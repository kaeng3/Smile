"""Final-review fixes: sweep estimate/guard, turnover share-basis annotations, docstrings, uint64 merge."""
from __future__ import annotations

import argparse
import logging
import sqlite3
from array import array
from contextlib import closing

import pytest

from jusmo_scanner.backtest import analysis, cli_commands as cc, experiments as ex, sampledata
from jusmo_scanner.backtest.analysis import SummaryAccumulator, select_analyses
from jusmo_scanner.backtest.engine import SampleMode
from jusmo_scanner.backtest.experiments import ExperimentOptions, run_experiment
from jusmo_scanner.backtest.metrics import EntryMode
from jusmo_scanner.config import load_config
from jusmo_scanner.data.base import PriceAdjustmentMode, ShareCountBasis
from tests import synthetic as syn
from tests.core.test_backtest_experiments import DictProvider, fixtures

CFG = load_config("config/scanner.yaml")


def test_sweep_estimate_math():
    # time: t_base + (variants - 1) * (a + b * horizons), fitted to the measured 31-ticker runs
    assert cc.estimate_run(31, 1)[0] == pytest.approx(22.8, rel=0.02)                  # baseline 22.8 s
    assert cc.estimate_run(31, 43, 6)[0] == pytest.approx(154.9, rel=0.02)            # OFAT, default horizons
    assert cc.estimate_run(31, 43, 2)[0] == pytest.approx(80.2, rel=0.02)             # OFAT, --horizons 5,20
    assert cc.estimate_run(31, 43, 2)[0] < cc.estimate_run(31, 43, 6)[0]
    sec, mb = cc.estimate_run(1, 1)
    assert mb == pytest.approx(0.67)
    sec, mb = cc.estimate_run(1, 43)
    assert mb == pytest.approx(5.4)
    sec, mb = cc.estimate_run(2500, 43)
    assert mb / 1000 == pytest.approx(13.5) and sec == pytest.approx(2500 * 5.0, rel=0.02)
    assert cc.estimate_run(100, 43, 6)[1] == cc.estimate_run(100, 43, 2)[1]           # memory model unchanged
    assert cc.estimate_run(2500, 1)[1] / 1000 == pytest.approx(1.675)      # baseline stays far below the guard
    assert cc.DEFAULT_MAX_SWEEP_MEMORY_GB == 8.0


@pytest.fixture(scope="module")
def csv_small(tmp_path_factory):
    d = tmp_path_factory.mktemp("csv_small")
    sampledata.write_csv_universe(d, 2, 350, 3)
    return d


def _run(csv_dir, out, *argv):
    p = argparse.ArgumentParser()
    cc.add_parsers(p.add_subparsers(dest="command"))
    args = p.parse_args(["backtest", "--csv-dir", str(csv_dir), "--output", str(out), "--horizons", "5", *argv])
    return cc.dispatch(args)


