# tests/test_engine.py
from __future__ import annotations
import pandas as pd
from tests.conftest import make_ohlcv_df
from jusmo_scanner.config import load_config
from jusmo_scanner.scanner import engine, state_machine as sm


def _cfg():
    return load_config("config/scanner.yaml")


def _quiet_then_event_rows(n_quiet: int = 30) -> list[dict]:
    rows = [{"close": 1000, "high": 1010, "low": 990, "open": 1000,
             "volume": 100000, "trading_value": 1_000_000_000} for _ in range(n_quiet)]
    rows.append({"close": 1000, "high": 1020, "low": 980, "open": 1000,
                 "volume": 500000, "trading_value": 60_000_000_000})
    return rows


def test_run_ticker_produces_one_result_per_bar_from_event_onward():
    rows = _quiet_then_event_rows(30)
    rows += [{"close": 1000, "high": 1010, "low": 990, "open": 1000, "volume": 90000} for _ in range(5)]
    df = make_ohlcv_df(rows)
    results = engine.run_ticker(df, ticker="TEST", cfg=_cfg())
    assert len(results) == 6  # event bar + 5 following bars
    assert results[0].state == sm.State.COST_TRACKING  # LOCATION120 unavailable with 30 bars


def test_run_ticker_never_crashes_on_new_listing_short_history_bug14():
    rows = _quiet_then_event_rows(5)  # far fewer than 240 bars of MA history
    df = make_ohlcv_df(rows)
    results = engine.run_ticker(df, ticker="TEST", cfg=_cfg())
    assert len(results) >= 1
    assert all(r.state != sm.State.BREAKOUT for r in results)  # can't confirm MA240 cross


def test_run_ticker_state_never_regresses_bug7():
    # HH60 = high.shift(1).rolling(60).max(), so genuinely reaching BREAKOUT
    # via hh60_break needs >=60 bars of quiet history before the breakout bar
    # (240-bar MA history is impractical for a unit fixture). 65 quiet bars
    # up front comfortably covers that, with headroom for the event bar and
    # a few settle bars in between.
    rows = _quiet_then_event_rows(125)
    rows[25]["high"] = 1100  # bottom anchor, outside recent indicator windows
    # A handful of quiet bars post-event so the ticker settles into
    # ACCUMULATION/DORMANT first, establishing the "before" state.
    rows += [{"close": 1000, "high": 1010, "low": 990, "open": 1000,
              "volume": 100000, "trading_value": 1_000_000_000} for _ in range(5)]
    # Genuine breakout day: close clearly clears the rolling 60-bar high
    # (~1020 from the event bar), with volume far above the >=1.3 rvol20
    # threshold (trailing 20-bar average volume is ~120k here).
    rows.append({"close": 1200, "high": 1250, "low": 1100, "open": 1050,
                 "volume": 5_000_000, "trading_value": 1_000_000_000})
    # Several bars afterward, deliberately quiet/tight-range again at the new
    # elevated price level -- exactly the conditions that would independently
    # satisfy DORMANT's low-VCR/tight-range10 entry condition if state were
    # allowed to regress.
    rows += [{"close": 1200, "high": 1210, "low": 1190, "open": 1200,
              "volume": 100000, "trading_value": 1_000_000_000} for _ in range(10)]
    df = make_ohlcv_df(rows)
    results = engine.run_ticker(df, ticker="TEST", cfg=_cfg())
    seen_breakout = False
    for r in results:
        if r.state == sm.State.BREAKOUT:
            seen_breakout = True
        if seen_breakout:
            assert r.state in (sm.State.BREAKOUT, sm.State.PULLBACK, sm.State.INVALIDATED)
    assert seen_breakout  # otherwise the loop above never actually checks anything


def test_run_ticker_handles_halted_bar_without_crash_bug13():
    rows = _quiet_then_event_rows(30)
    rows.append({"close": 1000, "high": 1000, "low": 1000, "open": 1000, "volume": 0, "trading_value": 0})
    df = make_ohlcv_df(rows)
    results = engine.run_ticker(df, ticker="TEST", cfg=_cfg())
    assert len(results) >= 1


from jusmo_scanner.data.base import DataProvider


class _PoisonedProvider(DataProvider):
    """Two healthy tickers, one that raises when read."""

    def __init__(self, good_df: pd.DataFrame):
        self._good_df = good_df

    def get_tickers(self) -> list[str]:
        return ["GOOD1", "POISON", "GOOD2"]

    def get_ohlcv(self, ticker: str) -> pd.DataFrame:
        if ticker == "POISON":
            raise ValueError("simulated bad data")
        return self._good_df.copy()


