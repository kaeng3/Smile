from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date

import numpy as np
import pytest

from jusmo_scanner.backtest.metrics import GroupStats
from jusmo_scanner.storage import sqlite_store as store


def _exp(eid="e1", **kw):
    row = {"experiment_id": eid, "created_at": "2026-01-01T00:00:00+00:00", "status": "RUNNING",
           "config_hash": "abc", "universe_size": 3, "git_dirty": False, "min_sample_size": 100,
           "schema_version": store.SCHEMA_VERSION, "horizons": "[1, 3]"}
    row.update(kw)
    return row


def _sig(uid="EP|BREAKOUT|10", eid="e1", variant="baseline", **kw):
    row = {"experiment_id": eid, "variant": variant, "signal_uid": uid, "signal_type": "BREAKOUT",
           "is_first_sample": True, "ticker": "T", "signal_date": date(2020, 1, 2), "bar_index": 10,
           "episode_id": "EP", "state": "BREAKOUT", "previous_state": "IGNITION",
           "event_date": date(2020, 1, 1), "days_since_event_trading": 3, "event_count_so_far": 1,
           "cluster_trading_value_so_far": 1e11, "events_in_last_20d": 1, "event_added_this_bar": False,
           "strong_event_this_bar": False, "accumulation_confirmed": True, "cross_ma120": False,
           "cross_ma240": True, "previous_high_break": True, "trend_break": False,
           "distribution_warning": False, "close": 1000.0, "vcr_anchor": 0.3, "location120": None,
           "rvol20": float("nan"), "days_since_previous_same_signal": None, "is_overlapping": True}
    row.update(kw)
    return row


def _res(uid="EP|BREAKOUT|10", eid="e1", variant="baseline", horizon=5, **kw):
    row = {"experiment_id": eid, "variant": variant, "signal_uid": uid, "entry_mode": "NEXT_OPEN",
           "signal_type": "BREAKOUT", "signal_semantics": "STANDARD", "horizon": horizon, "entry_price": np.float64(1000.0), "forward_return": np.float64(0.05),
           "mfe": 0.1, "mae": -0.02, **{f"hit_up_{p}": True for p in (5, 10)},
           **{f"hit_down_{p}": False for p in (3, 5)}}
    row.update(kw)
    return row


def _summary(eid="e1", **kw):
    row = {"experiment_id": eid, "analysis_name": "by_state", "variant": "baseline",
           "sample_mode": "ALL_SIGNALS", "entry_mode": "NEXT_OPEN", "dim1_name": "state",
           "dim1": "BREAKOUT", "dim2_name": "", "dim2": "", "signal_type": "BREAKOUT", "horizon": 5,
           **GroupStats(sample_count=3, sample_quality="VERY_LOW", low_sample=True, mean_return=0.02).to_dict(),
           "note": None}
    row.update(kw)
    return row


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "bt.db"
    store.init_db(p)
    return p


def _count(db, table, where="1"):
    with closing(sqlite3.connect(db)) as c:
        return c.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def test_schema_version_is_6_and_tables_exist(db):
    assert store.SCHEMA_VERSION == 6
    with closing(sqlite3.connect(db)) as c:
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"backtest_experiments", "backtest_signals", "backtest_results", "backtest_summary"} <= tables
        exp_cols = {r[1] for r in c.execute("PRAGMA table_info(backtest_experiments)")}
        assert {"source_data_start", "source_data_end", "signal_start", "signal_end"} <= exp_cols
        assert not ({"data_start", "data_end"} & exp_cols)
        assert {"history_truncated", "history_truncation_reason", "universe_basis",
                "tickers_with_missing_market_data", "missing_market_data_rows"} <= exp_cols
        cols = {r[1] for r in c.execute("PRAGMA table_info(backtest_results)")}
        assert "run_date" not in cols and {"signal_uid", "forward_return", "hit_down_20"} <= cols  # old table replaced
    assert not hasattr(store, "insert_backtest_result")


def test_v4_database_is_rejected_with_clear_error(tmp_path):
    p = tmp_path / "v4.db"
    with closing(sqlite3.connect(p)) as c:
        c.execute("CREATE TABLE backtest_experiments (experiment_id TEXT, signal_start TEXT)")
        c.execute("PRAGMA user_version = 4")
        c.commit()
    with pytest.raises(RuntimeError, match=r"older schema \(version 4, expected 6\)"):
        store.init_db(p)