def test_sweep_guard_refuses_large_estimate_and_allow_flag_overrides(csv_small, tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        assert _run(csv_small, tmp_path / "a", "--sweep", "ofat", "--max-sweep-memory-gb", "0.005") == 1
    msg = " ".join(r.getMessage() for r in caplog.records)
    err = next(r.getMessage() for r in caplog.records if "exceeds the" in r.getMessage())
    assert "estimated peak memory" in err and "--allow-large-sweep" in err
    for hint in ("--sweep-params", "fewer tickers", "estimate"):
        assert hint in err
    for not_in_estimate in ("--signal", "--horizons", "--mode"):      # only advertise what lowers the estimate
        assert not_in_estimate not in err
    assert "sweep is heavy: 43 variants x 2 tickers" in msg and "GB" in msg
    assert not (tmp_path / "a" / "backtest.db").exists()                  # refused before any work
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert _run(csv_small, tmp_path / "b", "--sweep", "ofat", "--sweep-params", "vcr",
                    "--max-sweep-memory-gb", "0.005", "--allow-large-sweep") == 0
    assert (tmp_path / "b" / "backtest.db").exists() and "sweep is heavy: 7 variants x 2 tickers" in caplog.text
    assert _run(csv_small, tmp_path / "c", "--sweep", "ofat", "--sweep-params", "nope") == 1


def test_default_guard_threshold_allows_normal_sweeps(csv_small, tmp_path):
    assert _run(csv_small, tmp_path / "d", "--sweep", "ofat", "--sweep-params", "range10") == 0


def test_turnover_artifacts_carry_the_share_count_basis(tmp_path):
    db = tmp_path / "t.db"
    frames = {**fixtures(), "R1": syn.random_frame(1, 320)}
    res = run_experiment(DictProvider(frames, PriceAdjustmentMode.ADJUSTED, ShareCountBasis.OUTSTANDING), CFG,
                         ExperimentOptions(horizons=(1,), sweeps=True, sweep_parameters=("turnover", "vcr"), db_path=db))
    tag = "share_count_basis=OUTSTANDING"
    turnover_rows = [r for r in res.summary_rows if r["analysis_name"] == "by_turnover"]
    assert turnover_rows and all(tag in (r["note"] or "") for r in turnover_rows)
    variant_rows = [r for r in res.summary_rows if r["variant"].startswith("turnover=")]
    assert variant_rows and all(tag in (r["note"] or "") for r in variant_rows)
    others = [r for r in res.summary_rows
              if r["analysis_name"] != "by_turnover" and not r["variant"].startswith("turnover=")]
    assert others and not any(tag in (r["note"] or "") for r in others)
    with closing(sqlite3.connect(db)) as c:
        assert c.execute("SELECT DISTINCT share_count_basis FROM backtest_signals").fetchall() == [("OUTSTANDING",)]
        assert c.execute("SELECT COUNT(*) FROM backtest_summary WHERE analysis='by_turnover' AND note LIKE ?",
                         (f"%{tag}%",)).fetchone()[0] == len(turnover_rows)
    unknown = run_experiment(DictProvider(fixtures()), CFG, ExperimentOptions(horizons=(1,)))
    assert any("share_count_basis=UNKNOWN" in (r["note"] or "")
               for r in unknown.summary_rows if r["analysis_name"] == "by_turnover")


def test_stale_docstrings_removed():
    assert "date filter" not in ex.__doc__
    assert "schema v3" not in ex.run_experiment.__doc__ and "SCHEMA_VERSION" in ex.run_experiment.__doc__


def test_overlapping_samples_denominator_is_documented_and_horizon_independent():
    assert "not per horizon" in analysis.__doc__ and "denominator" in analysis.__doc__
    res = run_experiment(DictProvider({"S": syn.success_frame()}), CFG, ExperimentOptions(horizons=(1, 5, 20)))
    rows = [r for r in res.summary_rows if r["analysis_name"] == "by_signal_type"
            and r["signal_type"] == "EVENT" and r["sample_mode"] == "FIRST_SIGNAL_PER_EPISODE"]
    notes = {r["horizon"]: [p for p in r["note"].split("; ") if p.startswith("OVERLAPPING")] for r in rows}
    assert len(notes) == 3 and len({tuple(v) for v in notes.values()}) == 1 and notes[1] == ["OVERLAPPING_SAMPLES(100%)"]


def test_accumulator_merge_uses_wide_index_arithmetic():
    a = SummaryAccumulator(select_analyses(["by_signal_type"]), EntryMode.NEXT_OPEN, (SampleMode.ALL_SIGNALS,))
    b = a.empty_like()
    key = ("by_signal_type", "baseline", "ALL_SIGNALS", "X", "", "X", 1)
    b._groups[key] = array("I", [0xFFFFFFFF])
    a._ret.extend([0.0] * 5)
    with pytest.raises(OverflowError, match="2\\*\\*32"):
        a.merge(b)
    ok = a.empty_like()
    ok._ret.extend([0.1, 0.2])
    ok._mfe.extend([0.1, 0.2])
    ok._mae.extend([-0.1, -0.2])
    ok._hits.extend([0, 0])
    ok._groups[key] = array("I", [0, 1])
    a2 = a.empty_like()
    for arr in (a2._ret, a2._mfe, a2._mae):
        arr.extend([0.0] * 3)
    a2._hits.extend([0] * 3)
    a2.merge(ok)
    assert list(a2._groups[key]) == [3, 4]


def test_adjusted_warning_text_and_position():
    w = ex.build_warnings(PriceAdjustmentMode.ADJUSTED, ShareCountBasis.FREE_FLOAT, EntryMode.NEXT_OPEN)
    assert w == ["volume/trading value/share counts are not restated for corporate actions", ex.SURVIVORSHIP_WARNING]
    assert ex.build_warnings(PriceAdjustmentMode.UNKNOWN, ShareCountBasis.FREE_FLOAT, EntryMode.NEXT_OPEN)[0] == \
        ex.UNKNOWN_ADJUSTMENT_WARNING
