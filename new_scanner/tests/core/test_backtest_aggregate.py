from __future__ import annotations

import json
import math

import numpy as np
import pytest

from jusmo_scanner.backtest.metrics import (
    HIT_FIELDS, GroupArrays, aggregate_group, pack_hits, sample_quality)
from jusmo_scanner.config import ScannerConfig, load_config, override_config

CFG = load_config("config/scanner.yaml")

# hand-computed example (n = 5)
RET = [-0.02, 0.01, 0.03, 0.05, 0.10]
MFE = [0.02, 0.04, 0.06, 0.08, 0.20]
MAE = [-0.01, -0.02, -0.04, -0.06, -0.25]


def _rows(ret=RET, mfe=MFE, mae=MAE):
    rows = []
    for r, f, a in zip(ret, mfe, mae):
        row = {"forward_return": r, "mfe": f, "mae": a}
        for name in HIT_FIELDS:
            kind, _, pct = name.rpartition("_")
            thr = int(pct) / 100
            row[name] = f >= thr - 1e-12 if kind == "hit_up" else a <= -thr + 1e-12
        rows.append(row)
    return rows


def test_aggregate_group_hand_computed_example():
    g = aggregate_group(_rows())
    assert g.sample_count == 5
    assert g.mean_return == pytest.approx(0.034)
    assert g.median_return == pytest.approx(0.03)
    # sample std (ddof=1): sqrt(0.00812 / 4)
    assert g.std_return == pytest.approx(math.sqrt(0.00812 / 4))
    assert g.mean_mfe == pytest.approx(0.08) and g.median_mfe == pytest.approx(0.06)
    assert g.mean_mae == pytest.approx(-0.076) and g.median_mae == pytest.approx(-0.04)
    assert g.win_rate == pytest.approx(0.8)
    # linear interpolation at position p/100*(n-1)
    assert g.return_p10 == pytest.approx(-0.008)   # pos 0.4 between -0.02 and 0.01
    assert g.return_p25 == pytest.approx(0.01)
    assert g.return_p50 == pytest.approx(0.03)
    assert g.return_p75 == pytest.approx(0.05)
    assert g.return_p90 == pytest.approx(0.08)     # pos 3.6 between 0.05 and 0.10
    assert (g.mfe_p50, g.mfe_p75) == (pytest.approx(0.06), pytest.approx(0.08))
    assert g.mfe_p90 == pytest.approx(0.152)       # pos 3.6 between 0.08 and 0.20
    assert g.mae_p10 == pytest.approx(-0.174)      # sorted -0.25,-0.06,-0.04,-0.02,-0.01; pos 0.4
    assert g.mae_p25 == pytest.approx(-0.06) and g.mae_p50 == pytest.approx(-0.04)
    # hit shares are fractions of the sample
    assert (g.hit_up_5, g.hit_up_10, g.hit_up_15, g.hit_up_20, g.hit_up_30) == pytest.approx(
        (0.6, 0.2, 0.2, 0.2, 0.0))
    assert (g.hit_down_3, g.hit_down_5, g.hit_down_10, g.hit_down_15, g.hit_down_20) == pytest.approx(
        (0.6, 0.4, 0.2, 0.2, 0.2))
    assert g.sample_quality == "VERY_LOW" and g.low_sample is True


def test_percentiles_match_numpy_default_linear_interpolation():
    rng = np.random.RandomState(3)
    r = rng.normal(0.01, 0.05, 137)
    g = aggregate_group(_rows(list(r), list(np.abs(r) + 0.01), list(-np.abs(r) - 0.01)))
    for p in (10, 25, 50, 75, 90):
        assert getattr(g, f"return_p{p}") == pytest.approx(float(np.percentile(r, p)), abs=1e-15)
    assert g.median_return == pytest.approx(float(np.median(r)), abs=1e-15)


def test_sample_quality_thresholds():
    cases = {0: "VERY_LOW", 29: "VERY_LOW", 30: "LOW", 99: "LOW", 100: "MEDIUM", 299: "MEDIUM",
             300: "HIGH", 5000: "HIGH"}
    for n, q in cases.items():
        assert sample_quality(n) == q, n
    assert sample_quality(10, (5, 8, 12)) == "MEDIUM"
    assert sample_quality(12, (5, 8, 12)) == "HIGH"
    rows = _rows()
    big = aggregate_group(rows * 20, (30, 100, 300), 100)        # n = 100
    assert big.sample_count == 100 and big.sample_quality == "MEDIUM" and big.low_sample is False
    assert aggregate_group(rows * 20, (30, 100, 300), 101).low_sample is True
    assert aggregate_group(rows * 60).sample_quality == "HIGH"  # n = 300


