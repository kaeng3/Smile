"""PykrxProvider behaviour with a fake pykrx (no network): as-of universe, concrete dates,
market-data gap accounting."""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
from contextlib import closing
from datetime import date

import pytest

from jusmo_scanner.backtest import cli_commands as cc
from jusmo_scanner.backtest import experiments as ex
from jusmo_scanner.backtest.experiments import ExperimentOptions, run_experiment
from jusmo_scanner.config import load_config
from jusmo_scanner.data.base import PriceAdjustmentMode, ShareCountBasis
from tests import synthetic as syn
from tests.pykrx_fake import FakePykrx

CFG = load_config("config/scanner.yaml")


def frames():
    out = {}
    for t, seed in (("AAA", 1), ("BBB", 2), ("CCC", 3)):
        df = syn.random_frame(seed, 320)
        df["ticker"] = t
        out[t] = df
    return out


def _parse(*argv):
    p = argparse.ArgumentParser()
    cc.add_parsers(p.add_subparsers(dest="command"))
    return p.parse_args(["backtest", "--provider", "pykrx", *argv])


def test_universe_dates_for():
    today = date(2026, 9, 20)
    assert cc.universe_dates_for(date(2022, 1, 3), date(2022, 12, 30), date(1990, 1, 1), today) == ["20220103", "20221230"]
    # RULE: no --start -> only the signal_end listing (the 1990 fetch start is a placeholder, not a listing date)
    assert cc.universe_dates_for(None, date(2022, 12, 30), date(1990, 1, 1), today) == ["20221230"]
    assert cc.universe_dates_for(None, None, date(1990, 1, 1), today) == ["20260920"]
    assert cc.universe_dates_for(date(2022, 1, 3), None, date(1990, 1, 1), today) == ["20220103", "20260920"]
    assert cc.universe_dates_for(date(2030, 1, 3), date(2031, 1, 1), date(1990, 1, 1), today) == ["20260920"]  # capped


def test_pykrx_universe_is_the_union_of_as_of_listings(monkeypatch):
    fake = FakePykrx(frames(), listings={"20220103": ["AAA", "BBB"], "20221230": ["BBB", "CCC"]}).install(monkeypatch)
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    p = PykrxProvider("19900101", "20230101", universe_dates=["20221230", "20220103", "20220103"])
    assert p.get_tickers() == ["AAA", "BBB", "CCC"]
    assert fake.list_calls == [("20220103", "ALL"), ("20221230", "ALL")]      # as-of dates, not today
    assert p.universe_basis == [{"requested": "2022-01-03", "used": "2022-01-03", "n_tickers": 2},
                                {"requested": "2022-12-30", "used": "2022-12-30", "n_tickers": 2}]
    # without dates: today's listing (documented look-ahead), recorded as such
    fake.list_calls.clear()
    q = PykrxProvider("19900101", "20230101")
    assert q.get_tickers() == ["AAA", "BBB", "CCC"] and fake.list_calls == [(None, "ALL")]
    assert q.universe_basis == [{"requested": None, "used": None, "n_tickers": 3}]


def test_universe_basis_is_recorded_and_warned(monkeypatch, tmp_path):
    fake = FakePykrx(frames(), listings={"20200601": ["AAA"], "20201231": ["AAA", "BBB"]}).install(monkeypatch)
    out = tmp_path / "out"
    args = _parse("--start", "2020-06-01", "--end", "2020-12-31", "--horizons", "1", "--output", str(out))
    assert cc.dispatch(args) == 0
    with closing(sqlite3.connect(out / "backtest.db")) as c:
        basis, warns, universe = c.execute(
            "SELECT universe_basis, warnings_json, universe_size FROM backtest_experiments").fetchone()
    assert json.loads(basis) == [{"requested": "2020-06-01", "used": "2020-06-01", "n_tickers": 1},
                                 {"requested": "2020-12-31", "used": "2020-12-31", "n_tickers": 2}]
    assert universe == 2                                                     # CCC not listed at either date
    assert len(fake.list_calls) == 2                                          # ONE get_tickers call for guard + run
    warns = json.loads(warns)
    line = ("Universe is the union of listings on 2020-06-01, 2020-12-31; securities listed after the first date "
            "or delisted before the last date may be missing or present only partially")
    assert line in warns and warns[-1] == ex.SURVIVORSHIP_WARNING == (
        "Survivorship bias may exist because historical delisted securities are not included.")
    assert warns.index(line) < len(warns) - 1
    md = next(out.glob("summary_*.md")).read_text(encoding="utf-8")
    assert line in md and "- universe_basis:" in md
    assert {c[2] for c in fake.ohlcv_calls} == {"AAA", "BBB"}


