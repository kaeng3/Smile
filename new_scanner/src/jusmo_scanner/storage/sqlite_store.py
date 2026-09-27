# src/jusmo_scanner/storage/sqlite_store.py
from __future__ import annotations
import dataclasses
import json
import math
import numbers
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

from jusmo_scanner.backtest.metrics import GroupStats
from jusmo_scanner.scanner.snapshot import SignalSnapshot

SCHEMA_VERSION = 6
LOCATION_COLUMNS = ("strategy_family", "anchor_event_location", "event_location", "current_location", "cost_status")


@contextmanager
def _connection(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on error, and ALWAYS close (the plain
    `with sqlite3.connect()` form only commits/rolls back, it never closes)."""
    conn = sqlite3.connect(db_path)
    try:
        # Per-connection (not persisted); WAL + NORMAL is still crash-safe
        # against corruption, it only risks losing the last commits on power loss.
        conn.execute("PRAGMA synchronous=NORMAL")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    event_date TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, trading_value REAL, turnover REAL, value_ratio REAL,
    capital_impact REAL, location120 REAL, event_score REAL, event_price REAL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ticker, episode_id, event_date)
);

CREATE TABLE IF NOT EXISTS scan_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    scan_date TEXT NOT NULL,
    state TEXT NOT NULL,
    structure_score REAL, trigger_score REAL, theme_score REAL, final_score REAL,
    structure_components TEXT, trigger_components TEXT,
    close REAL, estimated_cost REAL, cost_distance REAL, vcr REAL, rvol20 REAL,
    distribution_warning INTEGER,
    episode_id TEXT, event_count INTEGER, event_trading_value REAL,
    ma120 REAL, ma240 REAL, prior_high REAL,
    strategy_family TEXT, anchor_event_location TEXT, event_location TEXT,
    current_location TEXT, cost_status TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ticker, scan_date)
);

CREATE TABLE IF NOT EXISTS state_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    transition_date TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ticker, episode_id, transition_date, to_state)
);

CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    state TEXT NOT NULL,
    transition_date TEXT NOT NULL,
    notified_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(ticker, episode_id, state, transition_date)
);

"""


# --- backtest tables (schema v4) ---------------------------------------------------
# Storage types are REAL / INTEGER / TEXT / NULL only (no BLOBs). Booleans are 0/1
# INTEGERs, dates ISO TEXT, missing values NULL (never NaN/inf, never a fake 0).

_PY_TO_SQL = {"float": "REAL", "int": "INTEGER", "bool": "INTEGER", "str": "TEXT", "date": "TEXT"}


def _sql_type(annotation: str) -> str:
    return _PY_TO_SQL[annotation.replace(" | None", "").strip()]


EXPERIMENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("experiment_id", "TEXT PRIMARY KEY"), ("created_at", "TEXT NOT NULL"), ("status", "TEXT"),
    ("config_hash", "TEXT"), ("config_json", "TEXT"), ("options_json", "TEXT"),
    # raw frames actually used (full history incl. warm-up) / requested SIGNAL window (NULL = none)
    ("source_data_start", "TEXT"), ("source_data_end", "TEXT"),
    ("signal_start", "TEXT"), ("signal_end", "TEXT"),
    ("universe_size", "INTEGER"), ("tickers_scanned", "INTEGER"), ("tickers_failed", "INTEGER"),
    ("failed_tickers_json", "TEXT"), ("variants_json", "TEXT"), ("sample_modes", "TEXT"), ("entry_mode", "TEXT"),
    ("price_adjustment_mode", "TEXT"), ("share_count_basis", "TEXT"), ("warnings_json", "TEXT"),
    ("git_commit", "TEXT"), ("git_dirty", "INTEGER"), ("horizons", "TEXT"),
    ("min_sample_size", "INTEGER"), ("schema_version", "INTEGER"),
    # history provenance: 1 when the fetched history was limited (explicit --fetch-start, or
    # tickers starting at the fetch start); reason text; as-of universe dates (JSON list)
    ("history_truncated", "INTEGER"), ("history_truncation_reason", "TEXT"), ("universe_basis", "TEXT"),
    # provider data quality (pykrx market-cap join gaps)
    ("tickers_with_missing_market_data", "INTEGER"), ("missing_market_data_rows", "INTEGER"),
)

