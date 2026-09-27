# tests/test_scan_eod.py
from __future__ import annotations
from contextlib import closing
import pandas as pd
from tests.conftest import make_ohlcv_df
from jusmo_scanner.config import load_config
from jusmo_scanner.data.csv_provider import CSVProvider
from jusmo_scanner.storage import sqlite_store as store
from jusmo_scanner.jobs import scan_eod


def _run(provider, cfg, db_path, notifier=None, today=None):
    """scan_eod.run with `today` defaulting to the newest bar in the data, so
    fixtures with fixed 2026-01 dates are 'fresh' unless a test says otherwise."""
    if today is None and notifier is not None and provider.get_tickers():
        today = max(provider.get_ohlcv(t)["date"].max() for t in provider.get_tickers()).date()
    return scan_eod.run(provider, cfg, db_path, notifier=notifier, today=today)


class _FakeNotifier:
    def __init__(self):
        self.sent: list[str] = []

    def send_message(self, text: str) -> None:
        self.sent.append(text)


def _write_fixture_csv(csv_dir, rows):
    df = make_ohlcv_df(rows)
    df.to_csv(csv_dir / "TEST.csv", index=False)


def _event_rows(n_quiet=30):
    rows = [{"close": 1000, "high": 1010, "low": 990, "open": 1000,
             "volume": 100000, "trading_value": 1_000_000_000} for _ in range(n_quiet)]
    rows.append({"close": 1000, "high": 1020, "low": 980, "open": 1000,
                 "volume": 500000, "trading_value": 60_000_000_000})
    return rows


def test_run_writes_scan_results_and_sends_notification_on_transition(tmp_path):
    _write_fixture_csv(tmp_path, _event_rows())
    provider = CSVProvider(tmp_path)
    cfg = load_config("config/scanner.yaml")
    db_path = tmp_path / "scan.db"
    notifier = _FakeNotifier()
    _run(provider, cfg, db_path, notifier=notifier)
    assert store.get_latest_state(db_path, "TEST") is not None
    assert len(notifier.sent) >= 1  # at least the EVENT->ACCUMULATION transition


def test_run_twice_does_not_double_notify_bug9(tmp_path):
    _write_fixture_csv(tmp_path, _event_rows())
    provider = CSVProvider(tmp_path)
    cfg = load_config("config/scanner.yaml")
    db_path = tmp_path / "scan.db"
    notifier = _FakeNotifier()
    _run(provider, cfg, db_path, notifier=notifier)
    first_count = len(notifier.sent)
    _run(provider, cfg, db_path, notifier=notifier)  # rerun same data
    assert len(notifier.sent) == first_count  # no new notifications on rerun


def test_failed_send_is_retried_on_next_run(tmp_path):
    _write_fixture_csv(tmp_path, _event_rows())
    provider = CSVProvider(tmp_path)
    cfg = load_config("config/scanner.yaml")
    db_path = tmp_path / "scan.db"

    class _FailingNotifier:
        def __init__(self):
            self.attempts = 0

        def send_message(self, text: str) -> None:
            self.attempts += 1
            raise RuntimeError("simulated transient failure")

    failing_notifier = _FailingNotifier()
    _run(provider, cfg, db_path, notifier=failing_notifier)
    assert failing_notifier.attempts >= 1  # it tried

    # Rerun with a notifier that succeeds — the previously-failed
    # notification must be retried, not silently skipped as "already sent".
    succeeding_notifier = _FakeNotifier()
    _run(provider, cfg, db_path, notifier=succeeding_notifier)
    assert len(succeeding_notifier.sent) >= 1


def _multi_day_transition_rows(n_quiet=30):
    """Quiet history + event + several quiet post-event days, engineered so
    the state settles into DORMANT well before the LAST bar (i.e. the last
    bar has NO transition — prev_state == state on the final day)."""
    rows = [{"close": 1000, "high": 1010, "low": 990, "open": 1000,
             "volume": 100000, "trading_value": 1_000_000_000} for _ in range(n_quiet)]
    rows.append({"close": 1000, "high": 1020, "low": 980, "open": 1000,
                 "volume": 500000, "trading_value": 60_000_000_000})
    # several quiet, low-volume, tight-range days after the event so the
    # ticker settles into DORMANT and STAYS there for the last several bars
    rows += [{"close": 1000, "high": 1008, "low": 995, "open": 1000, "volume": 30000} for _ in range(10)]
    return rows


