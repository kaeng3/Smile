# src/jusmo_scanner/scanner/engine.py
from __future__ import annotations
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import logging

import numpy as np
import pandas as pd

from . import features, events, accumulation, pivots, trend, state_machine as sm, scoring
from .snapshot import SignalSnapshot, to_plain_float
from .location import classify_location, strategy_family

logger = logging.getLogger(__name__)


@dataclass
class ScanResult:
    ticker: str
    scan_date: pd.Timestamp
    state: sm.State
    prev_state: sm.State
    structure_score: float
    trigger_score: float
    structure_components: dict
    trigger_components: dict
    theme_score: float | None
    final_score: float
    close: float
    estimated_cost: float | None
    cost_distance: float | None
    vcr: float | None
    rvol20: float
    distribution_warning: bool
    anchor_event_date: pd.Timestamp
    episode_id: str
    event_count: int
    event_trading_value: float
    ma120: float | None
    ma240: float | None
    prior_high: float | None
    strategy_family: str = "UNKNOWN_COST_TRACKING"
    anchor_event_location: str = "UNKNOWN"
    event_location: str = "UNKNOWN"
    current_location: str = "UNKNOWN"
    cost_status: str | None = None


@dataclass
class EpisodeEvent:
    event: events.Event
    episode_id: str


@dataclass
class TickerScan:
    results: list[ScanResult]
    events: list[EpisodeEvent]
    last_bar_date: pd.Timestamp | None  # last date of the input DataFrame, not of the last result
    # Only populated with collect_snapshots=True: one causal SignalSnapshot per
    # result, same order/length as `results`.
    snapshots: list[SignalSnapshot] | None = None


@dataclass
class _Episode:
    episode_id: str
    anchor_event: events.Event
    event_count: int
    event_low_so_far: float
    event_score_so_far: float
    event_price_so_far: float
    cum_tv: float = 0.0
    cum_vol: float = 0.0
    state: sm.State = sm.State.EVENT
    had_breakout: bool = False
    breakout_high: float | None = None
    breakout_volume: float | None = None
    _price_tv_sum: float = 0.0
    _tv_sum: float = 0.0
    # Snapshot-only bookkeeping (never read by the state machine or scoring).
    anchor_pos: int = -1
    cluster_tv: float = 0.0
    latest_event_volume: float = float("nan")
    max_event_volume: float = float("nan")
    breakout_pos: int | None = None
    breakout_close: float | None = None
    breakout_hh60: float | None = None
    latest_event_location: str = "UNKNOWN"
    anchor_event_location: str = "UNKNOWN"

    def add_event(self, ev: events.Event) -> None:
        self.event_count += 1
        self.cluster_tv += ev.trading_value
        self.latest_event_volume = ev.volume
        if not (self.max_event_volume >= ev.volume):  # also true when max is NaN
            self.max_event_volume = ev.volume
        self.event_low_so_far = min(self.event_low_so_far, ev.low)
        self.event_score_so_far = max(self.event_score_so_far, ev.event_score)
        self._price_tv_sum += ev.event_price * ev.trading_value
        self._tv_sum += ev.trading_value
        if self._tv_sum > 0:
            self.event_price_so_far = self._price_tv_sum / self._tv_sum


def _new_episode(ticker: str, ev: events.Event, anchor_pos: int = -1) -> _Episode:
    ep = _Episode(
        episode_id=f"{ticker}:{ev.event_date.date()}", anchor_event=ev, event_count=1,
        event_low_so_far=ev.low, event_score_so_far=ev.event_score,
        event_price_so_far=ev.event_price, anchor_pos=anchor_pos,
        cluster_tv=ev.trading_value, latest_event_volume=ev.volume, max_event_volume=ev.volume,
    )
    ep._price_tv_sum = ev.event_price * ev.trading_value
    ep._tv_sum = ev.trading_value
    return ep


def _none_if_nan(x) -> float | None:
    return float(x) if pd.notna(x) else None


def compute_ticker_features(df: pd.DataFrame) -> pd.DataFrame:
    return features.compute_all_features(df)


