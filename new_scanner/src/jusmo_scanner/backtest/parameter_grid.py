"""Parameter sweep definitions and generation. The base config is NEVER mutated:
every variant is built with `override_config` (a `dataclasses.replace`).

OFAT (one factor at a time): each variant changes exactly one parameter of the
base config; `baseline` is the unchanged base config. The sweep only REPORTS how
signal statistics move; nothing here selects a "best" value.

A full Cartesian grid exists but is OFF by default: it refuses to run above
`max_combos` unless explicitly overridden, and reports the combo count first.
"""
from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, field
from typing import Any, Iterator, Mapping, Sequence

from jusmo_scanner.config import ScannerConfig, override_config

logger = logging.getLogger(__name__)

BASELINE_ID = "baseline"
DEFAULT_MAX_COMBOS = 200


@dataclass(frozen=True)
class Variant:
    """One config variant. `parameter` is the swept parameter name (None for the
    baseline); `overrides` maps ScannerConfig field -> value."""
    id: str
    parameter: str | None
    label: str | None
    overrides: Mapping[str, Any] = field(default_factory=dict)


def _n(x: float) -> str:
    """Compact number for ids: integers without a decimal point, floats via %g."""
    if float(x) == int(x) and abs(x) < 1e15:
        return str(int(x))
    return f"{x:g}"


def _simple(param: str, field_name: str, values: Sequence[float], fmt=_n) -> list[Variant]:
    return [Variant(f"{param}={fmt(v)}", param, fmt(v), {field_name: v}) for v in values]


def _band_id(lo: float, hi: float) -> str:
    # lo is the deeper (more negative) bound, hi the shallower one: -3~-8 means [-8%, -3%]
    return f"{_n(round(hi * 100, 10))}%~{_n(round(lo * 100, 10))}%"


# name -> list of Variants (values exactly as specified in the design doc §7)
_EVENT_VALUES_BN = (30, 50, 70, 100, 150)
PARAMETER_VARIANTS: dict[str, list[Variant]] = {
    "event_value": _simple("event_value", "core_event_trading_value",
                           [v * 1_000_000_000 for v in _EVENT_VALUES_BN]),
    "value_ratio": _simple("value_ratio", "strong_event_value_ratio_min", (1.5, 2, 3, 4, 5)),
    "turnover": _simple("turnover", "strong_event_turnover_min", (0.10, 0.20, 0.30, 0.40, 0.50)),
    "vcr": _simple("vcr", "dormant_vcr_max", (0.20, 0.25, 0.30, 0.35, 0.40, 0.50)),
    "cost_tolerance": [Variant(f"cost_tolerance={_n(p)}%", "cost_tolerance", f"{_n(p)}%",
                               {"cost_hold_tolerance_pct": p / 100}) for p in (2, 3, 5, 7, 10)],
    "event_low_atr": _simple("event_low_atr", "atr_tolerance_event_low", (0.0, 0.25, 0.5, 0.75, 1.0)),
    "range10": _simple("range10", "dormant_range10_max", (0.08, 0.10, 0.12, 0.15, 0.20)),
    # bands "shallow~deep" in percent: min = deeper (more negative) bound, max = shallower bound
    "pullback": [
        Variant(f"pullback={_band_id(lo / 100, hi / 100)}", "pullback", _band_id(lo / 100, hi / 100),
                {"pullback_drawdown_min": lo / 100, "pullback_drawdown_max": hi / 100})
        for hi, lo in ((-3, -8), (-3, -10), (-3, -12), (-5, -10), (-5, -12), (-5, -15))
    ],
}


def baseline_variant() -> Variant:
    return Variant(BASELINE_ID, None, None, {})


def ofat_variants(parameters: Sequence[str] | None = None) -> list[Variant]:
    """`baseline` followed by every OFAT variant (all parameters, or only the named
    ones), in definition order."""
    names = list(PARAMETER_VARIANTS) if parameters is None else list(parameters)
    unknown = [p for p in names if p not in PARAMETER_VARIANTS]
    if unknown:
        raise ValueError(f"unknown sweep parameter(s): {', '.join(unknown)}")
    out = [baseline_variant()]
    for p in names:
        out.extend(PARAMETER_VARIANTS[p])
    return out


def apply_variant(base_cfg: ScannerConfig, variant: Variant) -> ScannerConfig:
    """Config of a variant; `base_cfg` is left untouched (frozen dataclass)."""
    return override_config(base_cfg, **variant.overrides) if variant.overrides else base_cfg


def cartesian_combo_count(parameters: Sequence[str] | None = None) -> int:
    names = list(PARAMETER_VARIANTS) if parameters is None else list(parameters)
    n = 1
    for p in names:
        n *= len(PARAMETER_VARIANTS[p])
    return n


def cartesian_variants(parameters: Sequence[str] | None = None, *, max_combos: int = DEFAULT_MAX_COMBOS,
                       allow_exceed: bool = False) -> Iterator[Variant]:
    """Full Cartesian product of the chosen parameters' value lists (DEFAULT OFF:
    nothing calls this unless an experiment asks for it). The combo count is
    logged and checked BEFORE anything is generated; above `max_combos` a
    ValueError is raised unless `allow_exceed=True`. The returned iterator is lazy."""
    names = list(PARAMETER_VARIANTS) if parameters is None else list(parameters)
    unknown = [p for p in names if p not in PARAMETER_VARIANTS]
    if unknown:
        raise ValueError(f"unknown sweep parameter(s): {', '.join(unknown)}")
    total = cartesian_combo_count(names)
    logger.info("cartesian grid over %s: %d combinations (max_combos=%d)", names, total, max_combos)
    if total > max_combos and not allow_exceed:
        raise ValueError(
            f"cartesian grid has {total} combinations, above max_combos={max_combos}; "
            "pass allow_exceed=True (or a larger max_combos) to run it")
    return _cartesian(names)


def _cartesian(names: list[str]) -> Iterator[Variant]:
    for combo in itertools.product(*(PARAMETER_VARIANTS[p] for p in names)):
        overrides: dict[str, Any] = {}
        for v in combo:
            overrides.update(v.overrides)
        yield Variant("|".join(v.id for v in combo), "cartesian", None, overrides)