def test_run_scan_skips_poisoned_ticker_and_continues_bug11():
    rows = _quiet_then_event_rows(30)
    df = make_ohlcv_df(rows)
    provider = _PoisonedProvider(df)
    results = engine.run_scan(provider, provider.get_tickers(), _cfg())  # dict[str, TickerScan]
    assert "GOOD1" in results
    assert "GOOD2" in results
    assert "POISON" not in results


# ---------------------------------------------------------------------------
# Causal episode tests
# ---------------------------------------------------------------------------
import math
from jusmo_scanner.scanner import accumulation, features

_Q = {"close": 1000, "high": 1010, "low": 990, "open": 1000,
      "volume": 100000, "trading_value": 1_000_000_000}
_EV = {"close": 1000, "high": 1020, "low": 980, "open": 1000,
       "volume": 500000, "trading_value": 60_000_000_000}
_T = {"close": 1000, "high": 1008, "low": 995, "open": 1000, "volume": 30000}


def _rows(*parts) -> list[dict]:
    """parts are (row_dict, count) pairs."""
    out: list[dict] = []
    for row, n in parts:
        out += [dict(row) for _ in range(n)]
    return out


def _two_event_rows(gap: int = 38, event2: dict | None = None, tail: int = 5) -> list[dict]:
    return _rows((_Q, 30), (_EV, 1), (_T, gap), (event2 or _EV, 1), (_T, tail))


def test_new_event_does_not_reset_active_episode_state():
    df = make_ohlcv_df(_two_event_rows())
    results = engine.run_ticker(df, ticker="TEST", cfg=_cfg())
    event2_date = df["date"].iloc[30 + 1 + 38]
    assert len({r.episode_id for r in results}) == 1
    assert all(r.prev_state != sm.State.EVENT for r in results[1:])
    for r in results:
        if r.state != r.prev_state:
            assert r.state in sm.ALLOWED_TRANSITIONS[r.prev_state]
    r2 = next(r for r in results if r.scan_date == event2_date)
    before = [r for r in results if r.scan_date < event2_date][-1]
    # non-vacuous: the active episode had already settled to DORMANT (or later)
    assert before.state >= sm.State.DORMANT
    assert r2.event_count == 2
    assert r2.prev_state >= sm.State.DORMANT and r2.state >= sm.State.DORMANT
    assert not (r2.prev_state == sm.State.EVENT and r2.state == sm.State.ACCUMULATION)


def _invalidate_then_new_event_rows() -> list[dict]:
    crash = {"close": 900, "high": 905, "low": 895, "open": 1000, "volume": 30000}
    return _rows((_Q, 30), (_EV, 1), (_T, 5), (_EV, 1), (_T, 5), (crash, 1), (_T, 8), (_EV, 1), (_T, 3))


def test_new_episode_created_only_after_terminal_episode():
    df = make_ohlcv_df(_invalidate_then_new_event_rows())
    results = engine.run_ticker(df, ticker="TEST", cfg=_cfg())
    inv_idx = next(k for k, r in enumerate(results) if r.state == sm.State.INVALIDATED)
    first = results[:inv_idx + 1]
    second = results[inv_idx + 1:]
    # while episode 1 is active, its second event joins it: one episode id
    assert len({r.episode_id for r in first}) == 1
    assert first[-1].event_count == 2
    # the crash bar terminated it; a later independent event starts a new one
    assert second and second[0].episode_id != first[0].episode_id
    assert len({r.episode_id for r in second}) == 1
    assert second[0].scan_date == df["date"].iloc[30 + 1 + 5 + 1 + 5 + 1 + 8]
    assert (second[0].prev_state, second[0].state) == (sm.State.EVENT, sm.State.COST_TRACKING)
    assert second[0].event_count == 1
    assert all(r.state != sm.State.INVALIDATED for r in second)
    # no results on the bars between termination and the new event
    assert len(results) == len(first) + len(second)


def _compare_past(full, trunc, cutoff, fields):
    a = [r for r in full if r.scan_date < cutoff]
    b = list(trunc)
    assert len(a) == len(b) and len(a) > 0
    for x, y in zip(a, b):
        assert x.scan_date == y.scan_date
        for f in fields:
            vx, vy = getattr(x, f), getattr(y, f)
            if isinstance(vx, float) and math.isnan(vx):
                assert math.isnan(vy), f
            else:
                assert vx == vy, (x.scan_date, f, vx, vy)


_PAST_FIELDS = ["state", "prev_state", "episode_id", "event_count", "estimated_cost",
                "cost_distance", "structure_score", "trigger_score", "final_score", "vcr"]