def test_none_dates_never_reach_pykrx_and_bad_ranges_refuse_before_any_network_call(monkeypatch, tmp_path):
    fake = FakePykrx(frames()).install(monkeypatch)
    from jusmo_scanner.data.pykrx_provider import EARLIEST_FETCH_DATE, PykrxProvider
    PykrxProvider().get_ohlcv("AAA")                                   # no dates at all
    start, end, ticker, adjusted = fake.ohlcv_calls[0]
    assert start == EARLIEST_FETCH_DATE == "19900101" and end == date.today().strftime("%Y%m%d")
    assert isinstance(start, str) and isinstance(end, str) and adjusted is True   # adjusted=True is explicit
    fake.ohlcv_calls.clear(); fake.cap_calls.clear()
    for argv in (["--fetch-start", "2030-01-01"], ["--start", "2022-01-01", "--fetch-start", "2023-01-01"],
                 ["--end", "2022-12-31", "--fetch-end", "2022-06-01"]):
        args = _parse("--output", str(tmp_path / "o"), *argv)
        assert cc.dispatch(args) == 1
    assert fake.list_calls == [] and fake.ohlcv_calls == [] and fake.cap_calls == []   # nothing touched the network


def test_missing_market_data_is_counted_and_surfaced(monkeypatch, tmp_path, caplog):
    fr = frames()
    gaps = {"AAA": list(fr["AAA"]["date"].iloc[100:106]), "BBB": [fr["BBB"]["date"].iloc[50]]}   # 6 rows / 1 row
    FakePykrx(fr, cap_gaps=gaps).install(monkeypatch)
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    p = PykrxProvider("19900101", "20300101")
    q0 = p.data_quality_report()
    assert (q0["tickers_with_missing_market_data"], q0["missing_market_data_rows"]) == (0, 0)
    with caplog.at_level(logging.WARNING):
        a, b, c = p.get_ohlcv("AAA"), p.get_ohlcv("BBB"), p.get_ohlcv("CCC")
    assert a["market_cap"].isna().sum() == 6 and a["free_float_shares"].isna().sum() == 6   # NaN after the join
    assert b["market_cap"].isna().sum() == 1 and c["market_cap"].isna().sum() == 0
    q1 = p.data_quality_report()
    assert (q1["tickers_with_missing_market_data"], q1["missing_market_data_rows"]) == (2, 7)
    msgs = [r.getMessage() for r in caplog.records]
    assert any("AAA: 6 of 320 rows" in m for m in msgs) and not any(m.startswith("BBB") for m in msgs)  # small gap: counted only
    # experiment level: metadata columns + warning line
    db = tmp_path / "q.db"
    res = run_experiment(p, CFG, ExperimentOptions(horizons=(1,), db_path=db, tickers=("AAA", "BBB", "CCC")))
    assert res.metadata["tickers_with_missing_market_data"] == 2 and res.metadata["missing_market_data_rows"] == 7
    line = ("market data gaps: 2 ticker(s) have 7 row(s) without market cap / share count "
            "(turnover and capital impact are missing on those bars)")
    assert line in res.warnings and res.warnings[-1] == ex.SURVIVORSHIP_WARNING
    with closing(sqlite3.connect(db)) as cx:
        assert cx.execute("SELECT tickers_with_missing_market_data, missing_market_data_rows "
                          "FROM backtest_experiments").fetchone() == (2, 7)
    clean = FakePykrx(fr).install(monkeypatch)
    q = PykrxProvider("19900101", "20300101")
    res2 = run_experiment(q, CFG, ExperimentOptions(horizons=(1,), tickers=("AAA",)))
    assert res2.metadata["tickers_with_missing_market_data"] == 0 and not any("market data gaps" in w for w in res2.warnings)
    assert clean.ohlcv_calls


