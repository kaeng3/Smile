"""`backtest`, `backtest-report` and `sample-data` CLI commands (wired in jusmo_scanner.cli).

Expected problems (bad arguments, empty universe, unknown experiment id) are reported with
a one-line log message and exit code 1, never a traceback.
"""
from __future__ import annotations

import argparse
import logging
import dataclasses
import math
from datetime import date, timedelta
from pathlib import Path

from jusmo_scanner.backtest import parameter_grid, reporter, sampledata
from jusmo_scanner.backtest.engine import SampleMode
from jusmo_scanner.backtest.experiments import ExperimentOptions, run_experiment
from jusmo_scanner.backtest.metrics import EntryMode
from jusmo_scanner.backtest.signals import SignalType
from jusmo_scanner.config import load_config, normalize_horizons
from jusmo_scanner.data.base import DataProvider, PriceAdjustmentMode, ShareCountBasis

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = "output/backtest"
# ESTIMATE fitted to measurements on synthetic 1250-bar tickers (Windows, py3.13, 31 tickers):
# baseline 22.8 s (0.73 s per ticker); 43-variant OFAT 154.9 s at the default 6 horizons and 80.2 s
# with 2 horizons. Time per ticker = T_BASE + (variants - 1) * (T_VARIANT_BASE + T_VARIANT_PER_HORIZON * horizons).
# Peak accumulator memory (default horizons): ~0.67 MB per ticker for the baseline, ~5.4 MB per ticker
# with the 43-variant sweep (linear in the number of variants).
SECONDS_PER_TICKER_BASELINE = 0.73
SECONDS_PER_VARIANT_BASE = 0.0155
SECONDS_PER_VARIANT_PER_HORIZON = 0.01435
MB_PER_TICKER_BASELINE = 0.67
MB_PER_EXTRA_VARIANT_PER_TICKER = (5.4 - 0.67) / 42
DEFAULT_MAX_SWEEP_MEMORY_GB = 8.0


def estimate_run(n_tickers: int, n_variants: int, n_horizons: int = 6) -> tuple[float, float]:
    """(seconds, peak memory in MB) ESTIMATE: linear extrapolation of the measurements above.
    Time depends on the number of tickers, variants and horizons; memory (default horizons) on
    tickers and variants. Only fewer tickers and fewer variants (--sweep-params) lower the
    memory estimate. 2,500 tickers x 43 variants ~ 13.5 GB and ~ 3.5 h at 6 horizons."""
    per_variant = SECONDS_PER_VARIANT_BASE + SECONDS_PER_VARIANT_PER_HORIZON * n_horizons
    seconds = n_tickers * (SECONDS_PER_TICKER_BASELINE + max(n_variants - 1, 0) * per_variant)
    mem_mb = n_tickers * (MB_PER_TICKER_BASELINE + MB_PER_EXTRA_VARIANT_PER_TICKER * max(n_variants - 1, 0))
    return seconds, mem_mb
COMMANDS = ("backtest", "backtest-report", "sample-data")


class CliError(Exception):
    """An expected, user-facing error (exit code 1)."""