def test_future_event_does_not_change_past_cluster_low():
    dip = {"close": 970, "high": 975, "low": 968, "open": 990, "volume": 30000}
    deep_event = {"close": 500, "high": 520, "low": 400, "open": 990,
                  "volume": 500000, "trading_value": 60_000_000_000}
    # event #1 (low 1000, close near its low so cost is close to the event
    # low), dip bar breaches only its event-low limit, recovery, then event #2
    # with a far lower low
    ev1 = {"close": 1005, "high": 1010, "low": 1000, "open": 1003,
           "volume": 500000, "trading_value": 60_000_000_000}
    # event #2 lands 5 days after event #1: inside the old 10-day cluster cooldown
    rows = _rows((_Q, 30), (ev1, 1), (_T, 2), (dip, 1), (_T, 1), (deep_event, 1), (_T, 3))
    df = make_ohlcv_df(rows)
    event2_pos = 30 + 1 + 2 + 1 + 1
    cutoff = df["date"].iloc[event2_pos]
    full = engine.run_ticker(df, "TEST", _cfg())
    trunc = engine.run_ticker(df.iloc[:event2_pos].reset_index(drop=True), "TEST", _cfg())
    _compare_past(full, trunc, cutoff, _PAST_FIELDS)
    inv = [r for r in trunc if r.state == sm.State.INVALIDATED]
    assert len(inv) == 1 and inv[0].scan_date == df["date"].iloc[30 + 1 + 2]

    # non-vacuity: had event #2's low leaked into the past bar's event-low
    # limit, the dip would NOT have been invalidated by the event-low breach.
    feat = features.compute_all_features(df)
    row = feat.iloc[30 + 1 + 2]
    atr = row["ATR20"]
    cfg = _cfg()
    true_limit = accumulation.compute_event_low_limit(1000, atr, cfg.atr_tolerance_event_low)
    leaked_limit = accumulation.compute_event_low_limit(400, atr, cfg.atr_tolerance_event_low)
    assert row["close"] < true_limit
    assert row["close"] >= leaked_limit
    # the cost-based breach alone would not have invalidated it
    assert row["close"] >= inv[0].estimated_cost - atr * cfg.atr_multiplier_invalidated


def test_future_event_does_not_change_past_cluster_cost():
    big = {"close": 1950, "high": 2000, "low": 1900, "open": 1950,
           "volume": 5_000_000, "trading_value": 90_000_000_000}
    # event #2 lands 5 days after event #1 (inside the old cluster cooldown)
    df = make_ohlcv_df(_two_event_rows(gap=4, event2=big))
    event2_pos = 30 + 1 + 4
    cutoff = df["date"].iloc[event2_pos]
    full = engine.run_ticker(df, "TEST", _cfg())
    trunc = engine.run_ticker(df.iloc[:event2_pos].reset_index(drop=True), "TEST", _cfg())
    _compare_past(full, trunc, cutoff, _PAST_FIELDS)
    # non-vacuous: the later event really does move cost once it happens
    before = [r for r in full if r.scan_date < cutoff][-1]
    after = [r for r in full if r.scan_date == cutoff][0]
    assert before.state >= sm.State.DORMANT
    assert after.estimated_cost > before.estimated_cost * 1.2
    assert after.event_count == 2 and before.event_count == 1


def test_one_result_per_bar_with_two_events_40_days_apart():
    df = make_ohlcv_df(_two_event_rows(gap=39))
    scan = engine.scan_ticker(df, "TEST", _cfg())
    dates = [r.scan_date for r in scan.results]
    assert len(dates) == len(set(dates))
    assert len(scan.events) == 2
    assert {e.episode_id for e in scan.events} == {scan.results[0].episode_id}
    assert (scan.events[1].event.event_date - scan.events[0].event.event_date).days >= 40


def _reference_anchored_vwap(df, anchor_idx: int) -> pd.Series:
    """Simple cumulative volume-weighted typical price from anchor_idx
    (inclusive, counted once); reference for the engine's incremental VWAP."""
    typical = accumulation.compute_typical_price(df["high"], df["low"], df["close"])
    tv = (typical * df["volume"]).iloc[anchor_idx:].cumsum()
    vol = df["volume"].iloc[anchor_idx:].cumsum()
    out = pd.Series(float("nan"), index=df.index, dtype="float64")
    out.iloc[anchor_idx:] = (tv / vol).to_numpy()
    return out


def _implied_vwap(r, event_price: float, cfg) -> float:
    return (r.estimated_cost - cfg.cost_weight_event_price * event_price) / cfg.cost_weight_vwap


def test_causal_vwap_matches_anchored_vwap_single_event():
    cfg = _cfg()
    rows = _rows((_Q, 30), (_EV, 1))
    for k in range(25):
        rows.append({"close": 1000 + (k % 5) * 3, "high": 1012 + k, "low": 996,
                     "open": 1000, "volume": 20000 + 1000 * k})
    df = make_ohlcv_df(rows)
    results = engine.run_ticker(df, "TEST", cfg)
    anchor = 30
    vwap = _reference_anchored_vwap(df, anchor)
    ev_price = accumulation.compute_typical_price(1020, 980, 1000)
    assert len(results) == len(df) - anchor
    for k, r in enumerate(results):
        assert math.isclose(_implied_vwap(r, ev_price, cfg), vwap.iloc[anchor + k], rel_tol=1e-9)