def test_provider_hooks_default_to_nothing():
    from tests.core.test_backtest_experiments import DictProvider
    p = DictProvider({})
    assert p.data_quality_report() == {} and p.universe_basis is None and p.fetch_start is None
    res = run_experiment(DictProvider({"S": syn.success_frame()}), CFG, ExperimentOptions(horizons=(1,)))
    assert res.metadata["tickers_with_missing_market_data"] is None and res.metadata["universe_basis"] is None
    assert res.metadata["history_truncated"] is False


def test_history_near_fetch_start_is_flagged_possibly_truncated(monkeypatch):
    fr = frames()                                                    # data starts 2020-01-01
    FakePykrx(fr).install(monkeypatch)
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    near = PykrxProvider("20200103", "20300101")                   # first bar within 7 days of the fetch start
    res = run_experiment(near, CFG, ExperimentOptions(horizons=(1,), tickers=("AAA",)))
    assert res.metadata["history_truncated"] is True and "possibly truncated" in res.metadata["history_truncation_reason"]
    assert any(w.startswith("history truncated:") for w in res.warnings)
    full = PykrxProvider(None, "20300101")
    res2 = run_experiment(full, CFG, ExperimentOptions(horizons=(1,), tickers=("AAA",)))
    assert res2.metadata["history_truncated"] is False


def test_provider_metadata_constants_unchanged():
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    import sys, types
    pkg, stock = types.ModuleType("pykrx"), types.ModuleType("pykrx.stock")
    pkg.stock = stock
    sys.modules["pykrx"], sys.modules["pykrx.stock"] = pkg, stock
    try:
        p = PykrxProvider()
        assert (p.price_adjustment_mode, p.share_count_basis) == (PriceAdjustmentMode.ADJUSTED, ShareCountBasis.OUTSTANDING)
    finally:
        del sys.modules["pykrx"], sys.modules["pykrx.stock"]


# --- as-of universe dates are snapped to trading days (I-A) ---------------------------------------------------------

def test_weekend_and_holiday_universe_dates_step_back_and_record_requested_vs_used(monkeypatch, caplog):
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    fake = FakePykrx(frames(), listings={"20200605": ["AAA"], "20201230": ["AAA", "BBB"]},
                     holidays=["20201231"]).install(monkeypatch)
    # 2020-06-06 is a Saturday -> Friday 2020-06-05; 2020-12-31 is a (configured) holiday -> 2020-12-30
    p = PykrxProvider("19900101", "20230101", universe_dates=["20200606", "20201231"])
    with caplog.at_level(logging.WARNING):
        assert p.get_tickers() == ["AAA", "BBB"]
    assert p.universe_basis == [{"requested": "2020-06-06", "used": "2020-06-05", "n_tickers": 1},
                                {"requested": "2020-12-31", "used": "2020-12-30", "n_tickers": 2}]
    calls = [c[0] for c in fake.list_calls]
    assert calls == ["20200606", "20200605", "20201231", "20201230"]         # stepped back one calendar day at a time
    text = caplog.text
    assert "2020-06-06 is not a trading day with listings; using 2020-06-05" in text
    assert "2020-12-31 is not a trading day with listings; using 2020-12-30" in text