def test_bootstrap_does_not_replay_historical_notifications(tmp_path):
    _write_fixture_csv(tmp_path, _multi_day_transition_rows())
    provider = CSVProvider(tmp_path)
    cfg = load_config("config/scanner.yaml")
    db_path = tmp_path / "scan.db"
    notifier = _FakeNotifier()
    _run(provider, cfg, db_path, notifier=notifier)
    # Multiple historical transitions happened (EVENT->ACCUMULATION->DORMANT
    # etc. over the 10 quiet days), but NONE of them are on the final bar
    # (state has settled and stays DORMANT for the last several days), so
    # a first/bootstrap run must send ZERO notifications.
    import sqlite3
    with closing(sqlite3.connect(db_path)) as conn:
        transition_count = conn.execute("SELECT COUNT(*) FROM state_history").fetchone()[0]
    assert transition_count >= 1  # history WAS built
    assert len(notifier.sent) == 0  # but nothing was replayed as a notification


def test_today_transition_can_notify_once(tmp_path):
    # Reuses the same fixture-construction idea as the engine's bug7 test:
    # enough quiet history for HH60 to populate, then a genuine breakout on
    # the LAST bar, so there IS a real transition on the most recent day.
    rows = [{"close": 1000, "high": 1010, "low": 990, "open": 1000,
             "volume": 100000, "trading_value": 1_000_000_000} for _ in range(125)]
    rows[25]["high"] = 1100  # causal bottom anchor
    rows.append({"close": 1000, "high": 1020, "low": 980, "open": 1000,
                 "volume": 500000, "trading_value": 60_000_000_000})
    rows += [{"close": 1000, "high": 1008, "low": 995, "open": 1000, "volume": 30000} for _ in range(5)]
    rows.append({"close": 1200, "high": 1250, "low": 1190, "open": 1000, "volume": 5_000_000})
    _write_fixture_csv(tmp_path, rows)
    provider = CSVProvider(tmp_path)
    cfg = load_config("config/scanner.yaml")
    db_path = tmp_path / "scan.db"
    notifier = _FakeNotifier()
    _run(provider, cfg, db_path, notifier=notifier)
    # Exactly one notification: for the transition on the final (breakout) bar.
    assert len(notifier.sent) == 1


def _two_event_rows_csv():
    q = {"close": 1000, "high": 1010, "low": 990, "open": 1000,
         "volume": 100000, "trading_value": 1_000_000_000}
    ev = {"close": 1000, "high": 1020, "low": 980, "open": 1000,
          "volume": 500000, "trading_value": 60_000_000_000}
    t = {"close": 1000, "high": 1008, "low": 995, "open": 1000, "volume": 30000}
    return [dict(q) for _ in range(30)] + [dict(ev)] + [dict(t) for _ in range(10)] + [dict(ev)] + [dict(t) for _ in range(3)]


def _event_rows_in_db(db_path):
    import sqlite3
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute("SELECT ticker, event_date, episode_id FROM events ORDER BY event_date").fetchall()


def test_event_is_persisted(tmp_path):
    _write_fixture_csv(tmp_path, _two_event_rows_csv())
    db_path = tmp_path / "scan.db"
    _run(CSVProvider(tmp_path), load_config("config/scanner.yaml"), db_path)
    # 2026-01-01 + 30 days = 2026-01-31; second event 11 bars later
    assert _event_rows_in_db(db_path) == [
        ("TEST", "2026-01-31", "TEST:2026-01-31"),
        ("TEST", "2026-02-11", "TEST:2026-01-31"),
    ]


def test_event_persistence_is_idempotent(tmp_path):
    _write_fixture_csv(tmp_path, _two_event_rows_csv())
    db_path = tmp_path / "scan.db"
    cfg = load_config("config/scanner.yaml")
    _run(CSVProvider(tmp_path), cfg, db_path)
    first = _event_rows_in_db(db_path)
    _run(CSVProvider(tmp_path), cfg, db_path)
    assert len(first) == 2
    assert _event_rows_in_db(db_path) == first


