# tests/test_storage_batch.py
"""Batch SQLite writes must be observably identical to the row-by-row APIs."""
from __future__ import annotations
import logging
import sqlite3
from contextlib import closing

import pytest

from tests.conftest import make_ohlcv_df
from jusmo_scanner.config import load_config
from jusmo_scanner.data.csv_provider import CSVProvider
from jusmo_scanner.jobs import scan_eod
from jusmo_scanner.notifier.formatter import format_scan_message
from jusmo_scanner.notifier.freshness import is_signal_fresh
from jusmo_scanner.scanner import engine
from jusmo_scanner.storage import sqlite_store as store

logger = logging.getLogger(__name__)
TABLES = ("events", "scan_results", "state_history", "notification_log")
VOLATILE = {"created_at", "notified_at"}  # datetime('now') defaults


def _run_reference(provider, cfg, db_path, notifier=None, today=None):
    """The pre-batching scan_eod.run: one single-row store call per row."""
    from datetime import date
    today = today or date.today()
    tickers = provider.get_tickers()
    if not tickers:
        raise RuntimeError("Universe is empty; data provider is not configured")
    store.init_db(db_path)
    all_scans = engine.run_scan(provider, tickers, cfg)
    if not all_scans:
        raise RuntimeError("No ticker scanned successfully")
    for ticker, scan in all_scans.items():
        for ee in scan.events:
            e = ee.event
            store.insert_event(
                db_path, ticker=ticker, event_date=str(e.event_date.date()), episode_id=ee.episode_id,
                open_=e.open, high=e.high, low=e.low, close=e.close, volume=e.volume,
                trading_value=e.trading_value, turnover=e.turnover, value_ratio=e.value_ratio,
                capital_impact=e.capital_impact, location120=e.location120,
                event_score=e.event_score, event_price=e.event_price)
        if not scan.results:
            continue
        latest = scan.last_bar_date
        for r in scan.results:
            scan_date = str(r.scan_date.date())
            store.insert_scan_result(
                db_path, ticker=r.ticker, scan_date=scan_date, state=r.state.name,
                structure_score=r.structure_score, trigger_score=r.trigger_score,
                structure_components=r.structure_components, trigger_components=r.trigger_components,
                theme_score=r.theme_score, final_score=r.final_score, close=r.close,
                estimated_cost=r.estimated_cost, cost_distance=r.cost_distance,
                vcr=r.vcr, rvol20=r.rvol20, distribution_warning=r.distribution_warning,
                episode_id=r.episode_id, event_count=r.event_count,
                event_trading_value=r.event_trading_value, ma120=r.ma120, ma240=r.ma240,
                prior_high=r.prior_high, strategy_family=r.strategy_family,
                anchor_event_location=r.anchor_event_location, event_location=r.event_location,
                current_location=r.current_location, cost_status=r.cost_status)
            if r.state == r.prev_state:
                continue
            store.insert_state_transition(
                db_path, ticker=r.ticker, episode_id=r.episode_id, transition_date=scan_date,
                from_state=r.prev_state.name, to_state=r.state.name)
            if r.scan_date != latest:
                continue
            if not is_signal_fresh(r.scan_date.date(), today, cfg.telegram_max_signal_age_days):
                continue
            if notifier is None:
                continue
            if store.has_been_notified(db_path, ticker=r.ticker, episode_id=r.episode_id,
                                       state=r.state.name, transition_date=scan_date):
                continue
            message = format_scan_message(
                ticker=r.ticker, name=r.ticker, state=r.state, prev_state=r.prev_state,
                close=r.close, event_date=str(r.anchor_event_date.date()),
                event_trading_value=r.event_trading_value, estimated_cost=r.estimated_cost,
                cost_distance=r.cost_distance, vcr=r.vcr, rvol20=r.rvol20,
                ma120=r.ma120, ma240=r.ma240, prior_high=r.prior_high,
                structure_score=r.structure_score, trigger_score=r.trigger_score,
                final_score=r.final_score, strategy_family=r.strategy_family, cost_status=r.cost_status)
            try:
                notifier.send_message(message)
            except Exception:
                logger.exception("send failed")
            else:
                store.insert_notification(db_path, ticker=r.ticker, episode_id=r.episode_id,
                                          state=r.state.name, transition_date=scan_date)