def test_moved_universe_dates_reach_the_experiment_warnings_and_metadata(monkeypatch, tmp_path):
    FakePykrx(frames(), listings={"20200605": ["AAA"], "20201230": ["AAA", "BBB"]},
              holidays=["20201231"]).install(monkeypatch)
    out = tmp_path / "out"
    args = _parse("--start", "2020-06-06", "--end", "2020-12-31", "--horizons", "1", "--output", str(out))
    assert cc.dispatch(args) == 0
    with closing(sqlite3.connect(out / "backtest.db")) as c:
        basis, warns = c.execute("SELECT universe_basis, warnings_json FROM backtest_experiments").fetchone()
    assert [(b["requested"], b["used"]) for b in json.loads(basis)] == [("2020-06-06", "2020-06-05"),
                                                                        ("2020-12-31", "2020-12-30")]
    warns = json.loads(warns)
    assert any("universe date 2020-06-06 was not a trading day with listings; the listing on 2020-06-05 was used" in w
               for w in warns)
    union = [w for w in warns if w.startswith("Universe is the union of listings on ")]
    assert union == ["Universe is the union of listings on 2020-06-05, 2020-12-30; securities listed after the first "
                     "date or delisted before the last date may be missing or present only partially"]   # USED dates
    assert warns[-1] == ex.SURVIVORSHIP_WARNING


def test_universe_date_empty_after_max_steps_contributes_nothing_loudly(monkeypatch, caplog, tmp_path):
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    holidays = [f"202006{d:02d}" for d in range(1, 31)]                       # the whole month is empty
    FakePykrx(frames(), holidays=holidays, listings={"20201230": ["BBB"]}).install(monkeypatch)
    p = PykrxProvider("19900101", "20230101", universe_dates=["20200610", "20201230"])
    with caplog.at_level(logging.WARNING):
        assert p.get_tickers() == ["BBB"]
    assert p.universe_basis[0] == {"requested": "2020-06-10", "used": None, "n_tickers": 0}
    assert "2020-06-10: empty listing for 10 days back; it contributes NOTHING" in caplog.text
    lines = ex.universe_warnings(p.universe_basis)
    assert any("returned an empty listing" in w and "contributes NOTHING" in w for w in lines)
    assert any(w.startswith("Universe is the listing on a single date (2020-12-30)") for w in lines)
    assert not any(w.startswith("Universe is the union") for w in lines)       # never claims both dates


def test_empty_listing_on_every_date_is_a_clear_error_not_todays_listing(monkeypatch, tmp_path, caplog):
    fake = FakePykrx(frames(), holidays=[f"2020{m:02d}{d:02d}" for m in (5, 6, 12) for d in range(1, 32)]
                     ).install(monkeypatch)
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    p = PykrxProvider("19900101", "20230101", universe_dates=["20200610", "20201231"])
    with pytest.raises(RuntimeError, match="no listing found for any universe date 2020-06-10, 2020-12-31"):
        p.get_tickers()
    assert all(c[0] is not None for c in fake.list_calls)                      # never fell back to today's listing
    args = _parse("--start", "2020-06-10", "--end", "2020-12-31", "--output", str(tmp_path / "o"))
    with caplog.at_level(logging.ERROR):
        assert cc.dispatch(args) == 1
    assert "no listing found for any universe date" in caplog.text and fake.ohlcv_calls == []


def test_no_start_uses_only_the_end_listing_with_an_explicit_warning(monkeypatch, tmp_path):
    fake = FakePykrx(frames(), listings={"20201230": ["AAA", "BBB"]}, holidays=["20201231"]).install(monkeypatch)
    out = tmp_path / "out"
    args = _parse("--end", "2020-12-31", "--horizons", "1", "--output", str(out))
    assert cc.dispatch(args) == 0
    assert [c[0] for c in fake.list_calls] == ["20201231", "20201230"]         # one date (moved back), not 1990
    with closing(sqlite3.connect(out / "backtest.db")) as c:
        basis, warns = c.execute("SELECT universe_basis, warnings_json FROM backtest_experiments").fetchone()
    assert [(b["requested"], b["used"]) for b in json.loads(basis)] == [("2020-12-31", "2020-12-30")]
    assert any(w.startswith("Universe is the listing on a single date (2020-12-30) because no start date bounded it")
               for w in json.loads(warns))


def test_universe_without_dates_is_never_silent(monkeypatch):
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    FakePykrx(frames()).install(monkeypatch)
    res = run_experiment(PykrxProvider("19900101", "20300101"), CFG, ExperimentOptions(horizons=(1,), tickers=None))
    assert any(w.startswith("Universe is today's listing (no as-of date)") for w in res.warnings)
    assert res.warnings[-1] == ex.SURVIVORSHIP_WARNING


