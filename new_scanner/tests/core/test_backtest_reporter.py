from __future__ import annotations

import csv
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from jusmo_scanner.backtest import reporter
from jusmo_scanner.backtest.experiments import ExperimentOptions, run_experiment
from jusmo_scanner.backtest.metrics import EntryMode
from jusmo_scanner.config import load_config
from tests.core.test_backtest_experiments import DictProvider, fixtures
from tests import synthetic as syn

CFG = load_config("config/scanner.yaml")
BAD_CELLS = {"nan", "inf", "-inf", "none", "null", "NaN", "Infinity"}


@pytest.fixture(scope="module")
def exp(tmp_path_factory):
    d = tmp_path_factory.mktemp("rep")
    db = d / "r.db"
    frames = {**fixtures(), "R1": syn.random_frame(1, 320)}
    res = run_experiment(DictProvider(frames), CFG, ExperimentOptions(
        horizons=(1, 5, 20), sweeps=True, sweep_parameters=("vcr",), db_path=db))
    return db, res


def _read(p: Path):
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.reader(f))


def test_csv_files_named_with_experiment_id_and_complete(exp, tmp_path):
    db, res = exp
    rf = reporter.export_experiment(db, res.experiment_id, tmp_path)
    names = {p.name for p in rf.paths}
    assert all(res.experiment_id in n for n in names)
    for stem in ("signals", "results", "summary_by_signal", "summary_by_state", "summary_by_transition",
                 "summary_by_vcr", "summary_by_event_value", "summary_by_cost_distance",
                 "summary_by_location120", "summary_by_pullback", "summary_state_x_vcr",
                 "summary_state_x_cost_distance", "summary_state_x_location120",
                 "summary_event_value_x_capital_impact", "summary_pullback_depth_x_vcr",
                 "summary_structure_score_x_trigger_score", "summary_by_structure_score",
                 "summary_by_trigger_score", "summary_by_cluster_value", "summary_by_event_age",
                 "summary_by_event_count", "summary_by_capital_impact", "experiment"):
        assert any(n.startswith(stem + "_") and res.experiment_id in n for n in names), stem
    assert f"summary_{res.experiment_id}.md" in names
    with closing(sqlite3.connect(db)) as c:
        analyses = {r[0] for r in c.execute("SELECT DISTINCT analysis FROM backtest_summary")}
    n_summary = [n for n in names if n.startswith("summary_") and n.endswith(".csv")]
    assert len(n_summary) == len(analyses)


def test_csv_round_trip_no_nan_and_stable_columns(exp, tmp_path):
    db, res = exp
    reporter.export_experiment(db, res.experiment_id, tmp_path)
    with closing(sqlite3.connect(db)) as c:
        for table, stem in (("backtest_signals", "signals"), ("backtest_results", "results")):
            cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})") if r[1] != "id"]
            n = c.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            rows = _read(tmp_path / f"{stem}_{res.experiment_id}.csv")
            assert rows[0] == cols and len(rows) - 1 == n > 0
        scols = [r[1] for r in c.execute("PRAGMA table_info(backtest_summary)") if r[1] != "id"]
    assert "signal_type" in _read(tmp_path / f"results_{res.experiment_id}.csv")[0]
    summ = _read(tmp_path / f"summary_by_signal_{res.experiment_id}.csv")
    assert summ[0] == scols
    idx = {c: i for i, c in enumerate(scols)}
    assert any(r[idx["std_return"]] == "" for r in summ[1:])            # None -> empty cell
    for p in tmp_path.glob("*.csv"):                                     # CSV-level NaN guard
        for row in _read(p)[1:]:
            for cell in row:
                assert cell not in BAD_CELLS, (p.name, cell)
                if re.fullmatch(r"-?\d+\.\d+(e[+-]?\d+)?", cell):
                    float(cell)
    text = "\n".join(p.read_text(encoding="utf-8") for p in tmp_path.glob("*.csv")).lower()
    assert not re.findall(r"(?<![a-z_])(nan|inf)(?![a-z_])", text)


def test_experiment_json(exp, tmp_path):
    db, res = exp
    reporter.export_experiment(db, res.experiment_id, tmp_path)
    meta = json.loads((tmp_path / f"experiment_{res.experiment_id}.json").read_text(encoding="utf-8"))
    assert meta["experiment_id"] == res.experiment_id and meta["config_hash"] == res.metadata["config_hash"]
    assert meta["warnings_json"] == res.warnings and meta["horizons"] == [1, 5, 20]
    assert meta["config_json"]["dormant_vcr_max"] == 0.4 and meta["options_json"]["sweeps"] is True
    assert "git_commit" in meta and meta["universe_size"] == 4
    assert [v["id"] for v in meta["variants_json"]][0] == "baseline"