def _dump(db_path):
    """Every table, every column except timestamps, with SQLite storage type."""
    out = {}
    with closing(sqlite3.connect(db_path)) as conn:
        for t in TABLES:
            cols = [c[1] for c in conn.execute(f"PRAGMA table_info({t})") if c[1] not in VOLATILE]
            sel = ", ".join(f"{c}, typeof({c})" for c in cols)
            out[t] = conn.execute(f"SELECT {sel} FROM {t} ORDER BY id").fetchall()
    return out


class _Notifier:
    def __init__(self):
        self.sent = []

    def send_message(self, text):
        self.sent.append(text)


Q = {"close": 1000, "high": 1010, "low": 990, "open": 1000, "volume": 100000, "trading_value": 1_000_000_000}
EV = {"close": 1000, "high": 1020, "low": 980, "open": 1000, "volume": 500000, "trading_value": 60_000_000_000}
T = {"close": 1000, "high": 1008, "low": 995, "open": 1000, "volume": 30000}


def _multi_event_rows():
    # 65 quiet (HH60 populated) -> event -> settle -> event -> settle -> breakout on last bar
    rows = ([dict(Q) for _ in range(125)] + [dict(EV)] + [dict(T) for _ in range(10)]
            + [dict(EV)] + [dict(T) for _ in range(5)]
            + [{"close": 1200, "high": 1250, "low": 1190, "open": 1000, "volume": 5_000_000}])
    rows[25]['high'] = 1100  # bottom location without changing HH60/ATR20
    return rows


def _short_rows():  # <120 bars: ma120/ma240 etc. are NaN/None
    return [dict(Q) for _ in range(30)] + [dict(EV)] + [dict(T) for _ in range(6)]


def _write(csv_dir, rows, ticker="TEST", int_dtype=False):
    df = make_ohlcv_df(rows).assign(ticker=ticker)
    if int_dtype:
        for c in ("open", "high", "low", "close", "volume", "trading_value"):
            df[c] = df[c].astype("int64")
    df.to_csv(csv_dir / f"{ticker}.csv", index=False)


def _both(tmp_path, notify=True, twice=False):
    cfg = load_config("config/scanner.yaml")
    dbs, sent = {}, {}
    for name, runner in (("ref", _run_reference), ("new", scan_eod.run)):
        db = tmp_path / f"{name}.db"
        n = _Notifier()
        provider = CSVProvider(tmp_path)
        today = max(provider.get_ohlcv(t)["date"].max() for t in provider.get_tickers()).date()
        for _ in range(2 if twice else 1):
            runner(provider, cfg, db, notifier=n if notify else None, today=today)
        dbs[name], sent[name] = _dump(db), n.sent
    return dbs, sent


@pytest.mark.parametrize("twice", [False, True])
@pytest.mark.parametrize("case", ["multi_event", "int_dtype", "short_nan"])
def test_scan_eod_batch_equals_row_by_row(tmp_path, case, twice):
    rows = _short_rows() if case == "short_nan" else _multi_event_rows()
    _write(tmp_path, rows, "AAA", int_dtype=(case == "int_dtype"))
    _write(tmp_path, _short_rows(), "BBB")
    dbs, sent = _both(tmp_path, twice=twice)
    assert dbs["new"] == dbs["ref"]
    assert sent["new"] == sent["ref"]
    # sanity: the comparison is not vacuous
    assert len(dbs["new"]["scan_results"]) >= 14
    assert len(dbs["new"]["state_history"]) >= 2
    assert len(dbs["new"]["events"]) >= 2
    if case != "short_nan":
        assert len(dbs["new"]["notification_log"]) >= 1
    if case == "short_nan":
        assert any(v == "null" for row in dbs["new"]["scan_results"] for v in row)


def test_scan_eod_batch_equals_row_by_row_no_notifier(tmp_path):
    _write(tmp_path, _multi_event_rows(), "AAA")
    dbs, sent = _both(tmp_path, notify=False)
    assert dbs["new"] == dbs["ref"]
    assert sent["new"] == sent["ref"] == []


# ---- unit tests for the batch functions ------------------------------------

def _event_row(ticker="X", date="2026-01-01", episode="X:1", v=1.0):
    return (ticker, date, episode, v, v, v, v, v, v, v, v, v, v, v, v)


def _scan_row(ticker="X", date="2026-01-01", state="EVENT", score=1.0, dw=False, comps=None):
    return (ticker, date, state, score, 2.0, None, 3.0, comps or {"a": 1}, {"b": 2},
            1000.0, None, float("nan"), None, 1.5, dw, "X:1", 1, 5.0, None, None, None)


def _count(db, table):
    with closing(sqlite3.connect(db)) as conn:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@pytest.fixture
