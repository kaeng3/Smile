"""Location routing must use the anchor's causal location, never today's location."""
import json

import pandas as pd
import pytest

from jusmo_scanner.config import load_config, override_config
from jusmo_scanner.scanner.engine import scan_ticker
from tests.conftest import make_ohlcv_df


def frame(anchor_close=920):
    rows = [dict(open=1000, high=1100, low=900, close=1000,
                 volume=100000, trading_value=1e9) for _ in range(125)]
    rows += [dict(open=anchor_close, high=anchor_close + 10, low=anchor_close - 10,
                  close=anchor_close, volume=1000000, trading_value=60e9)]
    rows += [dict(open=anchor_close, high=anchor_close + 5, low=anchor_close - 5,
                  close=anchor_close, volume=50000, trading_value=1e9) for _ in range(15)]
    return make_ohlcv_df(rows)


def scan(df, **overrides):
    cfg = override_config(load_config('config/scanner.yaml'), **overrides)
    return scan_ticker(df, 'TEST', cfg, collect_snapshots=True)


@pytest.mark.parametrize('price,location,family', [
    (920, 'BOTTOM', 'BOTTOM_ACCUMULATION'),
    (1000, 'MIDDLE', 'MIDDLE_COST_TRACKING'),
    (1080, 'HIGH', 'HIGH_COST_TRACKING'),
    (1150, 'HIGH', 'HIGH_COST_TRACKING'),
])
def test_routes_by_anchor_location(price, location, family):
    result = scan(frame(price))
    assert all(s.anchor_event_location == location for s in result.snapshots)
    assert all(s.strategy_family == family for s in result.snapshots)
    if location == 'BOTTOM':
        assert 'DORMANT' in {s.state for s in result.snapshots}
    else:
        assert {s.state for s in result.snapshots} == {'COST_TRACKING'}
        assert not any(s.accumulation_confirmed for s in result.snapshots)


def test_anchor_stays_bottom_when_new_high_event_joins_and_prefix_is_invariant():
    df = frame()
    df.loc[140, ['open', 'high', 'low', 'close', 'volume', 'trading_value']] = [1120, 1140, 1110, 1130, 2e6, 80e9]
    full = scan(df)
    joined = full.snapshots[-1]
    assert joined.anchor_event_location == 'BOTTOM'
    assert joined.event_location == 'HIGH'
    assert joined.current_location == 'HIGH'
    assert joined.strategy_family == 'BOTTOM_ACCUMULATION'
    assert joined.event_count_so_far == 2
    assert joined.state == 'BREAKOUT'
    for end in (126, 133, 140):
        prefix = scan(df.iloc[:end])
        assert [s.to_dict() for s in prefix.snapshots] == [s.to_dict() for s in full.snapshots if s.bar_index < end]
    json.dumps(joined.to_dict(), allow_nan=False)


def test_unknown_location_is_not_inferred_from_future_bars():
    df = frame().iloc[120:].reset_index(drop=True)
    result = scan(df)
    assert result.snapshots[0].anchor_event_location == 'UNKNOWN'
    assert result.snapshots[0].strategy_family == 'UNKNOWN_COST_TRACKING'
    assert all(s.state == 'COST_TRACKING' for s in result.snapshots)


def test_configurable_inclusive_boundaries():
    assert scan(frame(960)).snapshots[0].anchor_event_location == 'BOTTOM'
    assert scan(frame(1040)).snapshots[0].anchor_event_location == 'HIGH'
    assert scan(frame(1000), event_location_bottom_max=0.5).snapshots[0].strategy_family == 'BOTTOM_ACCUMULATION'
    for values in ((0.7, 0.7), (0.8, 0.2), (-0.1, 0.7), (0.3, float('nan'))):
        with pytest.raises(ValueError):
            scan(frame(), event_location_bottom_max=values[0], event_location_high_min=values[1])


def test_high_cost_breach_ends_episode_and_next_event_gets_new_family():
    df = frame(1080)
    df.loc[139, ['open', 'high', 'low', 'close']] = [900, 910, 890, 900]
    df.loc[140, ['open', 'high', 'low', 'close', 'volume', 'trading_value']] = [920, 930, 910, 920, 1e6, 60e9]
    result = scan(df)
    broken, restarted = result.snapshots[-2:]
    assert broken.state == 'INVALIDATED'
    assert broken.cost_status == 'BREACHED'
    assert restarted.strategy_family == 'BOTTOM_ACCUMULATION'
    assert restarted.episode_id != broken.episode_id


def test_cost_tracking_signals_persist_and_export(tmp_path):
    from jusmo_scanner.backtest.signals import extract_signals
    from jusmo_scanner.jobs.scan_eod import run
    from jusmo_scanner.data.base import DataProvider
    from contextlib import closing
    import sqlite3

    df = frame(1080)
    result = scan(df)
    assert 'COST_TRACKING' in {s.signal_type.name for s in extract_signals(result)}
    class Provider(DataProvider):
        def get_tickers(self):
            return ['TEST']
        def get_ohlcv(self, ticker):
            return df
    path = tmp_path / 'scan.db'
    run(Provider(), load_config('config/scanner.yaml'), path)
    with closing(sqlite3.connect(path)) as conn:
        row = conn.execute('SELECT strategy_family, anchor_event_location, cost_status FROM scan_results LIMIT 1').fetchone()
    assert row == ('HIGH_COST_TRACKING', 'HIGH', 'HOLD')


def test_v5_migration_keeps_historical_values_unknown(tmp_path):
    import sqlite3
    from contextlib import closing
    from jusmo_scanner.storage import sqlite_store as store
    db = tmp_path / 'old.db'
    store.init_db(db)
    with closing(sqlite3.connect(db)) as conn:
        for table in ('scan_results', 'backtest_signals'):
            for field in store.LOCATION_COLUMNS:
                conn.execute(f'ALTER TABLE {table} DROP COLUMN {field}')
        conn.execute("INSERT INTO scan_results(ticker, scan_date, state) VALUES ('OLD', '2020-01-01', 'IGNITION')")
        conn.execute('PRAGMA user_version = 5')
        conn.commit()
    store.init_db(db)
    store.init_db(db)
    with closing(sqlite3.connect(db)) as conn:
        assert conn.execute('SELECT ticker, state, strategy_family FROM scan_results').fetchone() == ('OLD', 'IGNITION', None)
        assert conn.execute('PRAGMA user_version').fetchone()[0] == 6
