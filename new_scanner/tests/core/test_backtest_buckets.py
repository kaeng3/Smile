from __future__ import annotations

import math

import pandas as pd
import pytest

from jusmo_scanner.backtest import buckets as b
from jusmo_scanner.backtest.buckets import DIMENSIONS, MISSING

BN = 1e9


# (bucket function, [(value, label)]) - every edge is tested on both sides
CASES = {
    "event_value": (b.event_value_bucket, [
        (0, "<30bn"), (29.99 * BN, "<30bn"), (30 * BN, "30-50bn"), (49.99 * BN, "30-50bn"),
        (50 * BN, "50-70bn"), (70 * BN, "70-100bn"), (100 * BN, "100-150bn"),
        (149 * BN, "100-150bn"), (150 * BN, "150+bn"), (900 * BN, "150+bn")]),
    "value_ratio": (b.value_ratio_bucket, [
        (1.49, "<1.5"), (1.5, "1.5-2"), (2, "2-3"), (2.99, "2-3"), (3, "3-4"), (4, "4-5"), (5, "5+"), (9, "5+")]),
    "turnover": (b.turnover_bucket, [
        (0.05, "<0.1"), (0.1, "0.1-0.2"), (0.2, "0.2-0.3"), (0.3, "0.3-0.4"), (0.4, "0.4-0.5"),
        (0.5, "0.5+"), (2.0, "0.5+")]),
    "capital_impact": (b.capital_impact_bucket, [
        (-0.001, "<0%"), (0.0, "0-1%"), (0.0099, "0-1%"), (0.01, "1-3%"), (0.03, "3-5%"),
        (0.05, "5-10%"), (0.1, "10-20%"), (0.2, "20+%"), (0.7, "20+%")]),
    "location120": (b.location120_bucket, [
        (-0.1, "<0"), (0.0, "0-0.2"), (0.2, "0.2-0.4"), (0.4, "0.4-0.6"), (0.6, "0.6-0.8"),
        (0.8, "0.8-1"), (0.9999, "0.8-1"), (1.0, "1+"), (1.4, "1+")]),
    "vcr": (b.vcr_bucket, [
        (-0.01, "<0"), (0.0, "0-0.2"), (0.19, "0-0.2"), (0.2, "0.2-0.25"), (0.25, "0.25-0.3"),
        (0.2999, "0.25-0.3"), (0.3, "0.3-0.35"), (0.35, "0.35-0.4"), (0.4, "0.4-0.5"), (0.5, "0.5-0.75"),
        (0.75, "0.75+"), (3.0, "0.75+")]),
    "range10": (b.range10_bucket, [
        (0.0, "0-5%"), (0.05, "5-8%"), (0.08, "8-10%"), (0.1, "10-12%"), (0.12, "12-15%"),
        (0.15, "15-20%"), (0.2, "20+%"), (0.5, "20+%")]),
    "cost_distance": (b.cost_distance_bucket, [
        (-0.2, "<-10%"), (-0.1, "-10~-5%"), (-0.05, "-5~-2%"), (-0.02, "-2~0%"), (0.0, "0~2%"),
        (0.02, "2~5%"), (0.05, "5~10%"), (0.1, "10~20%"), (0.2, "20+%")]),
    "event_low_distance": (b.event_low_distance_bucket, [
        (-0.01, "<0%"), (0, "0-3%"), (0.03, "3-5%"), (0.05, "5-10%"), (0.1, "10-20%"),
        (0.2, "20-30%"), (0.3, "30+%")]),
    "event_age": (b.event_age_bucket, [
        (-1, "<0"), (0, "0-3"), (3, "0-3"), (4, "4-7"), (7, "4-7"), (8, "8-14"), (14, "8-14"),
        (15, "15-30"), (30, "15-30"), (31, "31-60"), (60, "31-60"), (61, "60+"), (500, "60+")]),
    "event_count": (b.event_count_bucket, [(1, "1"), (2, "2"), (3, "3"), (4, "4+"), (9, "4+")]),
    "cluster_value": (b.cluster_value_bucket, [
        (49 * BN, "<50bn"), (50 * BN, "50-100bn"), (100 * BN, "100-200bn"),
        (200 * BN, "200-500bn"), (500 * BN, "500+bn")]),
    "events_in_last_20d": (b.events_in_last_20d_bucket, [(0, "0"), (1, "1"), (3, "3"), (4, "4+")]),
    "pullback_depth": (b.pullback_depth_bucket, [
        (-0.2, "<-15%"), (-0.15, "-15~-12%"), (-0.12, "-12~-10%"), (-0.1, "-10~-8%"),
        (-0.08, "-8~-5%"), (-0.05, "-5~-3%"), (-0.03, "-3~0%"), (0.0, "0+%")]),
    "pullback_volume_ratio": (b.pullback_volume_ratio_bucket, [
        (0.1, "<0.25"), (0.25, "0.25-0.5"), (0.5, "0.5-0.75"), (0.75, "0.75-1"), (1.0, "1-1.5"), (1.5, "1.5+")]),
    "days_since_breakout": (b.days_since_breakout_bucket, [
        (0, "0"), (1, "1-2"), (2, "1-2"), (3, "3-5"), (6, "6-10"), (11, "11-20"), (21, "21+")]),
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_bucket_edges(name):
    fn, cases = CASES[name]
    for value, label in cases:
        assert fn(value) == label, (name, value)


def test_right_open_boundary_semantics():
    # exactly on an edge -> the UPPER bucket (right-open [lo, hi))
    assert b.vcr_bucket(0.25) == "0.25-0.3" and b.vcr_bucket(0.25 - 1e-12) == "0.2-0.25"
    assert b.range10_bucket(0.08) == "8-10%"         # 8/100 == 0.08 exactly, no float drift
    assert b.capital_impact_bucket(0.03) == "3-5%"
    assert b.event_value_bucket(50_000_000_000) == "50-70bn"


def test_structure_score_bucket():
    f = b.structure_score_bucket
    assert [f(v) for v in (0, 49.99, 50, 59.99, 60, 70, 80, 89.99, 90, 99.9, 100)] == [
        "0-50", "0-50", "50-60", "50-60", "60-70", "70-80", "80-90", "80-90", "90-100", "90-100", "90-100"]
    assert f(-1) == "<0" and f(100.5) == ">100"        # explicit, never dropped
    assert f(None) == MISSING


def test_trigger_score_bucket():
    f = b.trigger_score_bucket
    assert [f(v) for v in (0, 50, 60, 90, 100)] == ["0-50", "50-60", "60-70", "90-100", "90-100"]
    assert f(float("nan")) == MISSING and f(100.01) == ">100"


@pytest.mark.parametrize("missing", [None, float("nan"), float("inf"), -math.inf, pd.NA, "abc", True])
def test_missing_values_get_explicit_label(missing):
    for name, (fn, _) in CASES.items():
        assert fn(missing) == MISSING, name
    assert b.structure_score_bucket(missing) == MISSING


def test_bool_and_categorical_buckets():
    assert (b.bool_bucket(True), b.bool_bucket(False), b.bool_bucket(None)) == ("True", "False", MISSING)
    assert b.identity_bucket("PULLBACK") == "PULLBACK" and b.identity_bucket(None) == MISSING
    assert b.transition_label("BREAKOUT", "PULLBACK") == "BREAKOUT->PULLBACK"
    assert b.transition_label(None, "PULLBACK") == MISSING


def test_labels_are_unique_and_cover_every_value():
    for name, (fn, _) in CASES.items():
        assert len(set(fn.labels)) == len(fn.labels), name
        assert fn.all_labels()[-1] == MISSING
        # every edge value lands on the label at its own index (no gaps / overlaps)
        for k, e in enumerate(fn.edges):
            assert fn(e) == fn.labels[k + 1], (name, e)


def test_dimension_registry_reads_snapshot_rows():
    row = {"state": "PULLBACK", "previous_state": "BREAKOUT", "signal_type": "PULLBACK",
           "event_trading_value": 75e9, "event_value_ratio": 2.5, "event_turnover": 0.33,
           "capital_impact": 0.04, "event_capital_impact": None, "location120": 0.55,
           "vcr_anchor": 0.25, "cost_distance": 0.01, "days_since_event_trading": 12,
           "event_count_so_far": 2, "structure_score": 100.0, "above_ma240": False,
           "accumulation_confirmed": True, "pullback_depth": -0.07}
    lab = {n: d.label(row) for n, d in DIMENSIONS.items()}
    assert lab["state"] == "PULLBACK" and lab["transition"] == "BREAKOUT->PULLBACK"
    assert lab["event_value"] == "70-100bn" and lab["value_ratio"] == "2-3" and lab["turnover"] == "0.3-0.4"
    assert lab["capital_impact"] == "3-5%" and lab["event_capital_impact"] == MISSING
    assert lab["vcr_anchor"] == "0.25-0.3" and lab["event_age"] == "8-14" and lab["event_count"] == "2"
    assert lab["structure_score"] == "90-100" and lab["trigger_score"] == MISSING
    assert lab["above_ma240"] == "False" and lab["previous_high_break"] == MISSING
    assert lab["accumulation_confirmed"] == "True" and lab["pullback_depth"] == "-8~-5%"
    for needed in ("vcr_anchor", "vcr_latest_event", "vcr_max_event", "range10", "cost_distance",
                   "event_low_distance", "location120", "cluster_value", "events_in_last_20d",
                   "pullback_volume_ratio", "days_since_breakout"):
        assert needed in DIMENSIONS


EOK = 1e8  # 1 "억" in KRW


def test_krw_buckets_pin_the_eok_semantics_with_real_magnitudes():
    # design §7: event value 300/500/700/1000/1500억 == 30/50/70/100/150bn (bn = 1e9 KRW)
    for eok, label in ((299, "<30bn"), (300, "30-50bn"), (500, "50-70bn"), (700, "70-100bn"),
                       (1000, "100-150bn"), (1500, "150+bn")):
        assert b.event_value_bucket(eok * EOK) == label, eok
    # a single 5e10 KRW (500억) event sits exactly on the 50bn boundary -> upper bucket
    assert b.event_value_bucket(5e10) == "50-70bn" and b.event_value_bucket(5e10 - 1) == "30-50bn"
    # design §7: cluster <500억, 500-1000억, 1000-2000억, 2000-5000억, 5000억+
    for eok, label in ((499, "<50bn"), (500, "50-100bn"), (1000, "100-200bn"),
                       (2000, "200-500bn"), (5000, "500+bn")):
        assert b.cluster_value_bucket(eok * EOK) == label, eok
    assert b.cluster_value_bucket(5e10) == "50-100bn" and b.cluster_value_bucket(5e11) == "500+bn"
    assert b.cluster_value_bucket.edges == (5e10, 1e11, 2e11, 5e11)
    assert b.event_value_bucket.edges == (3e10, 5e10, 7e10, 1e11, 1.5e11)


def test_realistic_cluster_totals_spread_over_several_buckets():
    from tests import synthetic as syn
    from jusmo_scanner.config import load_config
    from jusmo_scanner.scanner import engine
    cfg = load_config("config/scanner.yaml")
    labels = set()
    for seed in range(12):
        scan = engine.scan_ticker(syn.random_frame(seed, 600), "T", cfg, collect_snapshots=True)
        labels |= {b.cluster_value_bucket(s.cluster_trading_value_so_far) for s in scan.snapshots}
    assert len(labels - {MISSING}) >= 4, labels