_SIGNAL_KEY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("experiment_id", "TEXT NOT NULL"), ("variant", "TEXT NOT NULL"), ("signal_uid", "TEXT NOT NULL"),
    ("signal_type", "TEXT NOT NULL"), ("signal_category", "TEXT"), ("signal_semantics", "TEXT"),
    ("is_first_sample", "INTEGER NOT NULL"), ("share_count_basis", "TEXT"),
)
_SIGNAL_OVERLAP_COLUMNS: tuple[tuple[str, str], ...] = (
    # all-signals basis (== the ALL_SIGNALS sample basis)
    ("days_since_previous_same_signal", "INTEGER"), ("days_since_previous_signal", "INTEGER"),
    ("is_overlapping", "INTEGER"),
    # FIRST_SIGNAL_PER_EPISODE sample basis (NULL for rows that are not first samples)
    ("days_since_previous_same_sample", "INTEGER"), ("days_since_previous_sample", "INTEGER"),
    ("is_overlapping_sample", "INTEGER"),
    # distinct signal types firing on the same ticker/bar (all types, before filtering)
    ("signal_types_on_bar", "INTEGER"),
)
BACKTEST_SIGNAL_COLUMNS: tuple[tuple[str, str], ...] = _SIGNAL_KEY_COLUMNS + tuple(
    (f.name, _sql_type(f.type)) for f in dataclasses.fields(SignalSnapshot)) + _SIGNAL_OVERLAP_COLUMNS

RESULT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("experiment_id", "TEXT NOT NULL"), ("variant", "TEXT NOT NULL"), ("signal_uid", "TEXT NOT NULL"),
    ("entry_mode", "TEXT NOT NULL"), ("horizon", "INTEGER NOT NULL"),
    # results are never to be aggregated across signal types blindly
    ("signal_type", "TEXT NOT NULL"), ("signal_semantics", "TEXT"),
    ("entry_price", "REAL"), ("forward_return", "REAL"), ("mfe", "REAL"), ("mae", "REAL"),
    *[(f"hit_up_{p}", "INTEGER") for p in (5, 10, 15, 20, 30)],
    *[(f"hit_down_{p}", "INTEGER") for p in (3, 5, 10, 15, 20)],
)

_STATS_TYPES = {"sample_count": "INTEGER", "sample_quality": "TEXT", "low_sample": "INTEGER"}
SUMMARY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("experiment_id", "TEXT NOT NULL"), ("analysis", "TEXT NOT NULL"), ("variant", "TEXT NOT NULL"),
    ("sample_mode", "TEXT NOT NULL"), ("entry_mode", "TEXT NOT NULL"),
    ("dim1_name", "TEXT NOT NULL"), ("dim1", "TEXT NOT NULL"),
    ("dim2_name", "TEXT NOT NULL"), ("dim2", "TEXT NOT NULL"),
    ("signal_type", "TEXT NOT NULL"), ("horizon", "INTEGER NOT NULL"),
    ("variant_equals_baseline", "INTEGER"),
    *[(f.name, _STATS_TYPES.get(f.name, "REAL")) for f in dataclasses.fields(GroupStats)],
    ("note", "TEXT"),
)

_SIGNALS_UNIQUE = "UNIQUE(experiment_id, variant, signal_uid)"
_RESULTS_UNIQUE = "UNIQUE(experiment_id, variant, signal_uid, entry_mode, horizon)"
_SUMMARY_UNIQUE = ("UNIQUE(experiment_id, analysis, variant, sample_mode, entry_mode, "
                   "dim1_name, dim1, dim2_name, dim2, signal_type, horizon)")


def _create_table(name: str, cols: Sequence[tuple[str, str]], unique: str | None) -> str:
    body = ["id INTEGER PRIMARY KEY AUTOINCREMENT"] if unique else []
    body += [f"{c} {t}" for c, t in cols]
    if unique:
        body.append(unique)
    return f"CREATE TABLE IF NOT EXISTS {name} (\n    " + ",\n    ".join(body) + "\n);\n"


BACKTEST_SCHEMA = (
    _create_table("backtest_experiments", EXPERIMENT_COLUMNS, None)
    + _create_table("backtest_signals", BACKTEST_SIGNAL_COLUMNS, _SIGNALS_UNIQUE)
    + _create_table("backtest_results", RESULT_COLUMNS, _RESULTS_UNIQUE)
    + _create_table("backtest_summary", SUMMARY_COLUMNS, _SUMMARY_UNIQUE)
    + "CREATE INDEX IF NOT EXISTS idx_bt_signals_type ON backtest_signals(experiment_id, variant, signal_type);\n"
    + "CREATE INDEX IF NOT EXISTS idx_bt_signals_ticker ON backtest_signals(experiment_id, ticker);\n"
    + "CREATE INDEX IF NOT EXISTS idx_bt_summary_analysis ON backtest_summary(experiment_id, analysis, variant);\n"
)