def _thresholds(cfg) -> sm.ScannerThresholds:
    # With cost_hold_tolerance_pct set, the tolerance is applied to the cost
    # itself (see scan_prepared), so the ATR term must vanish here.
    tolerance_mode = cfg.cost_hold_tolerance_pct is not None
    return sm.ScannerThresholds(
        dormant_vcr_max=cfg.dormant_vcr_max,
        dormant_range10_max=cfg.dormant_range10_max,
        ignition_rvol20_min=cfg.ignition_rvol20_min,
        breakout_rvol20_min=cfg.breakout_rvol20_min,
        pullback_drawdown_min=cfg.pullback_drawdown_min,
        pullback_drawdown_max=cfg.pullback_drawdown_max,
        pullback_volume_ratio_max=cfg.pullback_volume_ratio_max,
        atr_multiplier_invalidated=0.0 if tolerance_mode else cfg.atr_multiplier_invalidated,
        distribution_location120_min=cfg.distribution_location120_min,
        distribution_rvol20_min=cfg.distribution_rvol20_min,
        distribution_upper_wick_min=cfg.distribution_upper_wick_min,
    )


@dataclass
class PreparedTicker:
    """Config-independent per-ticker data (features + swing highs for one
    window). Nothing derived from thresholds (e.g. events) may be stored here."""
    df: pd.DataFrame  # feature frame from compute_all_features
    swing_window: int
    swing_pos: np.ndarray
    swing_prices: np.ndarray
    last_bar_date: pd.Timestamp | None
    dates: list  # Timestamps, one per bar
    cols: dict[str, np.ndarray]  # pre-extracted columns used by the episode loop


_LOOP_COLUMNS = (
    "open", "high", "low", "close", "volume", "ATR20", "AVG_VOLUME_5", "MA120", "MA240", "HH60",
    "RANGE10", "MA5_SLOPE", "RVOL20", "LOCATION120", "UPPER_WICK_RATIO", "CAPITAL_IMPACT",
)
# Extra columns read only when collect_snapshots=True.
_SNAPSHOT_COLUMNS = (
    "MA5", "MA20", "MA60", "MA20_SLOPE", "CLOSE_LOCATION", "market_cap", "free_float_shares",
)


def _check_dates(df: pd.DataFrame) -> None:
    """Dates must be unique and strictly increasing: the loop maps date -> bar
    position, so a duplicate date would silently drop an event."""
    if "date" not in df.columns:
        return
    d = pd.Series(df["date"]).reset_index(drop=True)
    dup = d[d.duplicated(keep=False)]
    if len(dup):
        raise ValueError(f"duplicate dates in ticker frame: {sorted({str(x)[:10] for x in dup})[:5]}")
    if len(d) > 1 and not bool((d.iloc[1:].to_numpy() > d.iloc[:-1].to_numpy()).all()):
        raise ValueError("non-monotonic dates in ticker frame (must be strictly increasing)")


def prepare_ticker(df: pd.DataFrame, swing_window: int) -> PreparedTicker:
    _check_dates(df)
    feats = compute_ticker_features(df)
    swing_pos, swing_prices, _ = pivots.swing_high_table(feats, swing_window)
    return PreparedTicker(
        df=feats, swing_window=swing_window, swing_pos=swing_pos, swing_prices=swing_prices,
        last_bar_date=feats["date"].iloc[-1] if len(feats) else None,
        dates=list(feats["date"]),
        cols={c: feats[c].to_numpy() for c in _LOOP_COLUMNS},
    )


def scan_ticker(df: pd.DataFrame, ticker: str, cfg, theme_engine: scoring.ThemeEngine | None = None,
                collect_snapshots: bool = False) -> TickerScan:
    return scan_prepared(prepare_ticker(df, cfg.breakout_swing_window), ticker, cfg, theme_engine,
                         collect_snapshots=collect_snapshots)