def add_parsers(sub) -> None:
    p = sub.add_parser("backtest", help="Run a historical backtest experiment and write reports")
    p.add_argument("--provider", choices=["csv", "pykrx", "kis"], default="csv")
    p.add_argument("--csv-dir", default="data")
    p.add_argument("--config", default="config/scanner.yaml")
    p.add_argument("--signal", action="append", default=None, metavar="NAME",
                   help="SignalType name (repeatable or comma separated); default: all")
    p.add_argument("--start", default=None, metavar="YYYY-MM-DD",
                   help="first SIGNAL date (inclusive). NOT a data cut: the scanner still sees the whole "
                        "provided history; only signals dated >= --start are analysed")
    p.add_argument("--end", default=None, metavar="YYYY-MM-DD",
                   help="last SIGNAL date (inclusive); forward returns may use bars after it")
    p.add_argument("--fetch-start", default=None, metavar="YYYY-MM-DD",
                   help="pykrx/kis fetch start. Default: full history (pykrx 1990-01-01; KIS 1980-01-01), because "
                        "episodes have no expiry. Setting it LIMITS history and is recorded as "
                        "history_truncated with a warning (episode ids/counts/cost anchors may change). "
                        "A full-history fetch is slower (more network per ticker) - that is the price of "
                        "correct episode history")
    p.add_argument("--tickers", default=None, metavar="005930,000660",
                   help="pykrx/kis only: scan exactly these tickers and skip the universe listing (recorded as "
                        "an explicit ticker list in universe_basis, not an as-of universe)")
    p.add_argument("--cache-dir", default="data/cache", help="kis provider: raw daily-bar cache directory")
    p.add_argument("--refresh", action="store_true", help="kis provider: ignore the cache and refetch every ticker")
    p.add_argument("--fetch-end", default=None, metavar="YYYY-MM-DD",
                   help="pykrx/kis fetch end. Default: --end plus the forward buffer (capped at today), else today")
    p.add_argument("--mode", choices=["first-per-episode", "all-signals", "both"], default="both",
                   help="sample mode(s); default both (FIRST_SIGNAL_PER_EPISODE is the primary one in reports)")
    p.add_argument("--entry-mode", choices=["next-open", "close"], default="next-open",
                   help="close = research/optimistic assumption")
    p.add_argument("--horizons", default=None, metavar="1,3,5,...", help="forward horizons in trading days")
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    p.add_argument("--db-path", default=None, help="default: <output>/backtest.db")
    p.add_argument("--sweep", choices=["none", "ofat"], default="none",
                   help="ofat = one-factor-at-a-time sweep (43 configs per ticker; heavy)")
    p.add_argument("--sweep-params", default=None, metavar="a,b",
                   help="restrict the OFAT sweep to these parameters (e.g. vcr,range10)")
    p.add_argument("--allow-large-sweep", action="store_true",
                   help="run even if the estimated peak memory exceeds --max-sweep-memory-gb")
    p.add_argument("--max-sweep-memory-gb", type=float, default=DEFAULT_MAX_SWEEP_MEMORY_GB,
                   help="refuse runs whose estimated peak memory is above this (default 8)")
    p.add_argument("--full-grid", action="store_true", help="full Cartesian grid (default OFF; needs --max-combos)")
    p.add_argument("--max-combos", type=int, default=None)
    p.add_argument("--grid-params", default=None, metavar="a,b", help="restrict the full grid to these sweep parameters")
    p.add_argument("--min-sample-size", type=int, default=None)
    p.add_argument("--price-adjustment-mode", type=str.upper, choices=[m.value for m in PriceAdjustmentMode], default=None)
    p.add_argument("--share-count-basis", type=str.upper, choices=[m.value for m in ShareCountBasis], default=None)

    r = sub.add_parser("backtest-report", help="Regenerate CSVs and the summary of a stored experiment")
    r.add_argument("experiment_id")
    r.add_argument("--output", default=DEFAULT_OUTPUT)
    r.add_argument("--db-path", default=None, help="default: <output>/backtest.db")

    s = sub.add_parser("sample-data", help="Generate a deterministic SYNTHETIC CSV universe")
    s.add_argument("--output", required=True)
    s.add_argument("--tickers", type=int, default=30)
    s.add_argument("--bars", type=int, default=1250)
    s.add_argument("--seed", type=int, default=0)


# --- argument helpers ---------------------------------------------------------------------------------

def parse_signals(values: list[str] | None) -> frozenset[SignalType] | None:
    if not values:
        return None
    out = set()
    for v in values:
        for name in v.split(","):
            name = name.strip().upper()
            if not name:
                continue
            try:
                out.add(SignalType[name])
            except KeyError:
                raise CliError(f"unknown signal {name!r}; valid: {', '.join(t.name for t in SignalType)}") from None
    return frozenset(out) or None


