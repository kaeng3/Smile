"""CSV / JSON / Markdown reports of a stored backtest experiment.

Everything is generated from the SQLite database (`backtest-report` and `backtest` use
the same path), so a re-generated report is identical to the original.

How to read the numbers (repeated in every summary):
* Results are HISTORICAL ASSOCIATIONS, not evidence of future predictive validity.
* `std_return` is the dispersion of the sample's forward returns. It is NOT a standard
  error of the mean; no confidence interval or significance test is claimed anywhere.
* Samples overlap in time (a signal's forward window overlaps the next signals') and
  across tickers (market-wide moves), so they are not independent observations.
* Rows are never totalled across signal types: one bar can carry several signal types
  and some types select identical samples (see the IDENTICAL_SAMPLES /
  OVERLAPPING_SAMPLES notes).
* Groups are listed in group-key (bucket) order, never sorted by performance. Groups with
  few samples are flagged through `sample_quality` / `low_sample` but never hidden.
* Parameter variants are compared side by side only; no parameter is declared optimal.
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence

from jusmo_scanner.backtest.buckets import DIMENSIONS, MISSING, Bucketer, bool_bucket
from jusmo_scanner.backtest.signals import SignalType
from jusmo_scanner.storage import sqlite_store as store

logger = logging.getLogger(__name__)

DISCLAIMERS: tuple[str, ...] = (
    "Results are historical associations, not evidence of future predictive validity.",
    "std_return is the dispersion of forward returns, not a standard error; samples overlap in "
    "time and across tickers, and no confidence intervals or significance are claimed.",
    "Results are not tuned; no parameter is declared optimal.",
    "Groups are listed in group-key order, never ranked by performance; rows are never totalled "
    "across signal types (one bar can carry several signal types, some select identical samples).",
    "Transaction costs, slippage, limit-up/limit-down or halted fills and market regime are not modelled.",
)

# analysis -> CSV stem (all other analyses: summary_<analysis>)
_STEMS = {
    "by_signal_type": "summary_by_signal", "by_state": "summary_by_state",
    "by_transition": "summary_by_transition", "by_vcr_anchor": "summary_by_vcr",
    "by_event_value": "summary_by_event_value", "by_cost_distance": "summary_by_cost_distance",
    "by_location120": "summary_by_location120", "by_pullback_depth": "summary_by_pullback",
}
HEADLINE_ANALYSES: tuple[str, ...] = (
    "by_state", "by_transition", "by_vcr_anchor", "by_event_value", "by_cost_distance",
    "by_location120", "by_pullback_depth", "pullback_depth_x_volume_ratio")
_JSON_COLUMNS = ("config_json", "options_json", "warnings_json", "failed_tickers_json", "variants_json", "horizons")


class UnknownExperiment(ValueError):
    def __init__(self, experiment_id: str, available: Sequence[str]) -> None:
        self.experiment_id, self.available = experiment_id, list(available)
        super().__init__(
            f"unknown experiment id {experiment_id!r}; available: "
            + (", ".join(self.available) if self.available else "(none)"))


@dataclass
class ReportFiles:
    experiment_id: str
    paths: list[Path] = field(default_factory=list)
    markdown: str = ""
    console_lines: list[str] = field(default_factory=list)


# --- db access ---------------------------------------------------------------------------------

def list_experiments(db_path: str | Path) -> list[str]:
    if not Path(db_path).exists():
        return []
    with store.connection(db_path) as conn:
        try:
            return [r[0] for r in conn.execute(
                "SELECT experiment_id FROM backtest_experiments ORDER BY created_at, experiment_id")]
        except Exception:  # noqa: BLE001 - not a backtest DB
            return []


def _columns(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if r[1] != "id"]


def _rows(conn, table: str, experiment_id: str) -> tuple[list[str], Iterator[tuple]]:
    cols = _columns(conn, table)
    cur = conn.execute(f"SELECT {', '.join(cols)} FROM {table} WHERE experiment_id = ? ORDER BY id",
                       (experiment_id,))
    return cols, iter(cur)


def _cell(v: Any) -> Any:
    """CSV cell: None -> empty, never 'nan'/'inf'; floats via repr (round-trip exact)."""
    if v is None:
        return ""
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return ""
        return repr(v)
    if isinstance(v, bytes):
        raise TypeError("BLOB value in backtest table")
    return v


def _write_csv(path: Path, cols: Sequence[str], rows: Iterator[Sequence[Any]]) -> int:
    n = 0
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow([_cell(v) for v in r])
            n += 1
    return n


def _experiment_dict(conn, experiment_id: str, db_path) -> dict[str, Any]:
    cols = _columns(conn, "backtest_experiments")
    row = None if not cols else conn.execute(f"SELECT {', '.join(cols)} FROM backtest_experiments WHERE experiment_id = ?",
                       (experiment_id,)).fetchone()
    if row is None:
        raise UnknownExperiment(experiment_id, list_experiments(db_path))
    meta = dict(zip(cols, row))
    for k in _JSON_COLUMNS:
        if isinstance(meta.get(k), str):
            try:
                meta[k] = json.loads(meta[k])
            except ValueError:
                pass
    return meta


# --- ordering / formatting ---------------------------------------------------------------------------

def label_rank(dim_name: str, label: str) -> tuple[int, str]:
    """Group-key order of a dimension label: bucket order for numeric dimensions, False/True/
    MISSING for flags, alphabetical for categorical ones. Never performance based."""
    dim = DIMENSIONS.get(dim_name)
    b = dim.bucket if dim is not None else None
    if isinstance(b, Bucketer):
        labels = b.all_labels()
        return (labels.index(label) if label in labels else len(labels), label)
    if b is bool_bucket:
        order = ("False", "True", MISSING)
        return (order.index(label) if label in order else len(order), label)
    return (0, label)


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:+.1f}%"


def group_line(label: str, r: dict[str, Any], horizon: int) -> str:
    flags = " (low sample)" if r.get("low_sample") else ""
    note = f" | {r['note']}" if r.get("note") else ""
    return (f"- {label}: sample {int(r['sample_count']):,} [{r['sample_quality']}], "
            f"{horizon}D median return {_pct(r['median_return'])}, "
            f"median MFE {_pct(r['median_mfe'])}, median MAE {_pct(r['median_mae'])}{flags}{note}")


def _type_order(name: str) -> int:
    try:
        return list(SignalType).index(SignalType[name])
    except KeyError:
        return len(SignalType)


def pick_report_horizon(horizons: Sequence[int], requested: int | None = None) -> int:
    if requested is not None:
        return requested
    hs = sorted(horizons)
    return 20 if 20 in hs else hs[-1]


def render_summary(meta: dict[str, Any], summary: Sequence[dict[str, Any]],
                   report_horizon: int | None = None) -> tuple[str, list[str]]:
    """(markdown text, console lines = header + warnings + by_signal_type section)."""
    horizons = meta.get("horizons") or sorted({r["horizon"] for r in summary}) or [1]
    hz = pick_report_horizon(horizons, report_horizon)
    modes = [m for m in str(meta.get("sample_modes") or "").split(",") if m]
    primary = modes[0] if modes else "FIRST_SIGNAL_PER_EPISODE"
    warnings_list = meta.get("warnings_json") or []
    lines: list[str] = [f"# Backtest summary {meta['experiment_id']}", ""]
    lines += ["## Warnings", ""]
    lines += [f"- {w}" for w in warnings_list]
    lines += [f"- {d}" for d in DISCLAIMERS]
    lines += ["", "## Experiment", ""]
    for k in ("created_at", "status", "source_data_start", "source_data_end", "signal_start", "signal_end", "universe_size", "tickers_scanned",
              "tickers_failed", "sample_modes", "entry_mode", "price_adjustment_mode",
              "share_count_basis", "horizons", "min_sample_size", "history_truncated", "history_truncation_reason", "universe_basis",
              "tickers_with_missing_market_data", "missing_market_data_rows",
              "config_hash", "git_commit", "git_dirty"):
        lines.append(f"- {k}: {meta.get(k)}")
    lines += ["", f"Headline tables use sample mode {primary} at {hz}D; the CSV files contain every "
              "analysis, sample mode and horizon.", ""]

    def by(analysis: str, variant: str, mode: str) -> list[dict[str, Any]]:
        return [r for r in summary if r["analysis"] == analysis and r["variant"] == variant
                and r["sample_mode"] == mode]

    def section_by_type(title: str, rows: list[dict[str, Any]], horizons_shown: Sequence[int]) -> None:
        lines.append(title)
        lines.append("")
        for st in sorted({r["signal_type"] for r in rows}, key=lambda t: (_type_order(t), t)):
            lines.append(f"### {st}")
            for h in horizons_shown:
                for r in rows:
                    if r["signal_type"] == st and r["horizon"] == h:
                        lines.append(group_line(f"{h}D", r, h))
            lines.append("")

    for mode in modes or [primary]:
        rows = by("by_signal_type", "baseline", mode)
        if rows:
            section_by_type(f"## Signal types, {mode} (baseline, all horizons)", rows, sorted(horizons))
    console_end = len(lines)

    variants = [v["id"] for v in (meta.get("variants_json") or [])]
    if len(variants) > 1:
        rows = [r for r in summary if r["analysis"] == "by_signal_type" and r["sample_mode"] == primary
                and r["horizon"] == hz]
        lines += [f"## Parameter variants ({primary}, {hz}D, by signal type)", "",
                  "Variants are listed in definition order; they are alternative configurations, "
                  "compared side by side without ranking.", ""]
        for st in sorted({r["signal_type"] for r in rows}, key=lambda t: (_type_order(t), t)):
            lines.append(f"### {st}")
            for v in variants:
                for r in rows:
                    if r["signal_type"] == st and r["variant"] == v:
                        lines.append(group_line(v, r, hz))
            lines.append("")

    lines += [f"## Headline analyses ({primary}, baseline, {hz}D)", ""]
    for name in HEADLINE_ANALYSES:
        rows = [r for r in by(name, "baseline", primary) if r["horizon"] == hz]
        if not rows:
            continue
        lines += [f"### {name}", ""]
        for st in sorted({r["signal_type"] for r in rows}, key=lambda t: (_type_order(t), t)):
            lines.append(f"#### {st}")
            grp = [r for r in rows if r["signal_type"] == st]
            grp.sort(key=lambda r: (label_rank(r["dim1_name"], r["dim1"]),
                                    label_rank(r["dim2_name"], r["dim2"]) if r["dim2_name"] else (0, "")))
            for r in grp:
                label = r["dim1"] if not r["dim2_name"] else f"{r['dim1']} x {r['dim2']}"
                lines.append(group_line(f"{r['dim1_name']} {label}", r, hz))
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n", lines[:console_end]


# --- export -----------------------------------------------------------------------------------------------

def export_experiment(db_path: str | Path, experiment_id: str, output_dir: str | Path,
                      report_horizon: int | None = None) -> ReportFiles:
    """Writes signals/results/summary CSVs, experiment JSON and the Markdown summary for one
    stored experiment into `output_dir` (created). Raises UnknownExperiment."""
    if not Path(db_path).exists():
        raise UnknownExperiment(experiment_id, [])
    out = Path(output_dir)
    rf = ReportFiles(experiment_id)
    with store.connection(db_path) as conn:
        meta = _experiment_dict(conn, experiment_id, db_path)
        out.mkdir(parents=True, exist_ok=True)
        for table, stem in (("backtest_signals", "signals"), ("backtest_results", "results")):
            cols, rows = _rows(conn, table, experiment_id)
            p = out / f"{stem}_{experiment_id}.csv"
            n = _write_csv(p, cols, rows)
            rf.paths.append(p)
            logger.info("wrote %s (%d rows)", p, n)
        cols, rows = _rows(conn, "backtest_summary", experiment_id)
        summary = [dict(zip(cols, r)) for r in rows]
    by_analysis: dict[str, list[dict[str, Any]]] = {}
    for r in summary:
        by_analysis.setdefault(r["analysis"], []).append(r)
    for analysis, rows in by_analysis.items():
        p = out / f"{_STEMS.get(analysis, f'summary_{analysis}')}_{experiment_id}.csv"
        _write_csv(p, cols, ([r[c] for c in cols] for r in rows))
        rf.paths.append(p)
    meta_path = out / f"experiment_{experiment_id}.json"
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
                         encoding="utf-8")
    rf.paths.append(meta_path)
    rf.markdown, rf.console_lines = render_summary(meta, summary, report_horizon)
    md_path = out / f"summary_{experiment_id}.md"
    md_path.write_text(rf.markdown, encoding="utf-8", newline="\n")
    rf.paths.append(md_path)
    return rf