def scan_prepared(prepared: PreparedTicker, ticker: str, cfg, theme_engine: scoring.ThemeEngine | None = None,
                  collect_snapshots: bool = False) -> TickerScan:
    """Single causal forward pass: at bar i only events at positions <= i
    influence outputs. One ScanResult per bar while an episode is active; a
    new event during an active episode joins it (never resets state/VWAP);
    INVALIDATED ends the episode and a later event starts a new one.

    With collect_snapshots=True a `SignalSnapshot` is built per result inside
    this same causal loop (TickerScan.snapshots); otherwise nothing extra runs."""
    swing_window = cfg.breakout_swing_window
    if prepared.swing_window != swing_window:
        raise ValueError(
            f"prepared swing_window {prepared.swing_window} != cfg.breakout_swing_window {swing_window}")
    theme_engine = theme_engine or scoring.NullThemeEngine()
    df = prepared.df
    raw_events = events.detect_events(df, ticker, cfg)
    swing_pos, swing_prices = prepared.swing_pos, prepared.swing_prices
    date_to_pos = {d: i for i, d in enumerate(prepared.dates)}
    events_by_pos = {date_to_pos[e.event_date]: e for e in raw_events}
    thresholds = _thresholds(cfg)
    cost_tol = cfg.cost_hold_tolerance_pct
    theme_score = theme_engine.get_score(ticker)
    dates = prepared.dates

    snapshots: list[SignalSnapshot] | None = None
    snap_cols: dict[str, np.ndarray] = {}
    event_positions: list[int] = []
    names = None
    if collect_snapshots:
        snapshots = []
        snap_cols = {c: df[c].to_numpy() for c in _SNAPSHOT_COLUMNS}
        event_positions = sorted(events_by_pos)
        if "name" in df.columns:
            names = df["name"].to_numpy()

    results: list[ScanResult] = []
    episode_events: list[EpisodeEvent] = []
    episode: _Episode | None = None

    cols = prepared.cols
    n = len(df)
    for i in range(n):
        ev = events_by_pos.get(i)
        if ev is not None:
            # NOTE: the event is applied to the running episode BEFORE this bar is
            # evaluated. An event landing on a bar that then invalidates the
            # episode is recorded under that (ending) episode and does NOT start
            # a new one (deliberate for now).
            if episode is None:
                episode = _new_episode(ticker, ev, anchor_pos=i)
                episode.anchor_event_location = classify_location(ev.location120, cfg)
            else:
                episode.add_event(ev)
            episode.latest_event_location = classify_location(ev.location120, cfg)
            episode_events.append(EpisodeEvent(event=ev, episode_id=episode.episode_id))
        if episode is None:
            continue

        state = episode.state
        typical = accumulation.compute_typical_price(cols["high"][i], cols["low"][i], cols["close"][i])
        episode.cum_tv += typical * cols["volume"][i]
        episode.cum_vol += cols["volume"][i]
        vwap = episode.cum_tv / episode.cum_vol if episode.cum_vol > 0 else float("nan")

        estimated_cost = accumulation.compute_estimated_cost(
            episode.event_price_so_far, vwap,
            cfg.cost_weight_event_price, cfg.cost_weight_vwap,
        )
        atr20 = cols["ATR20"][i] if pd.notna(cols["ATR20"][i]) else 0.0
        event_low_limit = accumulation.compute_event_low_limit(episode.event_low_so_far, atr20, cfg.atr_tolerance_event_low)
        event_low_hold = accumulation.is_event_low_hold(cols["close"][i], event_low_limit)
        if cost_tol is None:
            cost_floor = estimated_cost
            estimated_cost_hold = accumulation.is_estimated_cost_hold(
                cols["close"][i], estimated_cost, atr20, cfg.atr_multiplier_invalidated,
            )
        else:
            # Fixed-percentage floor replaces the ATR band (thresholds carry
            # atr_multiplier_invalidated=0, so the state machine sees the floor
            # as the cost). Scoring/ScanResult keep the real estimated_cost.
            cost_floor = estimated_cost * (1 - cost_tol)
            estimated_cost_hold = accumulation.is_estimated_cost_hold(
                cols["close"][i], cost_floor, atr20, 0.0,
            )
        # vcr intentionally references the anchor event's volume, not later events'
        vcr = accumulation.compute_vcr(cols["AVG_VOLUME_5"][i], episode.anchor_event.volume)
        cost_distance = accumulation.compute_cost_distance(cols["close"][i], estimated_cost)

        ma120_cross = bool(i > 0 and sm.is_golden_cross(
            cols["close"][i - 1], cols["MA120"][i - 1], cols["close"][i], cols["MA120"][i]))
        ma240_cross = bool(i > 0 and sm.is_golden_cross(
            cols["close"][i - 1], cols["MA240"][i - 1], cols["close"][i], cols["MA240"][i]))
        hh60_break = bool(pd.notna(cols["HH60"][i]) and cols["close"][i] > cols["HH60"][i])

        confirmed_pos, confirmed_prices = pivots.latest_confirmed_swing_highs(
            swing_pos, swing_prices, as_of_position=i, window=swing_window, n=2,
        )
        line = trend.fit_resistance_line(confirmed_pos, confirmed_prices) if len(confirmed_pos) >= 2 else None
        resistance_break = bool(line is not None and cols["close"][i] > trend.line_value(line, i))

        signals = sm.StateSignals(
            event_low_hold=event_low_hold,
            estimated_cost_hold=estimated_cost_hold,
            vcr=vcr if vcr == vcr else float("inf"),
            range10=cols["RANGE10"][i] if pd.notna(cols["RANGE10"][i]) else float("inf"),
            ma5_slope=cols["MA5_SLOPE"][i] if pd.notna(cols["MA5_SLOPE"][i]) else float("nan"),
            ma120_cross=ma120_cross,
            ma240_cross=ma240_cross,
            rvol20=cols["RVOL20"][i] if pd.notna(cols["RVOL20"][i]) else 0.0,
            hh60_break=hh60_break,
            resistance_break=resistance_break,
            had_breakout=episode.had_breakout,
            breakout_high=episode.breakout_high,
            close=cols["close"][i],
            current_volume=cols["volume"][i],
            breakout_volume=episode.breakout_volume,
            event_low_limit=event_low_limit,
            estimated_cost=cost_floor,
            atr20=atr20,
        )

        new_state = sm.next_state(state, signals, thresholds,
                                  bottom_accumulation=episode.anchor_event_location == "BOTTOM")
        if new_state == sm.State.BREAKOUT and state != sm.State.BREAKOUT:
            episode.breakout_high = cols["high"][i]
            episode.breakout_volume = cols["volume"][i]
            episode.had_breakout = True
            if snapshots is not None:
                episode.breakout_pos = i
                episode.breakout_close = float(cols["close"][i])
                episode.breakout_hh60 = to_plain_float(cols["HH60"][i])

        distribution_warning = sm.is_distribution_warning(
            cols["LOCATION120"][i] if pd.notna(cols["LOCATION120"][i]) else 0.0,
            cols["RVOL20"][i] if pd.notna(cols["RVOL20"][i]) else 0.0,
            cols["UPPER_WICK_RATIO"][i] if pd.notna(cols["UPPER_WICK_RATIO"][i]) else 0.0,
            cols["close"][i], cols["open"][i], thresholds,
        )

        # NaN/invalid inputs are intentionally passed through as-is here
        # (not pre-converted to a sentinel) — every scoring.score_* function
        # already guards NaN/inf internally via _safe() and returns 0.0 for
        # that component, which is the correct "missing data -> no points"
        # behavior. Pre-converting NaN to e.g. 0.0 here would be wrong: a
        # NaN cost_distance would then look like "0% from cost" (max points)
        # instead of "unknown" (0 points).
        structure_result = scoring.compute_structure_score(
            event_score=episode.event_score_so_far,
            event_low_hold=event_low_hold,
            estimated_cost_hold=estimated_cost_hold,
            cost_distance=cost_distance,
            vcr=vcr,
            range10=cols["RANGE10"][i],
            capital_impact=cols["CAPITAL_IMPACT"][i],
            distribution_warning=distribution_warning,
            cfg=cfg,
        )
        trigger_result = scoring.compute_trigger_score(
            ma240_cross=ma240_cross,
            ma120_cross=ma120_cross,
            ma5_slope=cols["MA5_SLOPE"][i] if pd.notna(cols["MA5_SLOPE"][i]) else 0.0,
            hh60_break=hh60_break,
            resistance_break=resistance_break,
            rvol20=cols["RVOL20"][i] if pd.notna(cols["RVOL20"][i]) else 0.0,
            close=cols["close"][i],
            ma240=cols["MA240"][i] if pd.notna(cols["MA240"][i]) else float("nan"),
            state=new_state,
            cfg=cfg,
        )
        final_score = scoring.compute_final_score(structure_result["total"], trigger_result["total"], theme_score, cfg)

        results.append(ScanResult(
            ticker=ticker, scan_date=dates[i], state=new_state, prev_state=state,
            structure_score=structure_result["total"], trigger_score=trigger_result["total"],
            structure_components=structure_result["components"], trigger_components=trigger_result["components"],
            theme_score=theme_score,
            final_score=final_score, close=float(cols["close"][i]), estimated_cost=estimated_cost,
            cost_distance=cost_distance, vcr=vcr, rvol20=cols["RVOL20"][i],
            distribution_warning=distribution_warning, anchor_event_date=episode.anchor_event.event_date,
            episode_id=episode.episode_id, event_count=episode.event_count,
            event_trading_value=float(episode.anchor_event.trading_value),  # intentionally the anchor event's
            ma120=_none_if_nan(cols["MA120"][i]), ma240=_none_if_nan(cols["MA240"][i]),
            prior_high=_none_if_nan(cols["HH60"][i]),
            strategy_family=strategy_family(episode.anchor_event_location),
            anchor_event_location=episode.anchor_event_location,
            event_location=episode.latest_event_location,
            current_location=classify_location(cols["LOCATION120"][i], cfg),
            cost_status="HOLD" if estimated_cost_hold else "BREACHED",
        ))

        if snapshots is not None:
            snapshots.append(_build_snapshot(
                i=i, ticker=ticker, cfg=cfg, cols=cols, snap_cols=snap_cols, names=names, dates=dates,
                episode=episode, ev=ev, state=state, new_state=new_state,
                event_positions=event_positions,
                event_low_hold=event_low_hold, estimated_cost_hold=estimated_cost_hold,
                estimated_cost=estimated_cost, cost_distance=cost_distance, vcr=vcr,
                ma120_cross=ma120_cross, ma240_cross=ma240_cross, hh60_break=hh60_break,
                resistance_break=resistance_break, distribution_warning=distribution_warning,
                structure_score=structure_result["total"], trigger_score=trigger_result["total"],
                final_score=final_score, theme_score=theme_score,
            ))

        episode.state = new_state
        if new_state == sm.State.INVALIDATED:
            episode = None

    return TickerScan(results=results, events=episode_events, last_bar_date=prepared.last_bar_date,
                      snapshots=snapshots)


