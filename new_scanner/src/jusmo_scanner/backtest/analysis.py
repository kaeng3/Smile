"""Registry of bucket analyses and the streaming summary accumulator.

An analysis groups the forward results of signals by one (single-variable) or two
(interaction) bucketed dimensions, always separately per signal_type and horizon:
one output row per (analysis, variant, sample_mode, entry_mode, dim1, dim2,
signal_type, horizon) with the objective `GroupStats`. Nothing here ranks groups or
picks a "best" one.

Memory: the accumulator keeps ONE compact record per result row (3 doubles + a
16-bit hit mask = 26 bytes) and, per group, a `uint32` index array (4 bytes per
member). Total ~ 26 B x results + 4 B x results x (#analyses that apply). For the
default 30 analyses that is ~ 150 B per (signal, horizon) result row; restrict
`analyses`, signal types or horizons for very large universes.

Note on `OVERLAPPING_SAMPLES(x%)`: the denominator is the number of SAMPLES (signals) of that
type in the row's sample mode, counted once per signal - not per horizon - so the same value is
repeated on every horizon row of a type. The numerator is the samples whose bar also carries
another signal type (`signal_types_on_bar > 1`).
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np

from jusmo_scanner.backtest.buckets import DIMENSIONS
from jusmo_scanner.backtest.engine import SampleMode, SignalResult
from jusmo_scanner.backtest.metrics import (
    DEFAULT_MIN_SAMPLE_SIZE, DEFAULT_QUALITY_THRESHOLDS, EntryMode, GroupArrays,
    aggregate_group, pack_hits)
from jusmo_scanner.backtest.signals import Signal, SignalType, signal_semantics

NO_DIM = ""  # dim2 name/label of single-variable analyses (a sentinel, not NULL, so UNIQUE keys work)


@dataclass(frozen=True)
class Analysis:
    name: str
    dims: tuple[str, ...]                       # one or two names from buckets.DIMENSIONS
    kind: str                                   # "single" | "interaction" | "pullback"
    signal_types: frozenset[SignalType] | None = None   # None = every signal type

    def __post_init__(self) -> None:
        assert 1 <= len(self.dims) <= 2 and all(d in DIMENSIONS for d in self.dims), self.dims


SINGLE_ANALYSES: tuple[Analysis, ...] = tuple(
    Analysis(f"by_{d}", (d,), "single") for d in DIMENSIONS)

_PULLBACK_ONLY = frozenset({SignalType.PULLBACK})

# Exactly the six interaction analyses of the design (§7). EventValue x CapitalImpact
# uses the ANCHOR-bar capital impact (`event_capital_impact`), consistent with the
# anchor event's trading value.
INTERACTION_ANALYSES: tuple[Analysis, ...] = (
    Analysis("state_x_vcr", ("state", "vcr_anchor"), "interaction"),
    Analysis("state_x_cost_distance", ("state", "cost_distance"), "interaction"),
    Analysis("state_x_location120", ("state", "location120"), "interaction"),
    Analysis("event_value_x_capital_impact", ("event_value", "event_capital_impact"), "interaction"),
    Analysis("pullback_depth_x_vcr", ("pullback_depth", "vcr_anchor"), "interaction", _PULLBACK_ONLY),
    Analysis("structure_score_x_trigger_score", ("structure_score", "trigger_score"), "interaction"),
)

# PULLBACK-specific report: depth x volume contraction (pullback volume / breakout volume).
PULLBACK_ANALYSES: tuple[Analysis, ...] = (
    Analysis("pullback_depth_x_volume_ratio", ("pullback_depth", "pullback_volume_ratio"),
             "pullback", _PULLBACK_ONLY),
)

ALL_ANALYSES: tuple[Analysis, ...] = SINGLE_ANALYSES + INTERACTION_ANALYSES + PULLBACK_ANALYSES
ANALYSES_BY_NAME: dict[str, Analysis] = {a.name: a for a in ALL_ANALYSES}
# Analyses run for sweep variants (engine re-runs): only the per-signal-type comparison.
SWEEP_ANALYSES: tuple[str, ...] = ("by_signal_type",)


def select_analyses(names: Iterable[str] | None) -> tuple[Analysis, ...]:
    if names is None:
        return ALL_ANALYSES
    out = []
    for n in names:
        if n not in ANALYSES_BY_NAME:
            raise ValueError(f"unknown analysis {n!r}; known: {', '.join(ANALYSES_BY_NAME)}")
        out.append(ANALYSES_BY_NAME[n])
    return tuple(out)


def signal_row(signal: Signal) -> dict[str, Any]:
    """Row mapping the bucket dimensions read: snapshot fields + signal_type."""
    row = signal.snapshot.to_dict()
    row["signal_type"] = signal.signal_type.value
    return row


_MASK = (1 << 64) - 1
GroupKey = tuple  # (analysis, variant, sample_mode, dim1, dim2, signal_type, horizon)


class SummaryAccumulator:
    """Streams (signal, results) pairs into per-group index lists; `finalize`
    aggregates every group. Pure in-memory; the experiment writes the rows out."""

    def __init__(self, analyses: Sequence[Analysis], entry_mode: EntryMode,
                 sample_modes: Sequence[SampleMode]) -> None:
        self._analyses = {a.name: a for a in analyses}
        self.entry_mode = entry_mode
        self.sample_modes = tuple(sample_modes)
        self._ret = array("d")
        self._mfe = array("d")
        self._mae = array("d")
        self._hits = array("H")
        self._groups: dict[GroupKey, array] = {}
        # (variant, sample_mode, signal_type) -> [count, sum of hash1, sum of hash2] over the
        # (ticker, episode_id, bar_index) identities of its samples: an O(1)-memory,
        # order-independent fingerprint used to flag identical sample sets (two 64-bit
        # sums + the count; a false "identical" would need a simultaneous collision).
        self._samples: dict[tuple[str, str, str], list[int]] = {}

    def __len__(self) -> int:
        return len(self._ret)

    def empty_like(self) -> "SummaryAccumulator":
        """A new, empty accumulator with the same analyses / entry mode / sample modes."""
        return SummaryAccumulator(list(self._analyses.values()), self.entry_mode, self.sample_modes)

    def merge(self, other: "SummaryAccumulator") -> None:
        """Adds everything `other` holds (its result rows are appended and its group
        indices shifted). `other` must not be used afterwards."""
        base = len(self._ret)
        self._ret.extend(other._ret)
        self._mfe.extend(other._mfe)
        self._mae.extend(other._mae)
        self._hits.extend(other._hits)
        for key, idx in other._groups.items():
            shifted = np.frombuffer(idx, dtype=np.uint32).astype(np.uint64) + np.uint64(base)
            if len(shifted) and int(shifted.max()) > 0xFFFFFFFF:
                raise OverflowError("more than 2**32 result rows: group index arrays are uint32")
            shifted = shifted.astype(np.uint32)
            g = self._groups.get(key)
            if g is None:
                g = self._groups[key] = array("I")
            g.frombytes(shifted.tobytes())
        for key, fp in other._samples.items():
            mine = self._samples.setdefault(key, [0, 0, 0, 0])
            mine[3] += fp[3]
            mine[0] += fp[0]
            mine[1] = (mine[1] + fp[1]) & _MASK
            mine[2] = (mine[2] + fp[2]) & _MASK

    def add(self, variant: str, signal: Signal, is_first: bool, results: Sequence[SignalResult],
            analysis_names: Sequence[str] | None = None) -> None:
        """Adds one signal with its (already evaluated) results. `is_first`: the
        signal is the first of its type in its episode (FIRST_SIGNAL_PER_EPISODE member)."""
        modes = [m for m in self.sample_modes if m is SampleMode.ALL_SIGNALS or is_first]
        if not modes:
            return
        stype = signal.signal_type.value
        h1 = hash((signal.ticker, signal.episode_id, signal.bar_index)) & _MASK
        h2 = hash((signal.bar_index, signal.episode_id, signal.ticker, 0x9E3779B97F4A7C15)) & _MASK
        for m in modes:
            fp = self._samples.setdefault((variant, m.value, stype), [0, 0, 0, 0])
            fp[3] += 1 if (signal.signal_types_on_bar or 1) > 1 else 0
            fp[0] += 1
            fp[1] = (fp[1] + h1) & _MASK
            fp[2] = (fp[2] + h2) & _MASK
        if not results:
            return
        idxs = []
        for r in results:
            f = r.forward
            self._ret.append(f.forward_return)
            self._mfe.append(f.mfe)
            self._mae.append(f.mae)
            self._hits.append(pack_hits(f))
            idxs.append(len(self._ret) - 1)
        row = signal_row(signal)
        labels: dict[str, str] = {}

        def label(dim: str) -> str:
            if dim not in labels:
                labels[dim] = DIMENSIONS[dim].label(row)
            return labels[dim]

        names = self._analyses if analysis_names is None else analysis_names
        for name in names:
            a = self._analyses.get(name)
            if a is None or (a.signal_types is not None and signal.signal_type not in a.signal_types):
                continue
            d1 = label(a.dims[0])
            d2 = label(a.dims[1]) if len(a.dims) == 2 else NO_DIM
            for r, idx in zip(results, idxs):
                for m in modes:
                    key = (name, variant, m.value, d1, d2, stype, r.horizon)
                    g = self._groups.get(key)
                    if g is None:
                        g = self._groups[key] = array("I")
                    g.append(idx)

    def identical_groups(self, variant: str, sample_mode: str) -> list[tuple[str, ...]]:
        """Groups (size >= 2) of signal types with identical sample sets (same contract as
        `signals.identical_sample_groups`, evaluated on the fingerprints)."""
        by_fp: dict[tuple[int, int, int], list[str]] = {}
        for (v, m, t), fp in self._samples.items():
            if v == variant and m == sample_mode and fp[0] > 0:
                by_fp.setdefault((fp[0], fp[1], fp[2]), []).append(t)
        return sorted(tuple(sorted(g)) for g in by_fp.values() if len(g) > 1)

    def finalize(self, quality_thresholds: Sequence[int] = DEFAULT_QUALITY_THRESHOLDS,
                 min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE) -> list[dict[str, Any]]:
        ret = np.frombuffer(self._ret, dtype=np.float64)
        mfe = np.frombuffer(self._mfe, dtype=np.float64)
        mae = np.frombuffer(self._mae, dtype=np.float64)
        hits = np.frombuffer(self._hits, dtype=np.uint16).astype(np.int64)
        identical: dict[tuple[str, str], dict[str, tuple[str, ...]]] = {}
        for (v, m) in {(k[1], k[2]) for k in self._groups}:
            identical[(v, m)] = {t: g for g in self.identical_groups(v, m) for t in g}
        rows: list[dict[str, Any]] = []
        for key in sorted(self._groups):
            name, variant, mode, d1, d2, stype, horizon = key
            idx = np.frombuffer(self._groups[key], dtype=np.uint32)
            stats = aggregate_group(
                GroupArrays(ret[idx], mfe[idx], mae[idx], hits[idx]),
                quality_thresholds, min_sample_size)
            a = self._analyses[name]
            row: dict[str, Any] = {
                "analysis_name": name, "variant": variant, "sample_mode": mode,
                "entry_mode": self.entry_mode.value,
                "dim1_name": a.dims[0], "dim1": d1,
                "dim2_name": a.dims[1] if len(a.dims) == 2 else NO_DIM, "dim2": d2,
                "signal_type": stype, "horizon": horizon,
            }
            row.update(stats.to_dict())
            row["note"] = self._note(stype, identical.get((variant, mode), {}),
                                     self._overlap_pct(variant, mode, stype))
            rows.append(row)
        return rows

    def _overlap_pct(self, variant: str, mode: str, stype: str) -> float | None:
        """Percent of this type's samples (per signal, all horizons alike) whose bar also
        carries another signal type."""
        fp = self._samples.get((variant, mode, stype))
        return None if not fp or fp[0] == 0 else 100.0 * fp[3] / fp[0]

    def _note(self, stype: str, identical: dict[str, tuple[str, ...]],
              overlap_pct: float | None = None) -> str | None:
        parts: list[str] = []
        if stype in identical:
            parts.append("IDENTICAL_SAMPLES: " + "/".join(identical[stype]))
        if overlap_pct is not None and overlap_pct > 0:
            # informational: share of this type's sample bars that also carry another signal type
            parts.append(f"OVERLAPPING_SAMPLES({overlap_pct:.0f}%)")
        st = SignalType(stype)
        if signal_semantics(st).startswith("EVENT_BASELINE"):
            parts.append("EVENT_BASELINE (unconfirmed: not a confirmation of accumulation)")
        if self.entry_mode is EntryMode.CLOSE:
            parts.append("optimistic assumption (CLOSE entry)")
        return "; ".join(parts) if parts else None
