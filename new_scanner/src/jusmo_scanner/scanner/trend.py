from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ResistanceLine:
    slope: float
    intercept: float


def fit_resistance_line(positions: list[int], prices: list[float]) -> ResistanceLine | None:
    """Fits a straight line through the LAST two confirmed swing highs.
    Returns None if there are fewer than two points, the two x-positions
    coincide, or the resulting line is not descending (slope >= 0) — a flat
    or rising line is not a resistance line."""
    if len(positions) < 2:
        return None
    x1, x2 = positions[-2], positions[-1]
    y1, y2 = prices[-2], prices[-1]
    if x2 == x1:
        return None
    slope = (y2 - y1) / (x2 - x1)
    if slope >= 0:
        return None
    intercept = y1 - slope * x1
    return ResistanceLine(slope=slope, intercept=intercept)


def line_value(line: ResistanceLine, x: int) -> float:
    return line.slope * x + line.intercept