def _ratio_minus_one(num, den) -> float | None:
    """(num - den) / den, None when either side is missing or den is 0."""
    n, d = to_plain_float(num), to_plain_float(den)
    if n is None or d is None or d == 0:
        return None
    return to_plain_float((n - d) / d)


def _build_snapshot(*, i, ticker, cfg, cols, snap_cols, names, dates, episode, ev, state, new_state,
                    event_positions, event_low_hold, estimated_cost_hold, estimated_cost,
                    cost_distance, vcr, ma120_cross, ma240_cross, hh60_break, resistance_break,
                    distribution_warning, structure_score, trigger_score, final_score,
                    theme_score) -> SignalSnapshot:
    """Assemble the snapshot for bar i. Only reads columns at index <= i and the
    episode's running (causal) state; called after this bar's episode updates."""
    f = to_plain_float
    close = float(cols["close"][i])
    anchor = episode.anchor_event
    days_since_event = i - episode.anchor_pos
    avg_vol5 = cols["AVG_VOLUME_5"][i]

    def vcr_against(volume):
        # same semantics as accumulation.compute_vcr (NaN when the volume is 0/NaN)
        return f(accumulation.compute_vcr(avg_vol5, volume))

    vcr_anchor = f(vcr)
    accumulation_confirmed = bool(
        episode.anchor_event_location == "BOTTOM" and vcr_anchor is not None
        and days_since_event >= cfg.backtest_accumulation_min_days
        and event_low_hold and estimated_cost_hold
        and vcr_anchor <= cfg.backtest_accumulation_vcr_max
    )
    # raw events at bars i-19..i (event_positions is sorted; all entries <= i count)
    n_recent = bisect_right(event_positions, i) - bisect_left(event_positions, i - 19)

    ma5, ma20, ma60 = f(snap_cols["MA5"][i]), f(snap_cols["MA20"][i]), f(snap_cols["MA60"][i])
    ma120, ma240 = f(cols["MA120"][i]), f(cols["MA240"][i])
    hh60 = f(cols["HH60"][i])

    # breakout context (None until the episode has had a breakout)
    bo: dict = {}
    if episode.had_breakout and episode.breakout_pos is not None:
        bo_vol = f(episode.breakout_volume)
        vol = f(cols["volume"][i])
        bo = dict(
            breakout_date=dates[episode.breakout_pos].date(),
            days_since_breakout=i - episode.breakout_pos,
            breakout_price=episode.breakout_close,
            breakout_high=f(episode.breakout_high),
            pullback_depth=_ratio_minus_one(close, episode.breakout_high),
            pullback_volume_ratio=(vol / bo_vol) if vol is not None and bo_vol else None,
            distance_to_ma20=_ratio_minus_one(close, ma20),
            distance_to_ma60=_ratio_minus_one(close, ma60),
            distance_to_ma120=_ratio_minus_one(close, ma120),
            distance_to_ma240=_ratio_minus_one(close, ma240),
            previous_high_hold=(close >= episode.breakout_hh60) if episode.breakout_hh60 is not None else None,
        )

    return SignalSnapshot(
        ticker=ticker,
        name=(None if names is None or pd.isna(names[i]) else str(names[i])),
        signal_date=dates[i].date(),
        bar_index=i,
        episode_id=episode.episode_id,
        state=new_state.name,
        previous_state=state.name,
        event_date=anchor.event_date.date(),
        days_since_event_trading=days_since_event,
        event_trading_value=f(anchor.trading_value),
        event_score=f(anchor.event_score),
        event_strength_class="STRONG" if anchor.event_score >= 100 else "CORE",
        event_value_ratio=f(anchor.value_ratio),
        event_turnover=f(anchor.turnover),
        event_close_location=f(snap_cols["CLOSE_LOCATION"][episode.anchor_pos]),
        event_capital_impact=f(anchor.capital_impact),
        event_location120=f(anchor.location120),
        event_location=episode.latest_event_location,
        anchor_event_location=episode.anchor_event_location,
        current_location=classify_location(cols["LOCATION120"][i], cfg),
        strategy_family=strategy_family(episode.anchor_event_location),
        cost_status="HOLD" if estimated_cost_hold else "BREACHED",
        event_count_so_far=episode.event_count,
        cluster_trading_value_so_far=float(episode.cluster_tv),
        events_in_last_20d=n_recent,
        event_added_this_bar=ev is not None,
        strong_event_this_bar=bool(ev is not None and ev.event_score >= 100),
        capital_impact=f(cols["CAPITAL_IMPACT"][i]),
        location120=f(cols["LOCATION120"][i]),
        estimated_cost=f(estimated_cost),
        cost_distance=f(cost_distance),
        event_low=f(episode.event_low_so_far),
        event_low_distance=_ratio_minus_one(close, episode.event_low_so_far),
        vcr_anchor=vcr_anchor,
        vcr_latest_event=vcr_against(episode.latest_event_volume),
        vcr_max_event=vcr_against(episode.max_event_volume),
        rvol20=f(cols["RVOL20"][i]),
        range10=f(cols["RANGE10"][i]),
        accumulation_confirmed=accumulation_confirmed,
        ma5=ma5, ma20=ma20, ma60=ma60, ma120=ma120, ma240=ma240,
        ma5_slope=f(cols["MA5_SLOPE"][i]),
        ma20_slope=f(snap_cols["MA20_SLOPE"][i]),
        above_ma120=None if ma120 is None else close > ma120,
        above_ma240=None if ma240 is None else close > ma240,
        cross_ma120=ma120_cross, cross_ma240=ma240_cross,
        prior_high=hh60,
        prior_high_distance=_ratio_minus_one(close, hh60),
        previous_high_break=hh60_break,
        trend_break=resistance_break,
        structure_score=f(structure_score), trigger_score=f(trigger_score), final_score=f(final_score),
        theme_score=f(theme_score),
        distribution_warning=bool(distribution_warning),
        market_cap=f(snap_cols["market_cap"][i]),
        free_float_shares=f(snap_cols["free_float_shares"][i]),
        close=close,
        **bo,
    )


def run_ticker(df: pd.DataFrame, ticker: str, cfg, theme_engine: scoring.ThemeEngine | None = None) -> list[ScanResult]:
    return scan_ticker(df, ticker, cfg, theme_engine).results


def run_scan(provider, tickers: list[str], cfg, theme_engine: scoring.ThemeEngine | None = None) -> dict[str, TickerScan]:
    """Runs `scan_ticker` for every ticker, isolating failures so that one bad
    ticker's exception never aborts the rest of the scan (bug #11)."""
    scans: dict[str, TickerScan] = {}
    for ticker in tickers:
        try:
            df = provider.get_ohlcv(ticker)
            if df.empty:
                logger.warning("no data for %s, skipping", ticker)
                continue
            scans[ticker] = scan_ticker(df, ticker, cfg, theme_engine)
        except Exception:
            logger.exception("scan failed for ticker %s", ticker)
            continue
    return scans
