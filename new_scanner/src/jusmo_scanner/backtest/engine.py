"""Backtest engine: signals -> forward performance. Pure per-ticker functions
(no DB, no globals) so they can later be parallelised trivially.

Flow of `backtest_ticker`: prepare_ticker -> scan_prepared(collect_snapshots=True,
NullThemeEngine) -> extract_signals -> annotate_overlap -> select_samples ->
evaluate_signals. Only `evaluate_signals` looks at bars after a signal.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Sequence

import numpy as np
import pandas as pd

from jusmo_scanner.backtest.metrics import EntryMode, ForwardResult, forward_metrics
from jusmo_scanner.backtest.signals import Signal, extract_signals, signal_row_semantics
from jusmo_scanner.config import normalize_horizons
from jusmo_scanner.scanner import engine as scan_engine
from jusmo_scanner.scanner import scoring


@dataclass
class BacktestResult:
    """Stage 1 skeleton kept for interface compatibility (see `backtest_ticker`
    for the real Stage 2 entry point)."""
    trades: list[dict] = field(default_factory=list)


class BacktestEngine:
    def run(self, state_history: list, events: list) -> BacktestResult:
        return BacktestResult(trades=[])


class SampleMode(Enum):
    FIRST_SIGNAL_PER_EPISODE = "FIRST_SIGNAL_PER_EPISODE"  # default
    ALL_SIGNALS = "ALL_SIGNALS"


@dataclass(frozen=True)
class SignalResult:
    """One row per (signal, horizon) with data. No NaN rows are ever produced."""
    signal: Signal
    horizon: int
    entry_mode: EntryMode
    forward: ForwardResult

    def to_dict(self) -> dict[str, Any]:
        s = self.signal
        row = s.snapshot.to_dict()
        row.update(
            signal_type=s.signal_type.value,
            signal_category=s.category.value,
            signal_semantics=signal_row_semantics(s),
            days_since_previous_same_signal=s.days_since_previous_same_signal,
            days_since_previous_signal=s.days_since_previous_signal,
            is_overlapping=s.is_overlapping,
            days_since_previous_same_sample=s.days_since_previous_same_sample,
            days_since_previous_sample=s.days_since_previous_sample,
            is_overlapping_sample=s.is_overlapping_sample,
            signal_types_on_bar=s.signal_types_on_bar,
            entry_mode=self.entry_mode.value,
            horizon=self.horizon,
        )
        row.update(dataclasses.asdict(self.forward))
        return row


@dataclass(frozen=True)
class TickerBacktest:
    signals: list[Signal]          # the selected (deduplicated per mode) samples, annotated
    results: list[SignalResult]


def _overlap_columns(signals: Sequence[Signal], max_horizon: int) -> list[tuple[int | None, int | None, bool]]:
    """(days_since_previous_same, days_since_previous_any, is_overlapping) per
    input signal, computed over exactly the given signals. Bars are trading
    days; "previous" means a STRICTLY earlier bar (signals sharing a bar do not
    precede each other). is_overlapping: a previous same-type signal exists
    within `max_horizon` bars."""
    order = sorted(range(len(signals)), key=lambda k: (signals[k].ticker, signals[k].bar_index, k))
    out: list[tuple[int | None, int | None, bool] | None] = [None] * len(signals)
    last_same: dict[str, dict] = {}
    prev_bars: dict[str, list[int]] = {}   # bars of earlier-processed signals, non-decreasing
    for k in order:
        sig = signals[k]
        t, b = sig.ticker, sig.bar_index
        same = last_same.setdefault(t, {})
        bars = prev_bars.setdefault(t, [])
        j = len(bars) - 1
        while j >= 0 and bars[j] >= b:
            j -= 1
        d_any = b - bars[j] if j >= 0 else None
        lb = same.get(sig.signal_type)
        d_same = b - lb if lb is not None and lb < b else None
        out[k] = (d_same, d_any, d_same is not None and d_same <= max_horizon)
        same[sig.signal_type] = b
        bars.append(b)
    return [o for o in out if o is not None]


def annotate_overlap(signals: Sequence[Signal], max_horizon: int) -> list[Signal]:
    """Adds the ALL-SIGNALS-basis overlap columns (call before any dedup; input
    order is kept): `days_since_previous_same_signal`, `days_since_previous_signal`,
    `is_overlapping`. On FIRST-mode rows these describe neighbours that may not
    be in the sample; use `annotate_sample_overlap` for the sample basis."""
    cols = _overlap_columns(signals, max_horizon)
    on_bar: dict[tuple[str, int], set] = {}
    for s in signals:
        on_bar.setdefault((s.ticker, s.bar_index), set()).add(s.signal_type)
    return [dataclasses.replace(
        s, days_since_previous_same_signal=d_same, days_since_previous_signal=d_any,
        is_overlapping=ov, signal_types_on_bar=len(on_bar[(s.ticker, s.bar_index)]))
        for s, (d_same, d_any, ov) in zip(signals, cols)]


def annotate_sample_overlap(samples: Sequence[Signal], max_horizon: int) -> list[Signal]:
    """Same definitions as `annotate_overlap` but computed over the SELECTED
    samples only: `days_since_previous_same_sample`, `days_since_previous_sample`,
    `is_overlapping_sample`. The all-signals columns are left untouched."""
    cols = _overlap_columns(samples, max_horizon)
    return [dataclasses.replace(
        s, days_since_previous_same_sample=d_same, days_since_previous_sample=d_any,
        is_overlapping_sample=ov) for s, (d_same, d_any, ov) in zip(samples, cols)]


def select_samples(signals: Sequence[Signal], mode: SampleMode = SampleMode.FIRST_SIGNAL_PER_EPISODE) -> list[Signal]:
    """ALL_SIGNALS keeps everything; FIRST_SIGNAL_PER_EPISODE keeps the first
    signal (in bar order) per (ticker, episode_id, signal_type). Output is in
    (ticker, bar) order."""
    ordered = sorted(signals, key=lambda s: (s.ticker, s.bar_index))
    if mode is SampleMode.ALL_SIGNALS:
        return ordered
    seen: set[tuple[str, str, Any]] = set()
    out: list[Signal] = []
    for s in ordered:
        key = (s.ticker, s.episode_id, s.signal_type)
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out


def evaluate_signals(
    prepared: scan_engine.PreparedTicker, signals: Sequence[Signal],
    entry_mode: EntryMode, horizons: Sequence[int],
) -> list[SignalResult]:
    """Forward metrics for each signal x horizon; (signal, horizon) pairs
    without enough forward data (or with unusable prices) are omitted."""
    cols = prepared.cols
    o, h, lo, c = (np.asarray(cols[k], dtype=float) for k in ("open", "high", "low", "close"))
    rows: list[SignalResult] = []
    for sig in signals:
        for hz in horizons:
            fr = forward_metrics(o, h, lo, c, sig.bar_index, hz, entry_mode)
            if fr is not None:
                rows.append(SignalResult(sig, hz, entry_mode, fr))
    return rows


def scan_signals(prepared: scan_engine.PreparedTicker, ticker: str, cfg, max_horizon: int) -> list[Signal]:
    """scan_prepared(collect_snapshots=True, NullThemeEngine) -> extract_signals ->
    annotate_overlap (ALL-signals basis, before any filtering/dedup). Signals are
    in bar order. Reuses `prepared`, so variants of one ticker share the features."""
    scan = scan_engine.scan_prepared(
        prepared, ticker, cfg, scoring.NullThemeEngine(), collect_snapshots=True)
    return annotate_overlap(extract_signals(scan), max_horizon)


def backtest_ticker(
    df: pd.DataFrame, ticker: str, cfg, entry_mode: EntryMode = EntryMode.NEXT_OPEN,
    horizons: Sequence[int] | None = None, mode: SampleMode = SampleMode.FIRST_SIGNAL_PER_EPISODE,
) -> TickerBacktest:
    """Full per-ticker backtest. There is deliberately NO theme_engine argument:
    the theme score has no as-of-date support yet, so historical runs always use
    NullThemeEngine (theme_score is None in every snapshot)."""
    # validate BEFORE any scanning (same rules as config: non-empty positive ints)
    hz = normalize_horizons(cfg.backtest_horizons if horizons is None else horizons)
    prepared = scan_engine.prepare_ticker(df, cfg.breakout_swing_window)
    signals = scan_signals(prepared, ticker, cfg, max(hz))
    selected = annotate_sample_overlap(select_samples(signals, mode), max(hz))
    return TickerBacktest(signals=selected, results=evaluate_signals(prepared, selected, entry_mode, hz))