def test_regenerated_report_is_identical(exp, tmp_path):
    db, res = exp
    a, b = tmp_path / "a", tmp_path / "b"
    reporter.export_experiment(db, res.experiment_id, a)
    reporter.export_experiment(db, res.experiment_id, b)
    assert sorted(p.name for p in a.iterdir()) == sorted(p.name for p in b.iterdir())
    for p in a.iterdir():
        assert p.read_bytes() == (b / p.name).read_bytes(), p.name


def test_unknown_experiment_lists_available(exp, tmp_path):
    db, res = exp
    with pytest.raises(reporter.UnknownExperiment) as ei:
        reporter.export_experiment(db, "nope", tmp_path)
    assert res.experiment_id in str(ei.value) and "nope" in str(ei.value)
    assert reporter.list_experiments(tmp_path / "missing.db") == []


def test_markdown_wording_and_disclaimers(exp, tmp_path):
    db, res = exp
    md = reporter.export_experiment(db, res.experiment_id, tmp_path).markdown
    assert "Survivorship bias may exist because historical delisted securities are not included." in md
    assert "price adjustment unknown: splits/mergers may distort returns" in md
    for d in reporter.DISCLAIMERS:
        assert d in md
    body = md
    for d in reporter.DISCLAIMERS:
        body = body.replace(d, "")
    low = body.lower()
    for word in ("best", "optimal", "outperform", "recommend", "winner", "worst", "beat"):
        assert word not in low, word
    assert re.search(r"^- 20D: sample [\d,]+ \[(VERY_LOW|LOW|MEDIUM|HIGH)\], 20D median return [+-]\d", md, re.M)
    assert "total" not in low                                          # never a total across signal types
    for k in ("source_data_start:", "source_data_end:", "signal_start:", "signal_end:"):
        assert f"- {k}" in md, k
    assert "IDENTICAL_SAMPLES" in md and "vcr=0.25" in md and "(low sample)" in md   # flagged, still shown


def test_warnings_for_close_and_synthetic(tmp_path):
    from jusmo_scanner.data.csv_provider import CSVProvider
    from jusmo_scanner.backtest.sampledata import write_csv_universe
    write_csv_universe(tmp_path / "csv", 3, 350, 2)
    db = tmp_path / "w.db"
    res = run_experiment(CSVProvider(tmp_path / "csv"), CFG, ExperimentOptions(
        horizons=(1,), entry_mode=EntryMode.CLOSE, db_path=db))
    md = reporter.export_experiment(db, res.experiment_id, tmp_path / "out").markdown
    assert "data is synthetic; results are not market evidence" in md
    assert "optimistic assumption" in md and "price adjustment unknown" in md


def test_groups_are_listed_in_key_order_not_by_performance():
    meta = {"experiment_id": "x", "horizons": [20], "sample_modes": "FIRST_SIGNAL_PER_EPISODE",
            "warnings_json": [], "variants_json": [{"id": "baseline"}]}

    def row(label, ret, n=500, dim="vcr_anchor", analysis="by_vcr_anchor"):
        return {"analysis": analysis, "variant": "baseline", "sample_mode": "FIRST_SIGNAL_PER_EPISODE",
                "dim1_name": dim, "dim1": label, "dim2_name": "", "dim2": "",
                "signal_type": "BREAKOUT", "horizon": 20, "sample_count": n, "sample_quality": "HIGH",
                "low_sample": n < 100, "median_return": ret, "median_mfe": 0.1, "median_mae": -0.05, "note": None}

    rows = [row("0.4-0.5", 0.30), row("MISSING", -0.20), row("0.2-0.25", 0.01, n=12),
            row("0.25-0.3", 0.99), row("<0", 0.5)]
    md, _ = reporter.render_summary(meta, rows)
    order = re.findall(r"^- vcr_anchor (\S+):", md, re.M)
    assert order == ["<0", "0.2-0.25", "0.25-0.3", "0.4-0.5", "MISSING"]      # bucket order, not by return
    assert "vcr_anchor 0.2-0.25: sample 12 [HIGH], 20D median return +1.0%" in md and "(low sample)" in md
    assert (reporter.label_rank("above_ma240", "False") < reporter.label_rank("above_ma240", "True")
            < reporter.label_rank("above_ma240", "MISSING"))
    assert reporter.label_rank("state", "A") < reporter.label_rank("state", "B")