def test_v3_database_is_rejected_with_clear_error(tmp_path):
    p = tmp_path / "v3.db"
    with closing(sqlite3.connect(p)) as c:
        c.execute("CREATE TABLE backtest_experiments (experiment_id TEXT, data_start TEXT)")
        c.execute("PRAGMA user_version = 3")
        c.commit()
    with pytest.raises(RuntimeError, match=r"older schema \(version 3, expected 6\)"):
        store.init_db(p)


def test_v2_database_is_rejected_with_clear_error(tmp_path):
    p = tmp_path / "v2.db"
    with closing(sqlite3.connect(p)) as c:
        c.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ticker TEXT)")
        c.execute("PRAGMA user_version = 2")
        c.commit()
    with pytest.raises(RuntimeError, match=r"older schema \(version 2, expected 6\)"):
        store.init_db(p)
    with closing(sqlite3.connect(p)) as c:  # rejected untouched
        assert c.execute("PRAGMA user_version").fetchone()[0] == 2
        assert c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='backtest_signals'").fetchone()[0] == 0


def test_round_trip(db):
    with store.connection(db) as conn:
        store.insert_backtest_experiment(conn, _exp(warnings_json='["w"]'))
        store.insert_backtest_signals_many(conn, [_sig(), _sig(uid="EP|PULLBACK|12", signal_type="PULLBACK")])
        store.insert_backtest_results_many(conn, [_res(), _res(horizon=10)])
        store.insert_backtest_summary_many(conn, [_summary()])
    with closing(sqlite3.connect(db)) as c:
        c.row_factory = sqlite3.Row
        e = c.execute("SELECT * FROM backtest_experiments").fetchone()
        assert e["experiment_id"] == "e1" and e["git_dirty"] == 0 and e["warnings_json"] == '["w"]'
        s = c.execute("SELECT * FROM backtest_signals WHERE signal_uid='EP|BREAKOUT|10'").fetchone()
        assert s["signal_date"] == "2020-01-02" and s["is_first_sample"] == 1 and s["accumulation_confirmed"] == 1
        assert s["location120"] is None and s["rvol20"] is None            # None and NaN -> NULL
        assert s["days_since_previous_same_signal"] is None and s["is_overlapping"] == 1
        assert s["vcr_anchor"] == 0.3 and s["days_since_previous_same_sample"] is None
        r = c.execute("SELECT * FROM backtest_results WHERE horizon=5").fetchone()
        assert (r["forward_return"], r["hit_up_5"], r["hit_down_3"], r["hit_up_30"]) == (0.05, 1, 0, None)
        m = c.execute("SELECT * FROM backtest_summary").fetchone()
        assert m["analysis"] == "by_state" and m["sample_count"] == 3 and m["low_sample"] == 1
        assert m["mean_return"] == 0.02 and m["std_return"] is None and m["note"] is None


def test_reruns_are_idempotent(db):
    for _ in range(3):
        with store.connection(db) as conn:
            store.insert_backtest_experiment(conn, _exp())
            store.insert_backtest_signals_many(conn, [_sig()])
            store.insert_backtest_results_many(conn, [_res(), _res(horizon=10)])
            store.insert_backtest_summary_many(conn, [_summary()])
    assert [_count(db, t) for t in ("backtest_experiments", "backtest_signals", "backtest_results",
                                    "backtest_summary")] == [1, 1, 2, 1]
    # a re-insert with different values REPLACES (same natural key), never duplicates
    with store.connection(db) as conn:
        store.insert_backtest_results_many(conn, [_res(mfe=0.5)])
        store.insert_backtest_summary_many(conn, [_summary(mean_return=0.5)])
    assert _count(db, "backtest_results", "mfe = 0.5") == 1 and _count(db, "backtest_summary") == 1
    assert _count(db, "backtest_summary", "mean_return = 0.5") == 1
    # different variant / experiment are distinct rows
    with store.connection(db) as conn:
        store.insert_backtest_signals_many(conn, [_sig(variant="vcr=0.2"), _sig(eid="e2")])
    assert _count(db, "backtest_signals") == 3