def init_db(db_path: str | Path) -> None:
    with _connection(db_path) as conn:
        has_tables = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1"
        ).fetchone() is not None
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if has_tables and version not in (5, SCHEMA_VERSION):
            raise RuntimeError(
                f"scan.db was created with an older schema (version {version}, "
                f"expected {SCHEMA_VERSION}); delete it or migrate"
            )
        # Persistent per-file; done after the version guard so an old-schema
        # DB is rejected untouched. Reader/writer friendly and no per-commit fsync.
        conn.execute("PRAGMA journal_mode=WAL")
        if has_tables and version == 5:
            # Additive migration: old results remain NULL, never retroactively classified.
            for table in ("scan_results", "backtest_signals"):
                existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
                for column in LOCATION_COLUMNS:
                    if existing and column not in existing:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
        conn.executescript(SCHEMA)
        conn.executescript(BACKTEST_SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


_INSERT_EVENT_SQL = """INSERT OR IGNORE INTO events
               (ticker, event_date, episode_id, open, high, low, close, volume,
                trading_value, turnover, value_ratio, capital_impact, location120,
                event_score, event_price)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

_INSERT_SCAN_RESULT_SQL = """INSERT OR REPLACE INTO scan_results
               (ticker, scan_date, state, structure_score, trigger_score, theme_score,
                final_score, structure_components, trigger_components,
                close, estimated_cost, cost_distance, vcr, rvol20, distribution_warning,
                episode_id, event_count, event_trading_value, ma120, ma240, prior_high,
                strategy_family, anchor_event_location, event_location, current_location, cost_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

_INSERT_STATE_TRANSITION_SQL = (
    "INSERT OR IGNORE INTO state_history (ticker, episode_id, transition_date, from_state, to_state) "
    "VALUES (?, ?, ?, ?, ?)")

# Row layouts for the *_many batch APIs: plain tuples in exactly the positional
# order of the corresponding single-row function's parameters (after db_path).
# Events: (ticker, event_date, episode_id, open, high, low, close, volume,
#   trading_value, turnover, value_ratio, capital_impact, location120, event_score, event_price)
EventRow = tuple
# Scan results: same order as insert_scan_result's parameters; the two
# components dicts and distribution_warning are converted (JSON / int) here.
ScanResultRow = tuple
# State transitions: (ticker, episode_id, transition_date, from_state, to_state)
StateTransitionRow = tuple


def _scan_result_params(row: ScanResultRow) -> tuple:
    (ticker, scan_date, state, structure_score, trigger_score, theme_score, final_score,
     structure_components, trigger_components, close, estimated_cost, cost_distance, vcr,
     rvol20, distribution_warning, episode_id, event_count, event_trading_value,
     ma120, ma240, prior_high) = row[:21]
    return (ticker, scan_date, state, structure_score, trigger_score, theme_score,
            final_score, json.dumps(structure_components), json.dumps(trigger_components),
            close, estimated_cost, cost_distance, vcr, rvol20, int(distribution_warning),
            episode_id, event_count, event_trading_value, ma120, ma240, prior_high,
            *(row[21:] if len(row) > 21 else (None,) * 5))


def _events_many(conn: sqlite3.Connection, rows: Sequence[EventRow]) -> None:
    if rows:
        conn.executemany(_INSERT_EVENT_SQL, rows)


def _scan_results_many(conn: sqlite3.Connection, rows: Sequence[ScanResultRow]) -> None:
    if rows:
        conn.executemany(_INSERT_SCAN_RESULT_SQL, [_scan_result_params(r) for r in rows])


def _state_transitions_many(conn: sqlite3.Connection, rows: Sequence[StateTransitionRow]) -> None:
    if rows:
        conn.executemany(_INSERT_STATE_TRANSITION_SQL, rows)


def insert_events_many(db_path: str | Path, rows: Sequence[EventRow]) -> None:
    """Batch `insert_event` (INSERT OR IGNORE) in ONE transaction; all-or-nothing."""
    with _connection(db_path) as conn:
        _events_many(conn, rows)


def insert_scan_results_many(db_path: str | Path, rows: Sequence[ScanResultRow]) -> None:
    """Batch `insert_scan_result` (INSERT OR REPLACE) in ONE transaction; all-or-nothing."""
    with _connection(db_path) as conn:
        _scan_results_many(conn, rows)


def insert_state_transitions_many(db_path: str | Path, rows: Sequence[StateTransitionRow]) -> None:
    """Batch `insert_state_transition` (INSERT OR IGNORE) in ONE transaction; all-or-nothing."""
    with _connection(db_path) as conn:
        _state_transitions_many(conn, rows)


def persist_ticker_batch(
    db_path: str | Path, events: Sequence[EventRow],
    scan_results: Sequence[ScanResultRow], transitions: Sequence[StateTransitionRow],
) -> None:
    """Write one ticker's events, scan results and state transitions in a
    single connection/transaction (all-or-nothing)."""
    with _connection(db_path) as conn:
        _events_many(conn, events)
        _scan_results_many(conn, scan_results)
        _state_transitions_many(conn, transitions)


def insert_event(
    db_path: str | Path, ticker: str, event_date: str, episode_id: str,
    open_: float, high: float, low: float, close: float, volume: float,
    trading_value: float, turnover: float, value_ratio: float, capital_impact: float,
    location120: float, event_score: float, event_price: float,
) -> None:
    with _connection(db_path) as conn:
        conn.execute(
            _INSERT_EVENT_SQL,
            (ticker, event_date, episode_id, open_, high, low, close, volume,
             trading_value, turnover, value_ratio, capital_impact, location120,
             event_score, event_price),
        )


def insert_scan_result(
    db_path: str | Path, ticker: str, scan_date: str, state: str,
    structure_score: float, trigger_score: float, theme_score: float | None, final_score: float,
    structure_components: dict, trigger_components: dict,
    close: float, estimated_cost: float | None, cost_distance: float | None,
    vcr: float | None, rvol20: float, distribution_warning: bool,
    episode_id: str, event_count: int, event_trading_value: float,
    ma120: float | None, ma240: float | None, prior_high: float | None,
    strategy_family: str | None = None, anchor_event_location: str | None = None,
    event_location: str | None = None, current_location: str | None = None, cost_status: str | None = None,
) -> None:
    """`structure_components`/`trigger_components` are the per-component
    breakdown dicts from `scoring.compute_structure_score`/`compute_trigger_score`
    (their `["components"]` key), stored as JSON text for later debugging /
    Stage 2 backtest analysis — not queried directly by Stage 1 code."""
    with _connection(db_path) as conn:
        conn.execute(
            _INSERT_SCAN_RESULT_SQL,
            (ticker, scan_date, state, structure_score, trigger_score, theme_score,
             final_score, json.dumps(structure_components), json.dumps(trigger_components),
             close, estimated_cost, cost_distance, vcr, rvol20, int(distribution_warning),
             episode_id, event_count, event_trading_value, ma120, ma240, prior_high,
             strategy_family, anchor_event_location, event_location, current_location, cost_status),
        )


def insert_state_transition(db_path: str | Path, ticker: str, episode_id: str, transition_date: str, from_state: str, to_state: str) -> bool:
    """Returns True iff a new row was actually inserted. False means this
    exact transition was already recorded for this date — callers use this
    to avoid sending a duplicate Telegram notification on a rerun."""
    with _connection(db_path) as conn:
        cur = conn.execute(
            _INSERT_STATE_TRANSITION_SQL,
            (ticker, episode_id, transition_date, from_state, to_state),
        )
        return cur.rowcount > 0


def insert_notification(db_path: str | Path, ticker: str, episode_id: str, state: str, transition_date: str) -> bool:
    """Independent idempotency layer for Telegram notifications, separate
    from state_history's own dedup — returns True iff a new row was
    genuinely inserted (safe to notify), False if this exact
    (ticker, episode_id, state, transition_date) was already notified."""
    with _connection(db_path) as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO notification_log (ticker, episode_id, state, transition_date) VALUES (?, ?, ?, ?)",
            (ticker, episode_id, state, transition_date),
        )
        return cur.rowcount > 0


def has_been_notified(db_path: str | Path, ticker: str, episode_id: str, state: str, transition_date: str) -> bool:
    """Read-only check for whether this exact (ticker, episode_id, state,
    transition_date) has already been recorded in notification_log —
    used to decide whether to attempt a send at all, separately from
    insert_notification, which should only be called AFTER a confirmed
    successful send (see jobs/scan_eod.py)."""
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM notification_log WHERE ticker = ? AND episode_id = ? AND state = ? AND transition_date = ?",
            (ticker, episode_id, state, transition_date),
        ).fetchone()
        return row is not None