def test_causal_vwap_not_reanchored_by_later_event():
    cfg = _cfg()
    ev2 = {"close": 1100, "high": 1120, "low": 1080, "open": 1100,
           "volume": 400000, "trading_value": 60_000_000_000}
    df = make_ohlcv_df(_two_event_rows(gap=10, event2=ev2, tail=4))
    results = engine.run_ticker(df, "TEST", cfg)
    anchor = 30
    vwap = _reference_anchored_vwap(df, anchor)  # anchored at event #1 only
    p1 = accumulation.compute_typical_price(1020, 980, 1000)
    p2 = accumulation.compute_typical_price(1120, 1080, 1100)
    for k, r in enumerate(results):
        pos = anchor + k
        price = p1 if pos < 41 else (p1 + p2) / 2  # equal trading values
        assert math.isclose(_implied_vwap(r, price, cfg), vwap.iloc[pos], rel_tol=1e-9)


def _breakout_pullback_resurge_rows() -> list[dict]:
    rows = _rows((_Q, 125), (_EV, 1), (_Q, 5))
    rows[25]["high"] = 1100  # bottom anchor
    rows.append({"close": 1200, "high": 1250, "low": 1100, "open": 1050,
                 "volume": 5_000_000, "trading_value": 1_000_000_000})
    rows += _rows(({"close": 1125, "high": 1130, "low": 1120, "open": 1125,  # -10% from breakout high
                    "volume": 100000, "trading_value": 1_000_000_000}, 3))
    # fresh high-volume surge above the prior high (1250): breakout-qualifying
    rows.append({"close": 1400, "high": 1450, "low": 1200, "open": 1130,
                 "volume": 8_000_000, "trading_value": 1_000_000_000})
    rows += _rows(({"close": 1400, "high": 1410, "low": 1390, "open": 1400,
                    "volume": 100000, "trading_value": 1_000_000_000}, 5))
    return rows


def test_no_breakout_pullback_cycles():
    df = make_ohlcv_df(_breakout_pullback_resurge_rows())
    scan = engine.scan_ticker(df, "TEST", _cfg())
    states = [r.state for r in scan.results]
    first_pb = states.index(sm.State.PULLBACK)
    assert sm.State.BREAKOUT in states[:first_pb]
    # the surge bar (after PULLBACK) is breakout-qualifying; with the old
    # PULLBACK->BREAKOUT transition it re-entered BREAKOUT here.
    surge = next(r for r in scan.results if r.scan_date == df["date"].iloc[125 + 1 + 5 + 1 + 3])
    assert surge.prev_state == sm.State.PULLBACK and surge.state == sm.State.PULLBACK
    assert all(s in (sm.State.PULLBACK, sm.State.INVALIDATED) for s in states[first_pb:])
    transitions = [(r.prev_state, r.state) for r in scan.results if r.state != r.prev_state]
    assert transitions.count((sm.State.BREAKOUT, sm.State.PULLBACK)) <= 1
    assert (sm.State.PULLBACK, sm.State.BREAKOUT) not in transitions


# --- date validation (Stage 2 commit 2a) ---------------------------------------

def test_prepare_ticker_rejects_duplicate_and_non_monotonic_dates():
    import pytest
    from jusmo_scanner.scanner import engine as scan_engine
    from tests import synthetic as syn
    df = syn.success_frame()
    dup = df.copy()
    dup.loc[10, "date"] = dup.loc[9, "date"]
    with pytest.raises(ValueError, match="duplicate dates"):
        scan_engine.prepare_ticker(dup, 5)
    shuffled = df.iloc[[1, 0] + list(range(2, len(df)))].reset_index(drop=True)
    with pytest.raises(ValueError, match="non-monotonic dates"):
        scan_engine.prepare_ticker(shuffled, 5)
    assert scan_engine.prepare_ticker(df, 5).last_bar_date == df["date"].iloc[-1]


def test_run_scan_isolates_duplicate_date_ticker():
    from jusmo_scanner.config import load_config
    from jusmo_scanner.scanner import engine as scan_engine
    from tests import synthetic as syn
    good, bad = syn.success_frame(), syn.success_frame()
    bad.loc[300, "date"] = bad.loc[299, "date"]

    class P:
        def get_ohlcv(self, t):
            return {"GOOD": good, "BAD": bad}[t]

    scans = scan_engine.run_scan(P(), ["BAD", "GOOD"], load_config("config/scanner.yaml"))
    assert list(scans) == ["GOOD"]