def test_no_blobs_and_only_plain_types(db):
    with store.connection(db) as conn:
        store.insert_backtest_experiment(conn, _exp())
        store.insert_backtest_signals_many(conn, [_sig(close=np.float64(1.5), bar_index=np.int64(4))])
        store.insert_backtest_results_many(conn, [_res()])
        store.insert_backtest_summary_many(conn, [_summary(mean_return=np.float32(0.25))])
    with closing(sqlite3.connect(db)) as c:
        for table in ("backtest_experiments", "backtest_signals", "backtest_results", "backtest_summary"):
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
            for col in cols:
                bad = c.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE typeof({col}) NOT IN ('integer','real','text','null')"
                ).fetchone()[0]
                assert bad == 0, (table, col)
        assert c.execute("SELECT typeof(close), typeof(bar_index) FROM backtest_signals").fetchone() == (
            "real", "integer")


def test_sql_value_coercions():
    assert store.sql_value(None) is None
    assert store.sql_value(float("nan")) is None and store.sql_value(float("inf")) is None
    assert store.sql_value(np.float64("nan")) is None
    assert store.sql_value(True) == 1 and store.sql_value(np.bool_(False)) == 0
    assert type(store.sql_value(np.int64(3))) is int and type(store.sql_value(np.float32(1.5))) is float
    assert store.sql_value(date(2020, 1, 2)) == "2020-01-02"
    for bad in (b"bytes", bytearray(b"x"), [1], {"a": 1}, object()):
        with pytest.raises(TypeError):
            store.sql_value(bad)


def test_unknown_columns_and_missing_experiment_id_rejected(db):
    with store.connection(db) as conn:
        with pytest.raises(ValueError, match="unknown column"):
            store.insert_backtest_signals_many(conn, [_sig(bogus=1)])
        with pytest.raises(ValueError, match="experiment_id"):
            store.insert_backtest_experiment(conn, {"created_at": "x"})
        with pytest.raises(ValueError, match="unknown experiment column"):
            store.update_backtest_experiment(conn, "e1", bogus=1)


def test_rollback_on_error_and_connection_closed(db):
    conn_ref = []
    with pytest.raises(RuntimeError):
        with store.connection(db) as conn:
            conn_ref.append(conn)
            store.insert_backtest_signals_many(conn, [_sig()])
            raise RuntimeError("boom")
    assert _count(db, "backtest_signals") == 0
    with pytest.raises(sqlite3.ProgrammingError):        # closed
        conn_ref[0].execute("SELECT 1")
    with store.connection(db) as conn:
        conn_ref.append(conn)
        store.insert_backtest_experiment(conn, _exp())
    with pytest.raises(sqlite3.ProgrammingError):
        conn_ref[1].execute("SELECT 1")


def test_update_and_delete_experiment(db):
    with store.connection(db) as conn:
        store.insert_backtest_experiment(conn, _exp())
        store.insert_backtest_signals_many(conn, [_sig()])
        store.insert_backtest_results_many(conn, [_res()])
        store.insert_backtest_summary_many(conn, [_summary()])
        store.insert_backtest_experiment(conn, _exp("other"))
        store.update_backtest_experiment(conn, "e1", status="COMPLETE", tickers_scanned=3)
    with closing(sqlite3.connect(db)) as c:
        assert c.execute("SELECT status, tickers_scanned FROM backtest_experiments WHERE experiment_id='e1'"
                         ).fetchone() == ("COMPLETE", 3)
    with store.connection(db) as conn:
        store.delete_backtest_experiment(conn, "e1")
    assert [_count(db, t, "experiment_id='e1'") for t in (
        "backtest_experiments", "backtest_signals", "backtest_results", "backtest_summary")] == [0, 0, 0, 0]
    assert _count(db, "backtest_experiments") == 1


def test_batch_insert_uses_executemany_in_one_transaction(db):
    calls = []

    class Spy:
        def __init__(self, conn):
            self._c = conn

        def executemany(self, sql, rows):
            calls.append(len(rows))
            return self._c.executemany(sql, rows)

        def __getattr__(self, n):
            return getattr(self._c, n)

    with store.connection(db) as conn:
        store.insert_backtest_signals_many(Spy(conn), [_sig(uid=f"u{i}") for i in range(50)])
        store.insert_backtest_results_many(Spy(conn), [_res(uid=f"u{i}") for i in range(50)])
        store.insert_backtest_signals_many(Spy(conn), [])   # empty batch is a no-op
    assert calls == [50, 50]
    assert _count(db, "backtest_signals") == 50
