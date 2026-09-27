# src/jusmo_scanner/scanner/accumulation.py
from __future__ import annotations
import math
import pandas as pd


def compute_typical_price(high: float, low: float, close: float) -> float:
    return (high + low + close) / 3


def compute_estimated_cost(event_price: float, anchored_vwap: float, weight_event: float, weight_vwap: float) -> float:
    return weight_event * event_price + weight_vwap * anchored_vwap


def compute_cost_distance(close: float, estimated_cost: float) -> float:
    if not estimated_cost or (isinstance(estimated_cost, float) and math.isnan(estimated_cost)):
        return float("nan")
    return (close - estimated_cost) / estimated_cost


def compute_vcr(avg_volume_5: float, event_volume: float) -> float:
    if not event_volume or (isinstance(event_volume, float) and math.isnan(event_volume)):
        return float("nan")
    return avg_volume_5 / event_volume


def compute_event_low_limit(event_low: float, atr20: float, tolerance: float) -> float:
    return event_low - atr20 * tolerance


def is_event_low_hold(close: float, event_low_limit: float) -> bool:
    return close >= event_low_limit


def is_estimated_cost_hold(close: float, estimated_cost: float, atr20: float, invalidation_multiplier: float) -> bool:
    return close >= estimated_cost - atr20 * invalidation_multiplier