def test_low_sample_values_are_still_shown():
    g = aggregate_group(_rows()[:2], min_sample_size=100)
    assert g.low_sample is True and g.mean_return is not None and g.median_mfe is not None


def test_empty_group_has_no_fabricated_numbers():
    g = aggregate_group([])
    assert g.sample_count == 0 and g.sample_quality == "VERY_LOW" and g.low_sample is True
    d = g.to_dict()
    stats = {k: v for k, v in d.items() if k not in ("sample_count", "sample_quality", "low_sample")}
    assert stats and all(v is None for v in stats.values())
    empty = aggregate_group(GroupArrays(*(np.array([]),) * 3, np.array([], dtype=np.int64)))
    assert empty == g


def test_single_observation_std_is_none():
    g = aggregate_group(_rows()[:1])
    assert g.sample_count == 1 and g.std_return is None
    assert g.return_p10 == g.return_p90 == g.median_return == pytest.approx(-0.02)


def test_non_finite_inputs_are_excluded_and_never_leak():
    rows = _rows()
    bad = [dict(rows[0], forward_return=float("nan")), dict(rows[1], mfe=float("inf")),
           dict(rows[2], mae=None), dict(rows[3], forward_return=-math.inf)]
    g = aggregate_group(rows + bad)
    assert g.sample_count == 5 and g.mean_return == pytest.approx(0.034)
    all_bad = aggregate_group(bad)
    assert all_bad.sample_count == 0 and all_bad.mean_return is None
    for grp in (g, all_bad):
        json.dumps(grp.to_dict(), allow_nan=False)
        assert all(not (isinstance(v, float) and not math.isfinite(v)) for v in grp.to_dict().values())


def test_aggregate_accepts_forward_result_objects_and_arrays():
    from jusmo_scanner.backtest.metrics import forward_metrics
    o = [100, 100, 100, 100]
    fr = forward_metrics(o, [110] * 4, [95] * 4, [105] * 4, 0, 2)
    g_obj = aggregate_group([fr, fr])
    arr = GroupArrays(np.array([fr.forward_return] * 2), np.array([fr.mfe] * 2),
                      np.array([fr.mae] * 2), np.array([pack_hits(fr)] * 2))
    assert aggregate_group(arr) == g_obj
    assert g_obj.hit_up_10 == 1.0 and g_obj.hit_down_5 == 1.0 and g_obj.hit_up_20 == 0.0
    with pytest.raises(ValueError):
        aggregate_group(GroupArrays(np.zeros(2), np.zeros(3), np.zeros(2), np.zeros(2, dtype=np.int64)))


# --- config -------------------------------------------------------------------------------

def test_config_sample_quality_and_min_sample_size_defaults():
    assert CFG.backtest_sample_quality == (30, 100, 300)
    assert CFG.backtest_min_sample_size == 100
    assert ScannerConfig.__dataclass_fields__["backtest_min_sample_size"].default == 100
    o = override_config(CFG, backtest_sample_quality=[10, 20, 30], backtest_min_sample_size=50)
    assert o.backtest_sample_quality == (10, 20, 30) and o.backtest_min_sample_size == 50
    assert CFG.backtest_sample_quality == (30, 100, 300)  # base untouched


@pytest.mark.parametrize("bad", [(100, 30, 300), (30, 30, 300), (30, 100), (30, 100, 300, 500),
                                 (0, 10, 20), (30.0, 100, 300), (True, 100, 300), "abc", 5])
def test_config_rejects_invalid_sample_quality(bad):
    with pytest.raises(ValueError, match="sample_quality"):
        override_config(CFG, backtest_sample_quality=bad)


@pytest.mark.parametrize("bad", [0, -1, 1.5, True, "100"])
def test_config_rejects_invalid_min_sample_size(bad):
    with pytest.raises(ValueError, match="min_sample_size"):
        override_config(CFG, backtest_min_sample_size=bad)


def test_config_loads_custom_sample_quality(tmp_path):
    import yaml
    with open("config/scanner.yaml", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    raw["backtest"]["sample_quality"] = {"very_low_below": 5, "low_below": 6, "medium_below": 7}
    raw["backtest"]["min_sample_size"] = 9
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    c = load_config(p)
    assert c.backtest_sample_quality == (5, 6, 7) and c.backtest_min_sample_size == 9
    del raw["backtest"]["sample_quality"], raw["backtest"]["min_sample_size"]
    p.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert load_config(p).backtest_sample_quality == (30, 100, 300)