def get_latest_state(db_path: str | Path, ticker: str) -> str | None:
    with _connection(db_path) as conn:
        row = conn.execute(
            "SELECT state FROM scan_results WHERE ticker = ? ORDER BY scan_date DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        return row[0] if row else None


# --- backtest batch API --------------------------------------------------------------
# One connection per JOB: open it with `connection(db_path)`, pass it to the functions
# below (one executemany each), and `conn.commit()` after each ticker's batch. The
# context manager commits on success, rolls back on error and always closes.

connection = _connection


def sql_value(v: Any) -> Any:
    """Coerces a Python value to REAL/INTEGER/TEXT/NULL. NaN/inf -> NULL, bool -> 0/1,
    numpy scalars -> plain Python, dates -> ISO text. Anything else (incl. bytes,
    which would become a BLOB) raises TypeError."""
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return int(bool(v))
    if isinstance(v, numbers.Integral):
        return int(v)
    if isinstance(v, numbers.Real):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, str):
        return v
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    raise TypeError(f"cannot store {type(v).__name__} in SQLite without a BLOB: {v!r}")


def _rows_for(table: str, cols: Sequence[tuple[str, str]], rows: Sequence[Mapping[str, Any]]) -> list[tuple]:
    names = [c for c, _ in cols]
    known = set(names)
    out = []
    for r in rows:
        extra = set(r) - known
        if extra:
            raise ValueError(f"unknown column(s) for {table}: {', '.join(sorted(extra))}")
        out.append(tuple(sql_value(r.get(c)) for c in names))
    return out