def parse_date(value: str | None, flag: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise CliError(f"{flag} must be YYYY-MM-DD, got {value!r}") from None


def parse_horizons(value: str | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    try:
        return normalize_horizons([int(x) for x in value.split(",") if x.strip()])
    except ValueError as exc:
        raise CliError(f"--horizons must be comma separated positive integers: {exc}") from None


class _MetaOverride(DataProvider):
    """Delegating provider that overrides the metadata reported by the wrapped one."""

    def __init__(self, inner: DataProvider, adjustment: PriceAdjustmentMode | None,
                 basis: ShareCountBasis | None) -> None:
        self._inner, self._adj, self._basis = inner, adjustment, basis

    @property
    def price_adjustment_mode(self) -> PriceAdjustmentMode:
        return self._adj or self._inner.price_adjustment_mode

    @property
    def share_count_basis(self) -> ShareCountBasis:
        return self._basis or self._inner.share_count_basis

    @property
    def is_synthetic(self) -> bool:
        return self._inner.is_synthetic

    @property
    def universe_basis(self):
        return self._inner.universe_basis

    @property
    def fetch_start(self):
        return self._inner.fetch_start

    def data_quality_report(self) -> dict:
        return self._inner.data_quality_report()

    def get_tickers(self) -> list[str]:
        return self._inner.get_tickers()

    def get_ohlcv(self, ticker: str):
        return self._inner.get_ohlcv(ticker)


EARLIEST_FETCH_DATE = date(1990, 1, 1)   # default fetch start: the provider's FULL history (see pykrx_provider)


def resolve_fetch_window(signal_start: date | None, signal_end: date | None, max_horizon: int,
                         explicit_start: date | None = None, explicit_end: date | None = None,
                         today: date | None = None, provider: str = "pykrx") -> tuple[date, date, str | None]:
    """Provider FETCH window (separate from the signal window) -> (start, end, truncation_reason).

    start: `explicit_start`, else provider earliest date (pykrx 1990-01-01, KIS 1980-01-01). NO fixed lookback: the scanner has no episode expiry, so an episode anchored
      years before signal_start can be alive at signal_start and truncating the history would
      change its id, event count, cost/VWAP anchor and dedup.
    end: `explicit_end` (capped at today), else signal_end + forward buffer (ceil(max_horizon * 1.6) + 10
      calendar days: trading days -> calendar days plus a holiday margin) capped at today; with
      no signal_end: today.
    truncation_reason: "explicit --fetch-start=<date>" when the user limited the history,
      else None (full history). Both bounds are always concrete dates (never None), and
    impossible ranges raise CliError BEFORE any network call."""
    today = today or date.today()
    earliest = EARLIEST_FETCH_DATE
    if provider == "kis":
        from jusmo_scanner.data.kis_provider import EARLIEST_FETCH_DATE as earliest
    start = explicit_start or earliest
    if explicit_end is not None:
        end = min(explicit_end, today)
    elif signal_end is not None:
        end = min(signal_end + timedelta(days=math.ceil(max_horizon * 1.6) + 10), today)
    else:
        end = today
    if start > end:
        raise CliError(f"fetch range is empty: start {start} is after end {end}")
    if explicit_start is not None and signal_start is not None and explicit_start > signal_start:
        raise CliError(f"--fetch-start {explicit_start} is after --start {signal_start}: "
                       "the signal window would have no data")
    if explicit_end is not None and signal_end is not None and end < signal_end:
        raise CliError(f"--fetch-end {explicit_end} is before --end {signal_end}")
    reason = f"explicit --fetch-start={explicit_start.isoformat()}" if explicit_start is not None else None
    return start, end, reason


def universe_dates_for(signal_start: date | None, signal_end: date | None, fetch_start: date,
                       today: date | None = None) -> list[str]:
    """As-of universe dates (YYYYMMDD), capped at today: signal_start and signal_end (today when
    there is none). The provider snaps each to a trading day and unions the listings - an
    approximation: securities listed AND delisted strictly inside the window are still missing.
    RULE: when there is no signal_start (the 1990 fetch start is a placeholder, not a listing
    date) ONLY the signal_end listing is used, and the run warns that the universe is the
    listing on that single date."""
    today = today or date.today()
    last = min(signal_end or today, today)
    if signal_start is None:
        return [last.strftime("%Y%m%d")]
    first = min(signal_start, today)
    return sorted({first.strftime("%Y%m%d"), last.strftime("%Y%m%d")})


def _build_provider(args, fetch_start: date | None, fetch_end: date | None,
                    universe_dates: list[str] | None = None, tickers: list[str] | None = None) -> DataProvider:
    adj = PriceAdjustmentMode[args.price_adjustment_mode] if args.price_adjustment_mode else None
    basis = ShareCountBasis[args.share_count_basis] if args.share_count_basis else None
    if args.provider == "csv":
        return _csv(args.csv_dir, adj, basis)
    if args.provider == "kis":
        if adj not in (None, PriceAdjustmentMode.ADJUSTED, PriceAdjustmentMode.RAW):
            raise CliError("KIS price adjustment must be ADJUSTED or RAW")
        if basis not in (None, ShareCountBasis.OUTSTANDING):
            raise CliError("KIS share-count-basis is OUTSTANDING; historical counts are unavailable")
        try:
            from jusmo_scanner.data.kis_provider import KisProvider
            inner = KisProvider(fetch_start.strftime("%Y%m%d") if fetch_start else None,
                                fetch_end.strftime("%Y%m%d") if fetch_end else None,
                                tickers=tickers, cache_dir=args.cache_dir, refresh=args.refresh,
                                adjusted=adj is not PriceAdjustmentMode.RAW)
        except (ImportError, ValueError) as exc:
            raise CliError(str(exc)) from None
        return inner
    try:
        from jusmo_scanner.data.pykrx_provider import PykrxProvider
        inner = PykrxProvider(fetch_start.strftime("%Y%m%d") if fetch_start else None,
                              fetch_end.strftime("%Y%m%d") if fetch_end else None,
                              universe_dates=universe_dates, tickers=tickers)
    except ImportError as exc:
        raise CliError(str(exc)) from None
    return _MetaOverride(inner, adj, basis)


def _csv(csv_dir, adj=None, basis=None) -> DataProvider:
    from jusmo_scanner.data.csv_provider import CSVProvider
    try:
        return CSVProvider(csv_dir, price_adjustment_mode=adj, share_count_basis=basis)
    except ValueError as exc:
        raise CliError(str(exc)) from None


# --- commands ---------------------------------------------------------------------------------------------------

def _cmd_backtest(args: argparse.Namespace) -> int:
    start, end = parse_date(args.start, "--start"), parse_date(args.end, "--end")
    fetch_start, fetch_end = parse_date(args.fetch_start, "--fetch-start"), parse_date(args.fetch_end, "--fetch-end")
    signals = parse_signals(args.signal)
    horizons = parse_horizons(args.horizons)
    modes = {"first-per-episode": (SampleMode.FIRST_SIGNAL_PER_EPISODE,),
             "all-signals": (SampleMode.ALL_SIGNALS,),
             "both": (SampleMode.FIRST_SIGNAL_PER_EPISODE, SampleMode.ALL_SIGNALS)}[args.mode]
    output = Path(args.output)
    db_path = Path(args.db_path) if args.db_path else output / "backtest.db"
    if args.full_grid:
        if args.max_combos is None:
            raise CliError("--full-grid needs --max-combos N (the grid grows multiplicatively)")
        params = [p.strip() for p in args.grid_params.split(",")] if args.grid_params else None
        try:
            total = parameter_grid.cartesian_combo_count(params)
        except KeyError as exc:
            raise CliError(f"unknown sweep parameter {exc}") from None
        logger.info("full grid: %d combinations (max %d)", total, args.max_combos)
        if total > args.max_combos:
            raise CliError(f"full grid has {total} combinations, above --max-combos {args.max_combos}; "
                           "raise the limit or restrict --grid-params")
    try:
        cfg = load_config(args.config)
        options = ExperimentOptions(
            signal_types=signals, signal_start=start, signal_end=end, sample_modes=modes,
            entry_mode=EntryMode.CLOSE if args.entry_mode == "close" else EntryMode.NEXT_OPEN,
            horizons=horizons, sweeps=args.sweep == "ofat",
            sweep_parameters=(tuple(x.strip() for x in args.sweep_params.split(",")) if args.sweep_params else None),
            cartesian=args.full_grid, cartesian_parameters=(tuple(params) if args.full_grid and params else None),
            max_combos=args.max_combos or parameter_grid.DEFAULT_MAX_COMBOS,
            min_sample_size=args.min_sample_size, db_path=db_path)
    except (ValueError, OSError, KeyError) as exc:
        raise CliError(str(exc)) from None
    if args.provider == "csv" and (args.fetch_start or args.fetch_end):
        logger.warning("--fetch-start/--fetch-end apply to pykrx/kis providers only; CSV history is used in full "
                       "(CSV data is never truncated by this tool; a hand-trimmed CSV cannot be detected)")
    if args.provider in ("pykrx", "kis"):
        fetch_start, fetch_end, reason = resolve_fetch_window(        # validated BEFORE any network call
            start, end, max(options.horizons or cfg.backtest_horizons), fetch_start, fetch_end,
            provider=args.provider)
        logger.info("%s fetch window: %s .. %s (signal window %s .. %s)", args.provider, fetch_start, fetch_end, start, end)
        if reason:
            logger.warning("history truncated: %s (episode history before %s is not fetched)", reason, fetch_start)
            options = dataclasses.replace(options, history_truncation_reason=reason)
    explicit = [t.strip() for t in args.tickers.split(",") if t.strip()] if args.tickers else None
    if args.tickers is not None and (args.provider not in ("pykrx", "kis") or not explicit):
        raise CliError("--tickers needs --provider pykrx or kis and at least one ticker")
    universe_dates = universe_dates_for(start, end, fetch_start) if args.provider == "pykrx" and not explicit else None
    provider = _build_provider(args, fetch_start, fetch_end, universe_dates, explicit)
    try:
        tickers = tuple(provider.get_tickers())      # ONE call, shared by the sweep guard and run_experiment
    except (ValueError, RuntimeError, OSError) as exc:
        raise CliError(str(exc)) from None
    options = dataclasses.replace(options, tickers=tickers)
    if options.sweeps or options.cartesian or args.max_sweep_memory_gb != DEFAULT_MAX_SWEEP_MEMORY_GB:
        n_tickers = len(options.tickers or ())
        try:
            n_variants = (parameter_grid.cartesian_combo_count(options.cartesian_parameters) if options.cartesian
                          else len(parameter_grid.ofat_variants(options.sweep_parameters)) if options.sweeps else 1)
        except (KeyError, ValueError) as exc:
            raise CliError(str(exc)) from None
        seconds, mem_mb = estimate_run(n_tickers, n_variants, len(options.horizons or cfg.backtest_horizons))
        gb = mem_mb / 1000
        if n_variants > 1:
            logger.warning(
                "sweep is heavy: %d variants x %d tickers, ESTIMATED ~ %.0f s at ~1250 bars per ticker and "
                "estimated peak memory ~ %.2f GB (~%.1f MB per ticker)", n_variants, n_tickers, seconds,
                gb, mem_mb / max(n_tickers, 1))
        if gb > args.max_sweep_memory_gb and not args.allow_large_sweep:
            raise CliError(
                f"estimated peak memory {gb:.1f} GB ({n_tickers} tickers x {n_variants} variants) exceeds the "
                f"{args.max_sweep_memory_gb:g} GB limit (an estimate); reduce it with fewer tickers "
                "(smaller universe / CSV dir) or fewer variants (--sweep-params a,b), or pass "
                "--allow-large-sweep to run anyway")
    output.mkdir(parents=True, exist_ok=True)
    try:
        result = run_experiment(provider, cfg, options)
    except (ValueError, RuntimeError) as exc:
        raise CliError(str(exc)) from None
    for w in result.warnings:
        logger.warning("%s", w)
    if result.failed_tickers:
        logger.warning("%d ticker(s) failed: %s", len(result.failed_tickers), ", ".join(sorted(result.failed_tickers)))
    files = reporter.export_experiment(db_path, result.experiment_id, output)
    logger.info("experiment %s: %d tickers scanned, %d summary rows", result.experiment_id,
                result.tickers_scanned, len(result.summary_rows))
    for line in files.console_lines:
        logger.info("%s", line)
    for p in files.paths:
        logger.info("wrote %s", p)
    return 0


def _cmd_backtest_report(args: argparse.Namespace) -> int:
    db_path = Path(args.db_path) if args.db_path else Path(args.output) / "backtest.db"
    try:
        files = reporter.export_experiment(db_path, args.experiment_id, args.output)
    except reporter.UnknownExperiment as exc:
        raise CliError(str(exc)) from None
    for p in files.paths:
        logger.info("wrote %s", p)
    return 0


def _cmd_sample_data(args: argparse.Namespace) -> int:
    try:
        paths = sampledata.write_csv_universe(args.output, args.tickers, args.bars, args.seed)
    except ValueError as exc:
        raise CliError(str(exc)) from None
    logger.warning("SYNTHETIC data written to %s (%d tickers): not market data", args.output, len(paths))
    return 0


def dispatch(args: argparse.Namespace) -> int:
    handler = {"backtest": _cmd_backtest, "backtest-report": _cmd_backtest_report,
               "sample-data": _cmd_sample_data}[args.command]
    try:
        return handler(args)
    except CliError as exc:
        logger.error("%s", exc)
        return 1