# --- M-3 / M-5 ------------------------------------------------------------------------------------------------------------

def test_empty_market_cap_frame_counts_as_missing_market_data(monkeypatch):
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    FakePykrx(frames(), empty_cap=["AAA"]).install(monkeypatch)
    p = PykrxProvider("19900101", "20300101")
    df = p.get_ohlcv("AAA")                                                     # used to raise KeyError
    assert len(df) == 320 and df["market_cap"].isna().all() and df["free_float_shares"].isna().all()
    q = p.data_quality_report()
    assert (q["tickers_with_missing_market_data"], q["missing_market_data_rows"]) == (1, 320)
    assert (q["tickers_without_trading_value"], q["rows_without_trading_value"]) == (1, 320)   # Naver has none either
    res = run_experiment(p, CFG, ExperimentOptions(horizons=(1,), tickers=("AAA",)))
    assert res.tickers_scanned == 1 and res.metadata["missing_market_data_rows"] == 320


def test_explicit_fetch_end_is_capped_at_today():
    today = date(2026, 9, 20)
    s, e, r = cc.resolve_fetch_window(date(2022, 1, 1), date(2022, 12, 31), 5, None, date(2031, 1, 1), today)
    assert e == today
    with pytest.raises(cc.CliError, match="before --end"):
        cc.resolve_fetch_window(date(2022, 1, 1), date(2030, 12, 31), 5, None, date(2031, 1, 1), today)


# --- real pykrx 1.2.9 structure (verified live, see tests/pykrx_fake.py) ------------------------------

def test_real_structure_trading_value_comes_from_the_cap_frame_and_extra_columns_are_dropped(monkeypatch):
    from jusmo_scanner.data.base import REQUIRED_COLUMNS
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    fr = frames()
    FakePykrx(fr).install(monkeypatch)                    # adjusted OHLCV: 6 columns, NO 거래대금, with 등락률
    df = PykrxProvider("19900101", "20300101").get_ohlcv("AAA")
    assert set(df.columns) == set(REQUIRED_COLUMNS) and "등락률" not in df.columns
    assert df["trading_value"].tolist() == fr["AAA"]["trading_value"].tolist()      # KRX value, not close * volume
    # a source frame that already carries 거래대금 keeps it
    FakePykrx(fr, ohlcv_trading_value=True).install(monkeypatch)
    q = PykrxProvider("19900101", "20300101")
    assert q.get_ohlcv("AAA")["trading_value"].tolist() == fr["AAA"]["trading_value"].tolist()
    assert q.data_quality_report()["rows_without_trading_value"] == 0


def test_missing_trading_value_is_counted_and_warned(monkeypatch):
    fr = frames()
    FakePykrx(fr, cap_gaps={"AAA": list(fr["AAA"]["date"].iloc[10:14])}).install(monkeypatch)
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    p = PykrxProvider("19900101", "20300101")
    res = run_experiment(p, CFG, ExperimentOptions(horizons=(1,), tickers=("AAA", "BBB")))
    assert res.metadata["tickers_scanned"] == 2
    assert any(w.startswith("trading value missing: 1 ticker(s) have 4 row(s)") for w in res.warnings)
    assert res.warnings[-1] == ex.SURVIVORSHIP_WARNING


def test_halted_rows_are_dropped_and_counted(monkeypatch):
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    fr = frames()
    halted = list(fr["AAA"]["date"].iloc[40:43])
    FakePykrx(fr, halted={"AAA": halted}).install(monkeypatch)      # Naver: open = high = low = 0, volume 0
    p = PykrxProvider("19900101", "20300101")
    df = p.get_ohlcv("AAA")
    assert len(df) == 317 and not df["date"].isin(halted).any()
    assert (df[["open", "high", "low"]] > 0).all().all()
    assert p.data_quality_report()["halted_rows_dropped"] == 3
    res = run_experiment(p, CFG, ExperimentOptions(horizons=(1,), tickers=("AAA",)))
    assert any(w.startswith("3 halted / no-trade bar(s)") for w in res.warnings)