def test_scanresult_formatter_uses_real_values(tmp_path):
    # 250 quiet bars so MA120/MA240 are defined, event, settle, then a real
    # breakout on the LAST bar (same idea as test_today_transition_can_notify_once).
    rows = [{"close": 1000, "high": 1010, "low": 990, "open": 1000,
             "volume": 100000, "trading_value": 1_000_000_000} for _ in range(250)]
    rows[150]["high"] = 1100  # causal bottom anchor
    rows.append({"close": 1000, "high": 1020, "low": 980, "open": 1000,
                 "volume": 500000, "trading_value": 60_000_000_000})
    rows += [{"close": 1000, "high": 1008, "low": 995, "open": 1000, "volume": 30000} for _ in range(5)]
    rows.append({"close": 1200, "high": 1250, "low": 1190, "open": 1000, "volume": 5_000_000})
    _write_fixture_csv(tmp_path, rows)
    notifier = _FakeNotifier()
    _run(CSVProvider(tmp_path), load_config("config/scanner.yaml"),
                 tmp_path / "scan.db", notifier=notifier)
    assert len(notifier.sent) == 1
    msg = notifier.sent[0]
    assert "BREAKOUT" in msg
    assert "600억원" in msg
    assert "0억원" not in msg.replace("600억원", "")
    assert "MA120: 1,002원" in msg
    assert "MA240: 1,001원" in msg
    assert "전고점: 1,020원" in msg
    assert "nan" not in msg.lower()
    assert ": 0원" not in msg
    assert "N/A" not in msg


def test_old_invalidated_transition_does_not_notify_on_first_run(tmp_path):
    import sqlite3
    q = {"close": 1000, "high": 1010, "low": 990, "open": 1000,
         "volume": 100000, "trading_value": 1_000_000_000}
    ev = {"close": 1000, "high": 1020, "low": 980, "open": 1000,
          "volume": 500000, "trading_value": 60_000_000_000}
    t = {"close": 1000, "high": 1008, "low": 995, "open": 1000, "volume": 30000}
    crash = {"close": 900, "high": 905, "low": 895, "open": 1000, "volume": 30000}
    rows = [dict(q) for _ in range(30)] + [dict(ev)] + [dict(t) for _ in range(3)] + [dict(crash)] \
        + [dict(t) for _ in range(60)]
    _write_fixture_csv(tmp_path, rows)
    db_path = tmp_path / "scan.db"
    notifier = _FakeNotifier()
    _run(CSVProvider(tmp_path), load_config("config/scanner.yaml"), db_path, notifier=notifier)
    with closing(sqlite3.connect(db_path)) as conn:
        to_states = {r[0] for r in conn.execute("SELECT to_state FROM state_history")}
    assert "INVALIDATED" in to_states  # the history was recorded...
    assert notifier.sent == []  # ...but nothing is replayed as a notification


def test_empty_universe_fails_fast(tmp_path):
    import pytest
    cfg = load_config("config/scanner.yaml")
    db_path = tmp_path / "scan.db"
    with pytest.raises(RuntimeError, match="Universe is empty; data provider is not configured"):
        _run(CSVProvider(tmp_path), cfg, db_path)
    assert not db_path.exists()


class _FailingProvider:
    def __init__(self, base, failing):
        self._base, self._failing = base, set(failing)

    def get_tickers(self):
        return self._base.get_tickers()

    def get_ohlcv(self, ticker):
        if ticker in self._failing:
            raise ValueError("boom")
        return self._base.get_ohlcv(ticker)


def test_all_tickers_failing_raises(tmp_path):
    import pytest
    _write_fixture_csv(tmp_path, _event_rows())
    provider = _FailingProvider(CSVProvider(tmp_path), {"TEST"})
    with pytest.raises(RuntimeError, match=r"No ticker scanned successfully \(1 tickers attempted\)"):
        _run(provider, load_config("config/scanner.yaml"), tmp_path / "scan.db")


def test_partial_ticker_failure_does_not_raise_and_persists_good_ticker(tmp_path):
    _write_fixture_csv(tmp_path, _event_rows())
    make_ohlcv_df(_event_rows()).assign(ticker="BAD").to_csv(tmp_path / "BAD.csv", index=False)
    provider = _FailingProvider(CSVProvider(tmp_path), {"BAD"})
    db_path = tmp_path / "scan.db"
    _run(provider, load_config("config/scanner.yaml"), db_path)
    assert store.get_latest_state(db_path, "TEST") is not None


def _int_and_float_frames():
    rows = _event_rows(30) + [
        {"close": 1000 + i, "high": 1010 + i, "low": 990, "open": 1000,
         "volume": 90000, "trading_value": 1_000_000_000} for i in range(6)
    ]
    int_df = make_ohlcv_df(rows)
    int_cols = ["open", "high", "low", "close", "volume", "trading_value"]
    for c in int_cols:
        int_df[c] = int_df[c].astype("int64")
    float_df = int_df.copy()
    for c in int_cols:
        float_df[c] = float_df[c].astype("float64")
    return int_df, float_df