def _insert_many(conn: sqlite3.Connection, table: str, cols: Sequence[tuple[str, str]],
                 rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    names = [c for c, _ in cols]
    sql = (f"INSERT OR REPLACE INTO {table} ({', '.join(names)}) "
           f"VALUES ({', '.join('?' * len(names))})")
    conn.executemany(sql, _rows_for(table, cols, rows))


def insert_backtest_experiment(conn: sqlite3.Connection, row: Mapping[str, Any]) -> None:
    """INSERT OR REPLACE of one experiment row (`experiment_id` required)."""
    if not row.get("experiment_id"):
        raise ValueError("experiment_id is required")
    _insert_many(conn, "backtest_experiments", EXPERIMENT_COLUMNS, [row])


def insert_backtest_signals_many(conn: sqlite3.Connection, rows: Sequence[Mapping[str, Any]]) -> None:
    """INSERT OR REPLACE (idempotent on experiment_id+variant+signal_uid). Keys of each
    row must be BACKTEST_SIGNAL_COLUMNS names; absent keys are NULL."""
    _insert_many(conn, "backtest_signals", BACKTEST_SIGNAL_COLUMNS, rows)


def insert_backtest_results_many(conn: sqlite3.Connection, rows: Sequence[Mapping[str, Any]]) -> None:
    """INSERT OR REPLACE (idempotent on experiment_id+variant+signal_uid+entry_mode+horizon)."""
    _insert_many(conn, "backtest_results", RESULT_COLUMNS, rows)


def insert_backtest_summary_many(conn: sqlite3.Connection, rows: Sequence[Mapping[str, Any]]) -> None:
    """INSERT OR REPLACE of summary rows. A row's `analysis_name` key is accepted as
    an alias of the `analysis` column."""
    fixed = [{("analysis" if k == "analysis_name" else k): v for k, v in r.items()} for r in rows]
    _insert_many(conn, "backtest_summary", SUMMARY_COLUMNS, fixed)


def update_backtest_experiment(conn: sqlite3.Connection, experiment_id: str, **fields: Any) -> None:
    known = {c for c, _ in EXPERIMENT_COLUMNS} - {"experiment_id"}
    bad = set(fields) - known
    if bad:
        raise ValueError(f"unknown experiment column(s): {', '.join(sorted(bad))}")
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE backtest_experiments SET {sets} WHERE experiment_id = ?",
                 [*(sql_value(v) for v in fields.values()), experiment_id])


def delete_backtest_experiment(conn: sqlite3.Connection, experiment_id: str) -> None:
    """Removes every row of one experiment (used before re-running the same id)."""
    for table in ("backtest_summary", "backtest_results", "backtest_signals", "backtest_experiments"):
        conn.execute(f"DELETE FROM {table} WHERE experiment_id = ?", (experiment_id,))
