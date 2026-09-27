# tests/test_storage.py
from __future__ import annotations
from contextlib import closing
from jusmo_scanner.storage import sqlite_store as store

_EXTRA = dict(episode_id="T:2025-12-01", event_count=1, event_trading_value=6e10,
              ma120=None, ma240=None, prior_high=None)


def test_init_db_creates_all_tables(tmp_path):
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    import sqlite3
    with closing(sqlite3.connect(db_path)) as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"events", "scan_results", "state_history", "backtest_results"} <= tables


def test_insert_event_twice_same_key_does_not_duplicate_bug6(tmp_path):
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    kwargs = dict(ticker="T", event_date="2026-01-01", episode_id="T:2026-01-01",
                   open_=100, high=110, low=90, close=105, volume=1000,
                   trading_value=60_000_000_000, turnover=0.1, value_ratio=2.0,
                   capital_impact=0.05, location120=0.5, event_score=100.0, event_price=105.0)
    store.insert_event(db_path, **kwargs)
    store.insert_event(db_path, **kwargs)  # duplicate ticker+episode+event_date
    import sqlite3
    with closing(sqlite3.connect(db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM events WHERE ticker='T'").fetchone()[0]
    assert count == 1


def test_insert_scan_result_upserts_same_ticker_and_date(tmp_path):
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    store.insert_scan_result(db_path, ticker="T", scan_date="2026-01-01", state="DORMANT",
                              structure_score=50, trigger_score=40, theme_score=None, final_score=45,
                              structure_components={"event": 10}, trigger_components={"rvol": 5},
                              close=1000, estimated_cost=950, cost_distance=0.05, vcr=0.3, rvol20=1.0,
                              distribution_warning=False, **_EXTRA)
    store.insert_scan_result(db_path, ticker="T", scan_date="2026-01-01", state="IGNITION",
                              structure_score=60, trigger_score=70, theme_score=None, final_score=63,
                              structure_components={"event": 20}, trigger_components={"rvol": 15},
                              close=1010, estimated_cost=950, cost_distance=0.06, vcr=0.4, rvol20=1.6,
                              distribution_warning=False, **_EXTRA)
    import sqlite3
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute("SELECT state FROM scan_results WHERE ticker='T' AND scan_date='2026-01-01'").fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "IGNITION"


def test_insert_scan_result_stores_component_breakdown_as_json(tmp_path):
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    store.insert_scan_result(db_path, ticker="T", scan_date="2026-01-01", state="DORMANT",
                              structure_score=50, trigger_score=40, theme_score=None, final_score=45,
                              structure_components={"event": 10.0, "low_hold": 15.0},
                              trigger_components={"rvol": 5.0},
                              close=1000, estimated_cost=950, cost_distance=0.05, vcr=0.3, rvol20=1.0,
                              distribution_warning=False, **_EXTRA)
    import json
    import sqlite3
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute(
            "SELECT structure_components, trigger_components FROM scan_results WHERE ticker='T'"
        ).fetchone()
    assert json.loads(row[0]) == {"event": 10.0, "low_hold": 15.0}
    assert json.loads(row[1]) == {"rvol": 5.0}


def test_insert_state_transition_idempotent_bug9(tmp_path):
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    first = store.insert_state_transition(db_path, ticker="T", episode_id="T:2026-01-01", transition_date="2026-01-01",
                                           from_state="DORMANT", to_state="IGNITION")
    second = store.insert_state_transition(db_path, ticker="T", episode_id="T:2026-01-01", transition_date="2026-01-01",
                                            from_state="DORMANT", to_state="IGNITION")
    assert first is True
    assert second is False
    import sqlite3
    with closing(sqlite3.connect(db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM state_history WHERE ticker='T'").fetchone()[0]
    assert count == 1


def test_notification_is_idempotent(tmp_path):
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    first = store.insert_notification(db_path, ticker="T", episode_id="T:2026-01-01", state="IGNITION", transition_date="2026-01-05")
    second = store.insert_notification(db_path, ticker="T", episode_id="T:2026-01-01", state="IGNITION", transition_date="2026-01-05")
    assert first is True
    assert second is False
    import sqlite3
    with closing(sqlite3.connect(db_path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM notification_log WHERE ticker='T'").fetchone()[0]
    assert count == 1


def test_get_latest_state_returns_most_recent(tmp_path):
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    store.insert_scan_result(db_path, ticker="T", scan_date="2026-01-01", state="DORMANT",
                              structure_score=50, trigger_score=40, theme_score=None, final_score=45,
                              structure_components={"event": 10}, trigger_components={"rvol": 5},
                              close=1000, estimated_cost=950, cost_distance=0.05, vcr=0.3, rvol20=1.0,
                              distribution_warning=False, **_EXTRA)
    store.insert_scan_result(db_path, ticker="T", scan_date="2026-01-02", state="IGNITION",
                              structure_score=60, trigger_score=70, theme_score=None, final_score=63,
                              structure_components={"event": 20}, trigger_components={"rvol": 15},
                              close=1010, estimated_cost=950, cost_distance=0.06, vcr=0.4, rvol20=1.6,
                              distribution_warning=False, **_EXTRA)
    assert store.get_latest_state(db_path, "T") == "IGNITION"


def test_get_latest_state_none_when_no_rows(tmp_path):
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    assert store.get_latest_state(db_path, "UNKNOWN") is None


def test_events_unique_per_episode_and_persisted_columns(tmp_path):
    import sqlite3
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    kwargs = dict(ticker="T", event_date="2026-01-01", open_=100, high=110, low=90, close=105,
                  volume=1000, trading_value=6e10, turnover=0.1, value_ratio=2.0,
                  capital_impact=0.05, location120=0.5, event_score=100.0, event_price=105.0)
    store.insert_event(db_path, episode_id="T:2026-01-01", **kwargs)
    store.insert_event(db_path, episode_id="T:2026-01-01", **kwargs)
    with closing(sqlite3.connect(db_path)) as conn:
        rows = conn.execute("SELECT episode_id FROM events").fetchall()
    assert rows == [("T:2026-01-01",)]


def test_state_transition_unique_per_episode(tmp_path):
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    kw = dict(ticker="T", transition_date="2026-01-01", from_state="EVENT", to_state="ACCUMULATION")
    assert store.insert_state_transition(db_path, episode_id="T:a", **kw) is True
    assert store.insert_state_transition(db_path, episode_id="T:b", **kw) is True
    assert store.insert_state_transition(db_path, episode_id="T:a", **kw) is False


def test_insert_scan_result_stores_new_fields(tmp_path):
    import sqlite3
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    store.insert_scan_result(db_path, ticker="T", scan_date="2026-01-01", state="DORMANT",
                              structure_score=50, trigger_score=40, theme_score=None, final_score=45,
                              structure_components={}, trigger_components={},
                              close=1000, estimated_cost=950, cost_distance=0.05, vcr=0.3, rvol20=1.0,
                              distribution_warning=False, episode_id="T:2025-12-01", event_count=2,
                              event_trading_value=6e10, ma120=990.0, ma240=None, prior_high=1100.0)
    with closing(sqlite3.connect(db_path)) as conn:
        row = conn.execute("SELECT episode_id, event_count, event_trading_value, ma120, ma240, prior_high "
                           "FROM scan_results").fetchone()
    assert row == ("T:2025-12-01", 2, 6e10, 990.0, None, 1100.0)


def test_init_db_fresh_and_reinit_ok(tmp_path):
    import sqlite3
    db_path = tmp_path / "test.db"
    store.init_db(db_path)
    store.init_db(db_path)  # re-init of a current-version DB is fine
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION == 6


def test_init_db_rejects_legacy_schema_with_clear_error(tmp_path):
    import sqlite3
    import pytest
    db_path = tmp_path / "old.db"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ticker TEXT, cluster_id TEXT)")
        conn.commit()
    with pytest.raises(RuntimeError, match=r"older schema \(version 0, expected 6\)"):
        store.init_db(db_path)
