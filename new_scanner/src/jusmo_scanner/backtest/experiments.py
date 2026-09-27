"""Backtest experiments: a universe x variants x samples run with reproducible metadata.

Per ticker: load frame -> `prepare_ticker` ONCE -> for every
config variant `scan_prepared(collect_snapshots=True)` (NullThemeEngine only) ->
extract / annotate / select / evaluate (the Commit-1 functions). The per-ticker
function `run_ticker_experiment` is pure (frame + configs in, outcomes out; no DB, no
globals) so it can later be parallelised; `run_experiment` is the sequential driver.

Storage: ONE SQLite connection for the whole run; each ticker's signal and result rows
are written in one transaction (executemany). Summaries are aggregated from compact
in-memory arrays (see `analysis.SummaryAccumulator` for the memory model) and written
with executemany at the end.

Results are HISTORICAL ASSOCIATIONS: nothing here ranks variants or picks a best
parameter, and no wording anywhere may suggest otherwise.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import logging
import math
import os
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

import pandas as pd

from jusmo_scanner.backtest import parameter_grid
from jusmo_scanner.backtest.analysis import (
    SWEEP_ANALYSES, SummaryAccumulator, select_analyses)
from jusmo_scanner.backtest.engine import (
    SampleMode, SignalResult, annotate_sample_overlap, evaluate_signals, scan_signals, select_samples)
from jusmo_scanner.backtest.metrics import CLOSE_MODE_WARNING, EntryMode
from jusmo_scanner.backtest.parameter_grid import Variant
from jusmo_scanner.backtest.signals import Signal, SignalType, signal_row_semantics
from jusmo_scanner.config import ScannerConfig, normalize_horizons
from jusmo_scanner.data.base import PriceAdjustmentMode, ShareCountBasis
from jusmo_scanner.scanner import engine as scan_engine
from jusmo_scanner.storage import sqlite_store as store

logger = logging.getLogger(__name__)

SURVIVORSHIP_WARNING = "Survivorship bias may exist because historical delisted securities are not included."
UNKNOWN_ADJUSTMENT_WARNING = "price adjustment unknown: splits/mergers may distort returns"
RAW_ADJUSTMENT_WARNING = "prices are unadjusted (RAW): splits/mergers may distort returns"
OUTSTANDING_SHARES_WARNING = "turnover uses shares outstanding, not free float"
ADJUSTED_NOT_RESTATED_WARNING = "volume/trading value/share counts are not restated for corporate actions"
SYNTHETIC_WARNING = "data is synthetic; results are not market evidence"
_SUMMARY_CHUNK = 20_000


@dataclass(frozen=True)
class ExperimentOptions:
    """Experiment settings (all optional).

    signal_types: SignalType names/enums to analyse (None = all). Overlap columns are
      still computed against ALL signals before this filter; sample-basis overlap is
      computed over the filtered, selected rows.
    signal_start / signal_end: inclusive SIGNAL window. Pipeline:
        DATA WINDOW (the full provided history, incl. warm-up; NEVER cut by these options)
        -> causal scanner -> extract signals -> annotate overlap on ALL signals
        -> select samples (FIRST/ALL) on the FULL history
        -> keep signal_start <= signal_date <= signal_end
        -> forward evaluation (bars after the signal; may run beyond signal_end).
      Policy: dedup happens on the full history, so an episode whose first IGNITION was
      before signal_start does not re-qualify as "first" later; an episode that started
      before signal_start and is still active can emit signals after it (types not yet
      fired, or ALL-mode repeats). Overlap columns keep their full-history meaning.
      The scanner is causal, so bars after signal_end never influence signal generation;
      they are only used as forward data.
    sample_modes: which modes to summarise (default both, for comparison).
    entry_mode: NEXT_OPEN (default) or CLOSE (optimistic, flagged in warnings/notes).
    sweeps: run the OFAT variants (`sweep_parameters` restricts which). cartesian: full
      grid, DEFAULT OFF, refuses above `max_combos` unless `allow_exceed`.
    analyses: names from `analysis.ALL_ANALYSES` for the baseline (None = all);
      variants run `variant_analyses` (default: by_signal_type).
    store_variant_rows: also persist signal/result rows of non-baseline variants
      (default: only summaries, to keep sweeps small).
    """
    signal_types: frozenset[SignalType] | None = None
    signal_start: pd.Timestamp | None = None
    signal_end: pd.Timestamp | None = None
    sample_modes: tuple[SampleMode, ...] = (SampleMode.FIRST_SIGNAL_PER_EPISODE, SampleMode.ALL_SIGNALS)
    entry_mode: EntryMode = EntryMode.NEXT_OPEN
    horizons: tuple[int, ...] | None = None
    sweeps: bool = False
    sweep_parameters: tuple[str, ...] | None = None
    cartesian: bool = False
    cartesian_parameters: tuple[str, ...] | None = None
    max_combos: int = parameter_grid.DEFAULT_MAX_COMBOS
    allow_exceed: bool = False
    analyses: tuple[str, ...] | None = None
    variant_analyses: tuple[str, ...] = SWEEP_ANALYSES
    store_variant_rows: bool = False
    min_sample_size: int | None = None
    tickers: tuple[str, ...] | None = None
    db_path: Path | str | None = None
    experiment_id: str | None = None
    # Set by the caller when the provider history was deliberately limited (explicit
    # --fetch-start); recorded as history_truncated=1 with this reason and warned about.
    history_truncation_reason: str | None = None

    def __post_init__(self) -> None:
        def setf(name: str, value: Any) -> None:
            object.__setattr__(self, name, value)

        if self.signal_types is not None:
            setf("signal_types", frozenset(
                t if isinstance(t, SignalType) else SignalType[str(t)] for t in self.signal_types))
        for name in ("signal_start", "signal_end"):
            v = getattr(self, name)
            if v is not None:
                setf(name, pd.Timestamp(v))
        if self.signal_start is not None and self.signal_end is not None and self.signal_start > self.signal_end:
            raise ValueError(f"signal_start {self.signal_start.date()} is after signal_end {self.signal_end.date()}")
        modes = tuple(m if isinstance(m, SampleMode) else SampleMode[str(m)] for m in self.sample_modes)
        if not modes:
            raise ValueError("sample_modes must not be empty")
        setf("sample_modes", tuple(dict.fromkeys(modes)))
        setf("entry_mode", self.entry_mode if isinstance(self.entry_mode, EntryMode)
             else EntryMode[str(self.entry_mode)])
        if self.horizons is not None:
            setf("horizons", normalize_horizons(self.horizons))
        if self.min_sample_size is not None and not (
                isinstance(self.min_sample_size, int) and not isinstance(self.min_sample_size, bool)
                and self.min_sample_size > 0):
            raise ValueError(f"min_sample_size must be a positive int, got {self.min_sample_size!r}")
        if self.tickers is not None:
            setf("tickers", tuple(self.tickers))
        select_analyses(self.analyses)          # validates names
        select_analyses(self.variant_analyses)

    def to_json_dict(self) -> dict[str, Any]:
        """Reproducible description of the options (db_path excluded)."""
        return {
            "signal_types": None if self.signal_types is None else sorted(t.value for t in self.signal_types),
            "signal_start": None if self.signal_start is None else self.signal_start.date().isoformat(),
            "signal_end": None if self.signal_end is None else self.signal_end.date().isoformat(),
            "sample_modes": [m.value for m in self.sample_modes],
            "entry_mode": self.entry_mode.value,
            "horizons": None if self.horizons is None else list(self.horizons),
            "sweeps": self.sweeps,
            "sweep_parameters": None if self.sweep_parameters is None else list(self.sweep_parameters),
            "cartesian": self.cartesian,
            "cartesian_parameters": (None if self.cartesian_parameters is None
                                     else list(self.cartesian_parameters)),
            "max_combos": self.max_combos, "allow_exceed": self.allow_exceed,
            "analyses": None if self.analyses is None else list(self.analyses),
            "variant_analyses": list(self.variant_analyses),
            "store_variant_rows": self.store_variant_rows,
            "min_sample_size": self.min_sample_size,
            "tickers": None if self.tickers is None else list(self.tickers),
            "experiment_id": self.experiment_id,
            "history_truncation_reason": self.history_truncation_reason,
        }


# --- per-ticker pure function ---------------------------------------------------------

@dataclass(frozen=True)
class SampleOutcome:
    """One signal with its evaluated results. `signal` carries the all-signals overlap
    columns; the sample-basis columns are set only when `is_first`."""
    signal: Signal
    is_first: bool
    results: tuple[SignalResult, ...]


@dataclass(frozen=True)
class TickerExperiment:
    ticker: str
    data_start: pd.Timestamp | None
    data_end: pd.Timestamp | None
    outcomes: dict[str, list[SampleOutcome]]   # variant id -> outcomes in (bar, type) order


def iter_ticker_variants(
    df: pd.DataFrame, ticker: str, variants: Sequence[tuple[str, ScannerConfig]],
    options: ExperimentOptions, horizons: Sequence[int],
) -> Iterator[tuple[str, list[SampleOutcome]]]:
    """Lazily yields (variant id, outcomes) - one causal scan per variant config on the
    ONE prepared feature set of the ticker, so only one variant's objects are alive at a
    time. Every variant must use the same breakout_swing_window (not a swept parameter).
    Pure: no DB, no globals, `df` is not modified."""
    if not variants:
        raise ValueError("no variants")
    windows = {c.breakout_swing_window for _, c in variants}
    if len(windows) > 1:
        raise ValueError(
            f"all variants must share breakout_swing_window (the prepared pivot table depends on it), got {sorted(windows)}")
    max_h = max(horizons)
    prepared = scan_engine.prepare_ticker(df, variants[0][1].breakout_swing_window)
    need_all = SampleMode.ALL_SIGNALS in options.sample_modes
    lo = options.signal_start.date() if options.signal_start is not None else None
    hi = options.signal_end.date() if options.signal_end is not None else None
    for vid, vcfg in variants:
        signals = scan_signals(prepared, ticker, vcfg, max_h)
        if options.signal_types is not None:
            signals = [s for s in signals if s.signal_type in options.signal_types]
        first = annotate_sample_overlap(select_samples(signals, SampleMode.FIRST_SIGNAL_PER_EPISODE), max_h)
        first_by_key = {(s.episode_id, s.signal_type, s.bar_index): s for s in first}
        if need_all:
            merged = [(first_by_key.get((s.episode_id, s.signal_type, s.bar_index)), s) for s in signals]
            evaluated = [(f if f is not None else s, f is not None) for f, s in merged]
        else:
            evaluated = [(s, True) for s in first]
        if lo is not None or hi is not None:     # SIGNAL window, applied after full-history dedup
            evaluated = [(s, f) for s, f in evaluated
                         if (lo is None or s.signal_date >= lo) and (hi is None or s.signal_date <= hi)]
        results = evaluate_signals(prepared, [s for s, _ in evaluated], options.entry_mode, horizons)
        by_sig: dict[int, list[SignalResult]] = {}
        for r in results:
            by_sig.setdefault(id(r.signal), []).append(r)
        yield vid, [SampleOutcome(s, is_first, tuple(by_sig.get(id(s), ()))) for s, is_first in evaluated]


def run_ticker_experiment(
    df: pd.DataFrame, ticker: str, variants: Sequence[tuple[str, ScannerConfig]],
    options: ExperimentOptions, horizons: Sequence[int],
) -> TickerExperiment:
    """All variants of one ticker at once (memory ~ every variant's outcomes; the driver
    streams `iter_ticker_variants` instead)."""
    outcomes = dict(iter_ticker_variants(df, ticker, variants, options, horizons))
    dates = pd.to_datetime(df["date"])
    return TickerExperiment(
        ticker=ticker, data_start=dates.min() if len(dates) else None,
        data_end=dates.max() if len(dates) else None, outcomes=outcomes)


# --- metadata ---------------------------------------------------------------------------

def _canon(x: Any) -> Any:
    """Canonical form of a config value: integral numbers (2 and 2.0) render identically
    as ints, so the hash does not depend on how a YAML/override spelled a number; bools,
    strings, None, lists and dicts are kept as they are."""
    if isinstance(x, bool) or x is None or isinstance(x, str):
        return x
    if isinstance(x, (int, float)):
        return int(x) if float(x).is_integer() else float(x)
    if isinstance(x, dict):
        return {str(k): _canon(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_canon(v) for v in x]
    return x


def config_to_json(cfg: ScannerConfig) -> str:
    """Canonical JSON of the FULL config (nested dataclasses included), sorted keys,
    integral numbers canonicalised (see `_canon`)."""
    return json.dumps(_canon(dataclasses.asdict(cfg)), sort_keys=True, separators=(",", ":"), allow_nan=False)


def config_hash(cfg: ScannerConfig) -> str:
    return hashlib.sha256(config_to_json(cfg).encode("utf-8")).hexdigest()


def _env_commit() -> tuple[str | None, bool | None]:
    """Provenance fallback: an explicit JUSMO_GIT_COMMIT environment variable (e.g. set by
    a build/CI step when the code runs from an installed copy without a .git directory).
    Dirtiness is unknown in that case."""
    v = os.environ.get("JUSMO_GIT_COMMIT", "").strip()
    return (v or None), None


def git_info(cwd: Path | str | None = None) -> tuple[str | None, bool | None]:
    """(commit, dirty) of the repository containing the package, best effort. When git
    cannot be resolved (missing, not a repository, timeout, anything) the commit falls
    back to the JUSMO_GIT_COMMIT environment variable (dirty None), else (None, None).
    Never raises."""
    where = str(cwd) if cwd is not None else str(Path(__file__).resolve().parent)
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=where, capture_output=True,
                              text=True, timeout=10)
        if head.returncode != 0:
            return _env_commit()
        commit = head.stdout.strip() or None
        if commit is None:
            return _env_commit()
    except Exception:  # noqa: BLE001 - metadata must never break an experiment
        return _env_commit()
    try:
        st = subprocess.run(["git", "status", "--porcelain"], cwd=where, capture_output=True,
                            text=True, timeout=10)
        dirty = bool(st.stdout.strip()) if st.returncode == 0 else None
    except Exception:  # noqa: BLE001
        dirty = None
    return commit, dirty


def _insert_warning(warns: list[str], text: str) -> None:
    """Adds a warning just before the survivorship sentence (which stays last, verbatim)."""
    warns.insert(warns.index(SURVIVORSHIP_WARNING) if SURVIVORSHIP_WARNING in warns else len(warns), text)


def truncation_warning(reason: str) -> str:
    return (f"history truncated: {reason}; episode history before the fetch start is missing, so episode "
            "ids, event counts, cost/VWAP anchors and first-signal dedup may differ from a full-history run")


def universe_warnings(basis: Sequence[dict] | None) -> list[str]:
    """Warnings about the as-of universe. `basis` = the provider's per-date resolution
    [{requested, used, n_tickers}] (requested None = today's listing, no as-of date)."""
    if not basis:
        return []
    out: list[str] = []
    used: list[str] = []
    for b in basis:
        req, u = b.get("requested"), b.get("used")
        if b.get("explicit"):
            out.append(f"Universe is an explicit ticker list ({b.get('n_tickers')} tickers), not a market universe: "
                       "no listing date was used, so it is not an as-of universe")
            continue
        if req is None:
            out.append("Universe is today's listing (no as-of date): it includes securities that were not "
                       "yet listed during the window and excludes delisted ones (universe look-ahead)")
            continue
        if u is None:
            out.append(f"universe date {req} returned an empty listing on every day of the step-back range; "
                       "it contributes NOTHING, so the universe is the listing on the remaining date(s) only")
        else:
            used.append(u)
            if u != req:
                out.append(f"universe date {req} was not a trading day with listings; the listing on {u} was used")
    if len(used) == 1 and len([b for b in basis if b.get("requested")]) == 1:
        out.append(f"Universe is the listing on a single date ({used[0]}) because no start date bounded it; "
                   "securities listed after it or delisted before it may be missing or present only partially")
    elif len(used) == 1:
        out.append(f"Universe is the listing on a single date ({used[0]}); securities listed after it or "
                   "delisted before it may be missing or present only partially")
    elif used:
        out.append("Universe is the union of listings on " + ", ".join(used) +
                   "; securities listed after the first date or delisted before the last date may be "
                   "missing or present only partially")
    return out


def build_warnings(adjustment: PriceAdjustmentMode, share_basis: ShareCountBasis,
                   entry_mode: EntryMode, synthetic: bool = False,
                   universe_basis: Sequence[dict] | None = None,
                   history_truncation_reason: str | None = None) -> list[str]:
    out: list[str] = []
    if synthetic:
        out.append(SYNTHETIC_WARNING)
    if adjustment is PriceAdjustmentMode.UNKNOWN:
        out.append(UNKNOWN_ADJUSTMENT_WARNING)
    elif adjustment is PriceAdjustmentMode.RAW:
        out.append(RAW_ADJUSTMENT_WARNING)
    elif adjustment is PriceAdjustmentMode.ADJUSTED:
        out.append(ADJUSTED_NOT_RESTATED_WARNING)
    if share_basis is ShareCountBasis.OUTSTANDING:
        out.append(OUTSTANDING_SHARES_WARNING)
    if entry_mode is EntryMode.CLOSE:
        out.append(CLOSE_MODE_WARNING)
    if history_truncation_reason:
        out.append(truncation_warning(history_truncation_reason))
    out.extend(universe_warnings(universe_basis))
    out.append(SURVIVORSHIP_WARNING)
    return out


# --- driver -----------------------------------------------------------------------------------

@dataclass
class ExperimentResult:
    experiment_id: str
    metadata: dict[str, Any]
    summary_rows: list[dict[str, Any]]
    variants: list[str]
    tickers_scanned: int
    failed_tickers: dict[str, str]
    warnings: list[str]
    signal_counts: dict[str, int] = field(default_factory=dict)  # variant -> ALL signals evaluated


def _ensure_finite(rows: Sequence[dict[str, Any]]) -> None:
    for r in rows:
        for k, v in r.items():
            if isinstance(v, float) and not math.isfinite(v):
                raise ValueError(f"non-finite value in summary row field {k!r}: {v!r}")


def _signal_rows(experiment_id: str, variant: str, outcomes: Sequence[SampleOutcome],
                 share_basis: str | None = None) -> tuple[list[dict], list[dict]]:
    sig_rows: list[dict[str, Any]] = []
    res_rows: list[dict[str, Any]] = []
    for o in outcomes:
        s = o.signal
        uid = f"{s.episode_id}|{s.signal_type.value}|{s.bar_index}"
        row = s.snapshot.to_dict()
        row.update(
            experiment_id=experiment_id, variant=variant, signal_uid=uid,
            signal_type=s.signal_type.value, signal_category=s.category.value,
            signal_semantics=signal_row_semantics(s), is_first_sample=o.is_first,
            signal_types_on_bar=s.signal_types_on_bar, share_count_basis=share_basis,
            days_since_previous_same_signal=s.days_since_previous_same_signal,
            days_since_previous_signal=s.days_since_previous_signal,
            is_overlapping=s.is_overlapping)
        if o.is_first:
            row.update(days_since_previous_same_sample=s.days_since_previous_same_sample,
                       days_since_previous_sample=s.days_since_previous_sample,
                       is_overlapping_sample=s.is_overlapping_sample)
        sig_rows.append(row)
        for r in o.results:
            f = dataclasses.asdict(r.forward)
            f.update(experiment_id=experiment_id, variant=variant, signal_uid=uid,
                     entry_mode=r.entry_mode.value, horizon=r.horizon,
                     signal_type=s.signal_type.value, signal_semantics=signal_row_semantics(s))
            res_rows.append(f)
    return sig_rows, res_rows


def _build_variants(cfg: ScannerConfig, options: ExperimentOptions) -> list[tuple[Variant, ScannerConfig]]:
    variants: list[Variant] = [parameter_grid.baseline_variant()]
    if options.sweeps:
        variants = parameter_grid.ofat_variants(options.sweep_parameters)
    if options.cartesian:
        variants.extend(parameter_grid.cartesian_variants(
            options.cartesian_parameters, max_combos=options.max_combos, allow_exceed=options.allow_exceed))
    seen: set[str] = set()
    out = []
    for v in variants:
        if v.id in seen:
            continue
        seen.add(v.id)
        out.append((v, parameter_grid.apply_variant(cfg, v)))   # base cfg is never mutated
    return out


HISTORY_START_NEAR_DAYS = 7


def _post_run_checks(provider, cfg: ScannerConfig, options: ExperimentOptions,
                     first_dates: dict[str, pd.Timestamp], meta: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Warnings and metadata that need the finished ticker loop: history truncation (explicit
    fetch start or tickers starting at the fetch start), short rolling warm-up before
    signal_start, provider data-quality counters."""
    warns: list[str] = []
    fields: dict[str, Any] = {}
    reason = options.history_truncation_reason
    fs = getattr(provider, "fetch_start", None)
    if fs is not None:
        near = sorted(t for t, d in first_dates.items() if (d.date() - fs).days <= HISTORY_START_NEAR_DAYS)
        if near and reason:
            reason += f"; {len(near)} ticker(s) start within {HISTORY_START_NEAR_DAYS} days of the fetch start (possibly truncated)"
        elif near:
            reason = (f"{len(near)} ticker(s) start within {HISTORY_START_NEAR_DAYS} days of the fetch start "
                      f"{fs.isoformat()} (possibly truncated)")
    report = provider.data_quality_report() if hasattr(provider, "data_quality_report") else {}
    n_capped = int(report.get("history_row_capped_tickers", 0) or 0)
    if n_capped:
        cap_text = (f"{n_capped} ticker(s) hit the source's cap of {report.get('history_row_cap')} daily rows "
                    f"(history starts no earlier than {report.get('history_row_capped_first_date')}, "
                    "counted back from the run date)")
        reason = f"{reason}; {cap_text}" if reason else cap_text
    if reason:
        # the initial warning (explicit reason) is already in the list; add the near-start detail
        if reason != options.history_truncation_reason:
            warns.append(truncation_warning(reason))
        fields.update(history_truncated=True, history_truncation_reason=reason)
    else:
        fields.update(history_truncated=False, history_truncation_reason=None)
    if options.signal_start is not None and first_dates:
        limit = options.signal_start.date() - timedelta(days=cfg.backtest_rolling_warmup_calendar_days)
        short = sorted(t for t, d in first_dates.items() if d.date() > limit)
        if short:
            warns.append(
                f"{len(short)} ticker(s) have less than {cfg.backtest_rolling_warmup_calendar_days} calendar days of "
                f"history before signal_start {options.signal_start.date().isoformat()}; rolling indicators "
                "(MA240, HH60, ...) may be unavailable early in the window")
    if report:
        k, n = int(report.get("tickers_with_missing_market_data", 0)), int(report.get("missing_market_data_rows", 0))
        fields.update(tickers_with_missing_market_data=k, missing_market_data_rows=n)
        if k:
            warns.append(f"market data gaps: {k} ticker(s) have {n} row(s) without market cap / share count "
                         "(turnover and capital impact are missing on those bars)")
        k_tv, n_tv = int(report.get("tickers_without_trading_value", 0)), int(report.get("rows_without_trading_value", 0))
        if k_tv:
            warns.append(f"trading value missing: {k_tv} ticker(s) have {n_tv} row(s) without a source trading value; "
                         "close * volume is used instead (an adjusted close times an unadjusted volume: "
                         "understated before splits)")
        dropped = int(report.get("halted_rows_dropped", 0) or 0)
        if dropped:
            warns.append(f"{dropped} halted / no-trade bar(s) (volume 0, open = high = low = 0) were dropped")
    return warns, fields


def _iso(d: Any) -> str | None:
    return None if d is None else pd.Timestamp(d).date().isoformat()


def run_experiment(provider, cfg: ScannerConfig, options: ExperimentOptions | None = None) -> ExperimentResult:
    """Runs one experiment over `provider`'s universe. Per-ticker exceptions are logged
    and counted (`failed_tickers`); the experiment itself fails (RuntimeError, after
    recording status FAILED when a DB is used) only if no ticker succeeded.
    With options.db_path the run is persisted (current schema, see sqlite_store.SCHEMA_VERSION) through ONE connection."""
    options = options or ExperimentOptions()
    horizons = normalize_horizons(options.horizons if options.horizons is not None else cfg.backtest_horizons)
    min_size = options.min_sample_size if options.min_sample_size is not None else cfg.backtest_min_sample_size
    variants = _build_variants(cfg, options)
    variant_ids = [v.id for v, _ in variants]
    baseline_id = parameter_grid.BASELINE_ID
    # A variant whose config equals the baseline is not re-scanned: it reuses the baseline
    # outcomes and is flagged `variant_equals_baseline` (same numbers, visibly the same config).
    equal_ids = {v.id for v, c in variants if v.id != baseline_id and c == cfg}
    scan_variants = [(v.id, c) for v, c in variants if v.id not in equal_ids]
    base_names = [a.name for a in select_analyses(options.analyses)]
    var_names = [a.name for a in select_analyses(options.variant_analyses)]
    acc = SummaryAccumulator(
        select_analyses(list(dict.fromkeys(base_names + var_names))), options.entry_mode, options.sample_modes)

    tickers = list(options.tickers) if options.tickers is not None else list(provider.get_tickers())
    if not tickers:
        raise ValueError("empty universe: no tickers to backtest")
    adjustment = getattr(provider, "price_adjustment_mode", PriceAdjustmentMode.UNKNOWN)
    share_basis = getattr(provider, "share_count_basis", ShareCountBasis.UNKNOWN)
    universe_basis = getattr(provider, "universe_basis", None)   # read AFTER get_tickers (resolution recorded there)
    warns = build_warnings(adjustment, share_basis, options.entry_mode,
                           bool(getattr(provider, "is_synthetic", False)), universe_basis,
                           options.history_truncation_reason)
    commit, dirty = git_info()
    experiment_id = options.experiment_id or uuid.uuid4().hex
    meta: dict[str, Any] = {
        "experiment_id": experiment_id,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "RUNNING",
        "config_hash": config_hash(cfg), "config_json": config_to_json(cfg),
        "options_json": json.dumps(options.to_json_dict(), sort_keys=True),
        "source_data_start": None, "source_data_end": None,
        "signal_start": _iso(options.signal_start), "signal_end": _iso(options.signal_end),
        "universe_size": len(tickers),
        "tickers_scanned": 0, "tickers_failed": 0, "failed_tickers_json": "{}",
        "sample_modes": ",".join(m.value for m in options.sample_modes),
        "entry_mode": options.entry_mode.value,
        "price_adjustment_mode": adjustment.value, "share_count_basis": share_basis.value,
        "warnings_json": json.dumps(warns), "git_commit": commit, "git_dirty": dirty,
        "horizons": json.dumps(list(horizons)),
        "variants_json": json.dumps([{"id": v, "equals_baseline": v in equal_ids} for v in variant_ids]), "min_sample_size": min_size,
        "schema_version": store.SCHEMA_VERSION,
        "history_truncated": bool(options.history_truncation_reason),
        "history_truncation_reason": options.history_truncation_reason,
        "universe_basis": json.dumps(list(universe_basis)) if universe_basis else None,
        "tickers_with_missing_market_data": None, "missing_market_data_rows": None,
    }

    failed: dict[str, str] = {}
    first_dates: dict[str, pd.Timestamp] = {}
    scanned = 0
    data_start: pd.Timestamp | None = None
    data_end: pd.Timestamp | None = None
    counts = {vid: 0 for vid in variant_ids}
    summary_rows: list[dict[str, Any]] = []
    error: str | None = None

    with contextlib.ExitStack() as stack:
        conn = None
        if options.db_path is not None:
            store.init_db(options.db_path)
            conn = stack.enter_context(store.connection(options.db_path))
            store.delete_backtest_experiment(conn, experiment_id)   # idempotent re-run of the same id
            store.insert_backtest_experiment(conn, meta)
            conn.commit()

        for ticker in tickers:
            # Ticker-local accumulation: nothing reaches the experiment totals (or the
            # DB, which rolls back) unless every variant of the ticker succeeded.
            local = acc.empty_like()
            t_counts = {vid: 0 for vid in variant_ids}
            try:
                df = provider.get_ohlcv(ticker)
                if df is None or df.empty:
                    raise ValueError("no data")
                dates = pd.to_datetime(df["date"])
                for vid, outs in iter_ticker_variants(df, ticker, scan_variants, options, horizons):
                    t_counts[vid] = len(outs)
                    names = base_names if vid == baseline_id else var_names
                    for o in outs:
                        local.add(vid, o.signal, o.is_first, o.results, names)
                    if vid == baseline_id:
                        for eq in sorted(equal_ids):
                            t_counts[eq] = len(outs)
                            for o in outs:
                                local.add(eq, o.signal, o.is_first, o.results, var_names)
                    if conn is not None and (vid == baseline_id or options.store_variant_rows):
                        sig_rows, res_rows = _signal_rows(experiment_id, vid, outs, share_basis.value)
                        store.insert_backtest_signals_many(conn, sig_rows)
                        store.insert_backtest_results_many(conn, res_rows)
            except Exception as exc:  # noqa: BLE001 - one bad ticker must not kill the experiment
                logger.exception("experiment failed for ticker %s", ticker)
                failed[ticker] = f"{type(exc).__name__}: {exc}"
                if conn is not None:
                    conn.rollback()
                continue
            if conn is not None:
                conn.commit()    # one transaction per ticker
            acc.merge(local)
            scanned += 1
            first_dates[ticker] = dates.min()
            for vid, n in t_counts.items():
                counts[vid] += n
            data_start = dates.min() if data_start is None else min(data_start, dates.min())
            data_end = dates.max() if data_end is None else max(data_end, dates.max())

        meta.update(tickers_scanned=scanned, tickers_failed=len(failed),
                    failed_tickers_json=json.dumps(failed, sort_keys=True),
                    source_data_start=_iso(data_start), source_data_end=_iso(data_end))
        extra_warnings, extra_fields = _post_run_checks(provider, cfg, options, first_dates, meta)
        for w in extra_warnings:
            if w.startswith("history truncated:") and options.history_truncation_reason:
                old = truncation_warning(options.history_truncation_reason)
                if old in warns:
                    warns.remove(old)             # replaced by the more detailed line
            _insert_warning(warns, w)
        meta.update(extra_fields, warnings_json=json.dumps(warns))
        if scanned == 0:
            meta["status"] = "FAILED"
            error = f"no ticker could be backtested ({len(failed)} failed): " + "; ".join(
                f"{t}: {m}" for t, m in list(failed.items())[:5])
        else:
            summary_rows = acc.finalize(cfg.backtest_sample_quality, min_size)
            for r in summary_rows:
                same = r["variant"] in equal_ids
                r["variant_equals_baseline"] = same
                if same:
                    r["note"] = (r["note"] + "; " if r["note"] else "") + "same config as baseline"
                if "turnover" in (r["dim1_name"], r["dim2_name"]) or r["variant"].startswith("turnover="):
                    # turnover = volume / share count; state which share count it is
                    r["note"] = (r["note"] + "; " if r["note"] else "") + f"share_count_basis={share_basis.value}"
            _ensure_finite(summary_rows)
            meta["status"] = "COMPLETE"
            if conn is not None:
                for i in range(0, len(summary_rows), _SUMMARY_CHUNK):
                    store.insert_backtest_summary_many(
                        conn, [{**r, "experiment_id": experiment_id}
                               for r in summary_rows[i:i + _SUMMARY_CHUNK]])
        if conn is not None:
            store.update_backtest_experiment(
                conn, experiment_id, **{k: v for k, v in meta.items() if k != "experiment_id"})

    if error is not None:
        raise RuntimeError(error)
    return ExperimentResult(
        experiment_id=experiment_id, metadata=meta, summary_rows=summary_rows, variants=variant_ids,
        tickers_scanned=scanned, failed_tickers=failed, warnings=warns, signal_counts=counts)