def test_naver_row_cap_is_detected_and_recorded_as_history_truncation(monkeypatch, tmp_path):
    from jusmo_scanner.data.pykrx_provider import NAVER_MAX_ROWS, PykrxProvider
    assert NAVER_MAX_ROWS == 3000
    fr = frames()
    monkeypatch.setattr("jusmo_scanner.data.pykrx_provider.NAVER_MAX_ROWS", 200)
    fake = FakePykrx(fr, naver_max_rows=200).install(monkeypatch)
    end = fr["AAA"]["date"].iloc[-30].strftime("%Y%m%d")           # fetch end BEFORE the last bar: cap still visible
    p = PykrxProvider("19900101", end)
    df = p.get_ohlcv("AAA")
    assert df["date"].iloc[0] == fr["AAA"]["date"].iloc[-200] and df["date"].iloc[-1] <= fr["AAA"]["date"].iloc[-30]
    rep = p.data_quality_report()
    assert rep["history_row_capped_tickers"] == 1 and rep["history_row_capped_first_date"] == df["date"].iloc[0].date().isoformat()
    db = tmp_path / "c.db"
    res = run_experiment(p, CFG, ExperimentOptions(horizons=(1,), db_path=db, tickers=("AAA",)))
    assert res.metadata["history_truncated"] is True
    assert "hit the source's cap of 200 daily rows" in res.metadata["history_truncation_reason"]
    assert any(w.startswith("history truncated:") and "cap of 200" in w for w in res.warnings)
    with closing(sqlite3.connect(db)) as cx:
        assert cx.execute("SELECT history_truncated FROM backtest_experiments").fetchone() == (1,)
    # a ticker shorter than the cap is not flagged
    q = PykrxProvider("19900101", "20300101")
    monkeypatch.setattr("jusmo_scanner.data.pykrx_provider.NAVER_MAX_ROWS", 500)
    q.get_ohlcv("BBB")
    assert q.data_quality_report()["history_row_capped_tickers"] == 0 and fake.ohlcv_calls


def test_explicit_tickers_skip_the_listing_and_are_recorded(monkeypatch, tmp_path):
    fake = FakePykrx(frames()).install(monkeypatch)
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    p = PykrxProvider("19900101", "20300101", tickers=["BBB", "AAA", "BBB"])
    assert p.get_tickers() == ["BBB", "AAA"] and fake.list_calls == []
    assert p.universe_basis == [{"requested": None, "used": None, "n_tickers": 2, "explicit": True}]
    out = tmp_path / "o"
    args = _parse("--tickers", "AAA, BBB", "--start", "2020-06-01", "--end", "2020-12-31", "--horizons", "1",
                  "--output", str(out))
    assert cc.dispatch(args) == 0 and fake.list_calls == []
    with closing(sqlite3.connect(out / "backtest.db")) as c:
        basis, warns, size = c.execute("SELECT universe_basis, warnings_json, universe_size FROM backtest_experiments").fetchone()
    assert json.loads(basis) == [{"requested": None, "used": None, "n_tickers": 2, "explicit": True}] and size == 2
    assert any(w.startswith("Universe is an explicit ticker list (2 tickers)") for w in json.loads(warns))
    assert not any("today's listing" in w for w in json.loads(warns))
    # --tickers is a pykrx option
    csv_args = argparse.ArgumentParser()
    cc.add_parsers(csv_args.add_subparsers(dest="command"))
    assert cc.dispatch(csv_args.parse_args(["backtest", "--tickers", "AAA", "--output", str(out)])) == 1


def test_empty_listing_error_names_the_krx_login_requirement(monkeypatch):
    FakePykrx(frames(), holidays=["20200601"]).install(monkeypatch)
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    p = PykrxProvider("19900101", "20300101", universe_dates=["20200601"])
    monkeypatch.setattr(p, "UNIVERSE_MAX_STEP_BACK_DAYS", 0)
    with pytest.raises(RuntimeError, match="KRX_ID"):
        p.get_tickers()
