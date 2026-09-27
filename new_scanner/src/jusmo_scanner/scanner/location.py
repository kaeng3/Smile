"""Causal event location and strategy interpretation (no price clipping)."""
from .snapshot import to_plain_float


def classify_location(value, cfg) -> str:
    value = to_plain_float(value)
    if value is None:
        return "UNKNOWN"
    if value <= cfg.event_location_bottom_max:
        return "BOTTOM"
    if value >= cfg.event_location_high_min:
        return "HIGH"
    return "MIDDLE"


def strategy_family(anchor_location: str) -> str:
    return "BOTTOM_ACCUMULATION" if anchor_location == "BOTTOM" else f"{anchor_location}_COST_TRACKING"
