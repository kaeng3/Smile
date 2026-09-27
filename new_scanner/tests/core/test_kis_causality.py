from datetime import date

import pandas as pd
import pytest

from jusmo_scanner.backtest import cli_commands as cc
from jusmo_scanner.cli import _build_parser
from jusmo_scanner.data import kis_provider as kp
from jusmo_scanner.data.base import PriceAdjustmentMode
from jusmo_scanner.scanner.features import compute_all_features
from tests.kis_fake import FakeKisTransport, make_bars
from tests.core.test_kis_provider import make_provider


def test_kis_default_backtest_uses_full_available_history(monkeypatch, tmp_path):
    captured = {}
    def build(args, start, end, *rest):
        captured['start'] = start
        raise cc.CliError('stop before network')
    monkeypatch.setattr(cc, '_build_provider', build)
    args = _build_parser().parse_args(['backtest', '--provider', 'kis', '--start', '2021-01-01', '--output', str(tmp_path)])
    assert cc.dispatch(args) == 1
    assert captured['start'] == date(1980, 1, 1)


@pytest.mark.parametrize('cached', [False, True])
def test_kis_historical_fetch_never_attaches_current_snapshot_to_past_bar(tmp_path, cached):
    t = FakeKisTransport({'005930': make_bars(300)}, shares=2_000_000)
    p, _ = make_provider(tmp_path, t, end_date='20231229')
    if cached:
        p.get_ohlcv('005930')
    df = p.get_ohlcv('005930')
    assert df.date.iloc[-1] == pd.Timestamp('2023-12-29')
    assert df[['market_cap', 'free_float_shares']].isna().all().all()
    feats = compute_all_features(df)
    assert feats[['TURNOVER', 'CAPITAL_IMPACT']].isna().all().all()


def test_kis_cli_metadata_matches_actual_provider_semantics(monkeypatch, tmp_path):
    t = FakeKisTransport({'005930': make_bars(10)})
    def factory(start, end, **kw):
        p, _ = make_provider(tmp_path, t, start_date=start, end_date=end,
                             adjusted=kw.get('adjusted', True))
        return p
    monkeypatch.setattr(kp, 'KisProvider', factory)
    args = _build_parser().parse_args(['backtest', '--provider', 'kis', '--price-adjustment-mode', 'RAW'])
    p = cc._build_provider(args, date(2023, 1, 1), date(2024, 3, 15))
    p.get_ohlcv('005930')
    assert p.price_adjustment_mode is PriceAdjustmentMode.RAW
    assert t.daily_calls()[0]['params']['FID_ORG_ADJ_PRC'] == '1'
    for flag, value in [('--share-count-basis', 'FREE_FLOAT'), ('--price-adjustment-mode', 'UNKNOWN')]:
        args = _build_parser().parse_args(['backtest', '--provider', 'kis', flag, value])
        with pytest.raises(cc.CliError):
            cc._build_provider(args, None, None)


def test_legacy_cached_snapshot_cannot_reintroduce_lookahead(tmp_path):
    import json
    t = FakeKisTransport({'005930': make_bars(300)})
    p, _ = make_provider(tmp_path, t, end_date='20231229')
    expected = p.get_ohlcv('005930')
    _, meta_path = p._cache_paths('005930')
    meta = json.loads(meta_path.read_text())
    meta['snapshot'] = {'as_of': '2023-12-29', 'shares_outstanding': 2e6, 'market_cap_won': 2.6e9}
    meta_path.write_text(json.dumps(meta))
    cached, _ = make_provider(tmp_path, t, end_date='20231229')
    pd.testing.assert_frame_equal(cached.get_ohlcv('005930'), expected)


def test_pre1990_episode_survives_kis_history_policy(tmp_path):
    from tests.core.test_strategy_location import frame
    from jusmo_scanner.config import load_config
    from jusmo_scanner.scanner.engine import scan_ticker
    df = frame(920)
    df['date'] = pd.bdate_range(end='1990-01-12', periods=len(df))
    bars = [dict(date=r.date.strftime('%Y%m%d'), open=r.open, high=r.high, low=r.low,
                 close=r.close, volume=r.volume, tv=r.trading_value) for r in df.itertuples()]
    fs, fe, reason = cc.resolve_fetch_window(date(1990, 1, 1), date(1990, 1, 12), 1,
                                            explicit_end=date(1990, 1, 12), provider='kis')
    p, _ = make_provider(tmp_path, FakeKisTransport({'TEST': bars}), start_date=fs.isoformat(), end_date=fe.isoformat())
    result = scan_ticker(p.get_ohlcv('TEST'), 'TEST', load_config('config/scanner.yaml'), collect_snapshots=True)
    assert reason is None
    assert result.snapshots[-1].event_date.year == 1989
    assert result.snapshots[-1].signal_date.year == 1990
    assert result.snapshots[-1].strategy_family == 'BOTTOM_ACCUMULATION'
