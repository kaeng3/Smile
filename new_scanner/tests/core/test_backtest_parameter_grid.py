from __future__ import annotations

import dataclasses

import pytest

from jusmo_scanner.backtest import parameter_grid as pg
from jusmo_scanner.config import ScannerConfig, load_config, override_config

CFG = load_config("config/scanner.yaml")


def _by_param(variants):
    out: dict[str, list[pg.Variant]] = {}
    for v in variants:
        out.setdefault(v.parameter or "baseline", []).append(v)
    return out


def test_ofat_variant_list_is_exactly_as_specified():
    variants = pg.ofat_variants()
    assert variants[0].id == "baseline" and variants[0].overrides == {}
    by = _by_param(variants)
    assert {k: len(v) for k, v in by.items()} == {
        "baseline": 1, "event_value": 5, "value_ratio": 5, "turnover": 5, "vcr": 6,
        "cost_tolerance": 5, "event_low_atr": 5, "range10": 5, "pullback": 6}
    assert len(variants) == 43 and len({v.id for v in variants}) == 43
    assert [v.id for v in by["event_value"]] == [
        f"event_value={n}" for n in (30_000_000_000, 50_000_000_000, 70_000_000_000,
                                     100_000_000_000, 150_000_000_000)]
    assert [v.id for v in by["value_ratio"]] == [f"value_ratio={x}" for x in (1.5, 2, 3, 4, 5)]
    assert [v.id for v in by["turnover"]] == [f"turnover={x}" for x in (0.1, 0.2, 0.3, 0.4, 0.5)]
    assert [v.id for v in by["vcr"]] == [f"vcr={x}" for x in (0.2, 0.25, 0.3, 0.35, 0.4, 0.5)]
    assert [v.id for v in by["cost_tolerance"]] == [f"cost_tolerance={x}%" for x in (2, 3, 5, 7, 10)]
    assert [v.id for v in by["event_low_atr"]] == [f"event_low_atr={x}" for x in (0, 0.25, 0.5, 0.75, 1)]
    assert [v.id for v in by["range10"]] == [f"range10={x}" for x in (0.08, 0.1, 0.12, 0.15, 0.2)]
    assert [v.id for v in by["pullback"]] == [
        "pullback=-3%~-8%", "pullback=-3%~-10%", "pullback=-3%~-12%",
        "pullback=-5%~-10%", "pullback=-5%~-12%", "pullback=-5%~-15%"]


def test_ofat_variants_map_to_the_specified_config_fields():
    by = _by_param(pg.ofat_variants())
    fields = {"event_value": "core_event_trading_value", "value_ratio": "strong_event_value_ratio_min",
              "turnover": "strong_event_turnover_min", "vcr": "dormant_vcr_max",
              "cost_tolerance": "cost_hold_tolerance_pct", "event_low_atr": "atr_tolerance_event_low",
              "range10": "dormant_range10_max"}
    for param, field in fields.items():
        for v in by[param]:
            assert list(v.overrides) == [field], (param, v.id)     # exactly ONE field changed
    assert [v.overrides["core_event_trading_value"] for v in by["event_value"]] == [
        30e9, 50e9, 70e9, 100e9, 150e9]
    assert [v.overrides["cost_hold_tolerance_pct"] for v in by["cost_tolerance"]] == [0.02, 0.03, 0.05, 0.07, 0.10]
    assert [v.overrides["dormant_range10_max"] for v in by["range10"]] == [0.08, 0.10, 0.12, 0.15, 0.20]


def test_pullback_bands_min_is_the_deeper_bound():
    bands = _by_param(pg.ofat_variants())["pullback"]
    got = [(v.overrides["pullback_drawdown_min"], v.overrides["pullback_drawdown_max"]) for v in bands]
    assert got == [(-0.08, -0.03), (-0.10, -0.03), (-0.12, -0.03), (-0.10, -0.05), (-0.12, -0.05), (-0.15, -0.05)]
    for v in bands:
        assert set(v.overrides) == {"pullback_drawdown_min", "pullback_drawdown_max"}
        assert v.overrides["pullback_drawdown_min"] < v.overrides["pullback_drawdown_max"] < 0
        pg.apply_variant(CFG, v)  # yields a valid config


def test_parameter_grid_does_not_mutate_base_config():
    before = dataclasses.asdict(CFG)
    ident = id(CFG)
    for v in pg.ofat_variants():
        cfg_v = pg.apply_variant(CFG, v)
        assert isinstance(cfg_v, ScannerConfig)
        if v.overrides:
            assert cfg_v is not CFG
            after = dataclasses.asdict(cfg_v)
            changed = {f for f in before if after[f] != before[f]}
            assert changed <= set(v.overrides)              # nothing else moved
    list(pg.cartesian_variants(["vcr", "range10"]))
    assert dataclasses.asdict(CFG) == before and id(CFG) == ident
    with pytest.raises(dataclasses.FrozenInstanceError):
        CFG.dormant_vcr_max = 0.9  # type: ignore[misc]


def test_baseline_variant_is_the_unchanged_base_config():
    assert pg.apply_variant(CFG, pg.baseline_variant()) is CFG


def test_ofat_subset_and_unknown_parameter():
    assert [v.id for v in pg.ofat_variants(["vcr"])][:2] == ["baseline", "vcr=0.2"]
    assert len(pg.ofat_variants(["vcr", "range10"])) == 1 + 6 + 5
    with pytest.raises(ValueError, match="unknown sweep parameter"):
        pg.ofat_variants(["nope"])


def test_cartesian_refuses_above_max_combos_and_reports_count():
    total = 5 * 5 * 5 * 6 * 5 * 5 * 5 * 6
    assert pg.cartesian_combo_count() == total
    with pytest.raises(ValueError, match=str(total)):
        pg.cartesian_variants()                                   # default max_combos
    with pytest.raises(ValueError, match="max_combos"):
        pg.cartesian_variants(["vcr", "range10"], max_combos=10)   # 30 > 10
    combos = list(pg.cartesian_variants(["vcr", "range10"], max_combos=30))
    assert len(combos) == 30 and len({c.id for c in combos}) == 30
    assert combos[0].id == "vcr=0.2|range10=0.08"
    assert combos[0].overrides == {"dormant_vcr_max": 0.2, "dormant_range10_max": 0.08}
    # explicit override; generator stays lazy (nothing materialised)
    gen = pg.cartesian_variants(["vcr", "range10"], max_combos=1, allow_exceed=True)
    assert next(iter(gen)).id == "vcr=0.2|range10=0.08"


def test_cartesian_count_is_logged_before_generation(caplog):
    with caplog.at_level("INFO", logger=pg.logger.name):
        with pytest.raises(ValueError):
            pg.cartesian_variants(max_combos=10)
    assert any("combinations" in r.message for r in caplog.records)


def test_variants_are_valid_configs_for_every_override():
    for v in pg.ofat_variants():
        override_config(CFG, **v.overrides)