def test_integer_dtype_input_is_stored_as_real_never_blob(tmp_path):
    import sqlite3
    int_df, _ = _int_and_float_frames()
    assert str(int_df["close"].dtype) == "int64"
    int_df.to_csv(tmp_path / "TEST.csv", index=False)
    db_path = tmp_path / "scan.db"
    _run(CSVProvider(tmp_path), load_config("config/scanner.yaml"), db_path)
    numeric = {
        "scan_results": ["structure_score", "trigger_score", "final_score", "close", "estimated_cost",
                         "cost_distance", "vcr", "rvol20", "event_trading_value", "ma120", "ma240", "prior_high"],
        "events": ["open", "high", "low", "close", "volume", "trading_value", "turnover", "value_ratio",
                   "capital_impact", "location120", "event_score", "event_price"],
    }
    with closing(sqlite3.connect(db_path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] > 0
        for table, cols in numeric.items():
            for col in cols:
                types = {t for (t,) in conn.execute(f"SELECT DISTINCT typeof({col}) FROM {table}")}
                assert types <= {"real", "null"}, f"{table}.{col} stored as {types}"


def test_integer_dtype_results_equal_float_dtype_results():
    from jusmo_scanner.scanner import engine
    int_df, float_df = _int_and_float_frames()
    cfg = load_config("config/scanner.yaml")
    a = engine.run_ticker(int_df, "TEST", cfg)
    b = engine.run_ticker(float_df, "TEST", cfg)
    assert len(a) == len(b) > 0
    for x, y in zip(a, b):
        assert x.state == y.state
        for f in ("close", "estimated_cost", "cost_distance", "vcr", "structure_score",
                  "trigger_score", "final_score", "event_trading_value", "ma120", "prior_high"):
            u, v = getattr(x, f), getattr(y, f)
            assert (u is None and v is None) or u == v or (u != u and v != v), f
        assert isinstance(x.close, float)


def _breakout_last_bar_rows():
    rows = [{"close": 1000, "high": 1010, "low": 990, "open": 1000,
             "volume": 100000, "trading_value": 1_000_000_000} for _ in range(125)]
    rows[25]["high"] = 1100  # causal bottom anchor
    rows.append({"close": 1000, "high": 1020, "low": 980, "open": 1000,
                 "volume": 500000, "trading_value": 60_000_000_000})
    rows += [{"close": 1000, "high": 1008, "low": 995, "open": 1000, "volume": 30000} for _ in range(5)]
    rows.append({"close": 1200, "high": 1250, "low": 1190, "open": 1000, "volume": 5_000_000})
    return rows


def _table_counts(db_path):
    import sqlite3
    with closing(sqlite3.connect(db_path)) as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("events", "scan_results", "state_history", "notification_log")}


def _run_freshness(tmp_path, age_days):
    _write_fixture_csv(tmp_path, _breakout_last_bar_rows())
    last_bar = pd.Timestamp("2026-01-01") + pd.Timedelta(days=len(_breakout_last_bar_rows()) - 1)
    notifier = _FakeNotifier()
    db_path = tmp_path / "scan.db"
    scan_eod.run(CSVProvider(tmp_path), load_config("config/scanner.yaml"), db_path,
                 notifier=notifier, today=(last_bar + pd.Timedelta(days=age_days)).date())
    return notifier, _table_counts(db_path)


import pytest


@pytest.mark.parametrize("age_days", [0, 1, 3, -2])  # -2: future-dated data is treated as fresh
def test_fresh_transition_is_notified(tmp_path, age_days):
    notifier, counts = _run_freshness(tmp_path, age_days)
    assert len(notifier.sent) == 1
    assert counts["notification_log"] == 1


@pytest.mark.parametrize("age_days", [4, 400])
def test_stale_transition_is_persisted_but_not_notified(tmp_path, age_days):
    notifier, counts = _run_freshness(tmp_path, age_days)
    assert notifier.sent == []
    assert counts["notification_log"] == 0
    assert counts["events"] == 1
    assert counts["scan_results"] == 7  # event bar + 5 quiet + breakout bar
    assert counts["state_history"] >= 2


def test_stale_data_does_not_block_later_fresh_notification(tmp_path):
    notifier, counts = _run_freshness(tmp_path, 10)
    assert notifier.sent == [] and counts["notification_log"] == 0
    # same DB rerun with a fresh "today" still notifies (nothing was logged as sent)
    last_bar = pd.Timestamp("2026-01-01") + pd.Timedelta(days=len(_breakout_last_bar_rows()) - 1)
    scan_eod.run(CSVProvider(tmp_path), load_config("config/scanner.yaml"), tmp_path / "scan.db",
                 notifier=notifier, today=last_bar.date())
    assert len(notifier.sent) == 1