def db(tmp_path):
    p = tmp_path / "t.db"
    store.init_db(p)
    return p


def test_empty_batches_are_noops(db):
    store.insert_events_many(db, [])
    store.insert_scan_results_many(db, [])
    store.insert_state_transitions_many(db, [])
    store.persist_ticker_batch(db, [], [], [])
    assert all(_count(db, t) == 0 for t in TABLES)


def test_events_duplicates_are_ignored_first_wins(db):
    store.insert_events_many(db, [_event_row(v=1.0), _event_row(v=9.0), _event_row(date="2026-01-02")])
    store.insert_events_many(db, [_event_row(v=5.0)])
    with closing(sqlite3.connect(db)) as conn:
        rows = conn.execute("SELECT event_date, open FROM events ORDER BY id").fetchall()
    assert rows == [("2026-01-01", 1.0), ("2026-01-02", 1.0)]


def test_scan_results_duplicates_are_replaced_last_wins(db):
    store.insert_scan_results_many(db, [_scan_row(score=1.0), _scan_row(score=7.0, dw=True),
                                        _scan_row(date="2026-01-02")])
    with closing(sqlite3.connect(db)) as conn:
        rows = conn.execute(
            "SELECT scan_date, structure_score, distribution_warning, structure_components, cost_distance "
            "FROM scan_results ORDER BY scan_date").fetchall()
    assert rows == [("2026-01-01", 7.0, 1, '{"a": 1}', None), ("2026-01-02", 1.0, 0, '{"a": 1}', None)]


def test_state_transition_duplicates_are_ignored(db):
    row = ("X", "X:1", "2026-01-01", "DORMANT", "EVENT")
    store.insert_state_transitions_many(db, [row, row, ("X", "X:1", "2026-01-01", "DORMANT", "ACCUMULATION")])
    store.insert_state_transitions_many(db, [row])
    assert _count(db, "state_history") == 2


def test_batch_matches_single_row_api(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    store.init_db(a)
    store.init_db(b)
    ev, sr = _event_row(v=3.0), _scan_row(dw=True)
    store.insert_event(a, ev[0], ev[1], ev[2], *ev[3:])
    store.insert_scan_result(a, *sr)
    store.insert_state_transition(a, "X", "X:1", "2026-01-01", "DORMANT", "EVENT")
    store.persist_ticker_batch(b, [ev], [sr], [("X", "X:1", "2026-01-01", "DORMANT", "EVENT")])
    assert _dump(a) == _dump(b)


def test_exception_mid_batch_rolls_back_events(db):
    bad = _event_row(date="2026-01-02")[:5]  # wrong binding count -> error mid-executemany
    with pytest.raises(Exception):
        store.insert_events_many(db, [_event_row(), _event_row(date="2026-01-03"), bad])
    assert _count(db, "events") == 0


def test_exception_mid_batch_rolls_back_scan_results(db):
    with pytest.raises(Exception):
        store.insert_scan_results_many(db, [_scan_row(), _scan_row(date="2026-01-02"),
                                            _scan_row(date="2026-01-03", comps=object())])
    assert _count(db, "scan_results") == 0


def test_exception_mid_batch_rolls_back_transitions(db):
    ok = ("X", "X:1", "2026-01-01", "DORMANT", "EVENT")
    with pytest.raises(Exception):
        store.insert_state_transitions_many(db, [ok, ("X", "X:1", "2026-01-02", "A")])  # wrong binding count (OR IGNORE would swallow NOT NULL)
    assert _count(db, "state_history") == 0


def test_exception_in_persist_ticker_batch_rolls_back_everything(db):
    with pytest.raises(Exception):
        store.persist_ticker_batch(
            db, [_event_row()], [_scan_row()],
            [("X", "X:1", "2026-01-01", "A", "B"), ("X", "X:1", "2026-01-02", "A")])
    assert all(_count(db, t) == 0 for t in TABLES)


def test_init_db_enables_wal_and_guard_still_rejects_old_schema(tmp_path):
    p = tmp_path / "w.db"
    store.init_db(p)
    with closing(sqlite3.connect(p)) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    old = tmp_path / "old.db"
    with closing(sqlite3.connect(old)) as conn:
        conn.execute("CREATE TABLE x (a)")
        conn.commit()
    with pytest.raises(RuntimeError, match="older schema"):
        store.init_db(old)
    with closing(sqlite3.connect(old)) as conn:  # rejected untouched: still rollback-journal mode
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
