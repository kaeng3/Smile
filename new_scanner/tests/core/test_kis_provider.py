"""KisProvider tests: fake transport only (no network). Live checks need KIS_LIVE_TEST=1 and are skipped by default."""
from __future__ import annotations

import gzip
import json
import logging
import os
import subprocess
import traceback
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from jusmo_scanner.data import kis_provider as kp
from jusmo_scanner.data.base import PriceAdjustmentMode, ShareCountBasis
from jusmo_scanner.data.kis_provider import (KisApiError, KisClient, KisProvider, RateLimiter, Redactor,
                                             TokenManager, fetch_daily_rows, parse_master, rows_to_frame)
from tests.kis_fake import (FAKE_ACCOUNT, FAKE_KEY, FAKE_SECRET, FAKE_TOKEN, FakeClock, FakeKisTransport,
                            fixed_now, make_bars)

REPO = Path(__file__).resolve().parents[2]
BASE = "https://fake.example"


def make_provider(tmp_path, transport, **kw):
    clock = kw.pop("clock", None) or FakeClock()
    kw.setdefault("start_date", "20230101")
    kw.setdefault("end_date", "20240315")
    now = kw.pop("now", None) or fixed_now()
    return KisProvider(app_key=FAKE_KEY, app_secret=FAKE_SECRET, transport=transport, cache_dir=tmp_path,
                       now=now, clock=clock, sleep=clock.sleep, **kw), clock


def make_client(transport, clock=None, **kw):
    clock = clock or FakeClock()
    red = Redactor(FAKE_KEY, FAKE_SECRET)
    tm = TokenManager(FAKE_KEY, FAKE_SECRET, transport, BASE, red, clock=lambda: 1_000_000.0)
    tm.get()                                   # token first, so scripted failures hit the quotation calls
    return KisClient(FAKE_KEY, FAKE_SECRET, transport, tm, red, BASE, clock=clock, sleep=clock.sleep, **kw), clock, tm


# --- token manager -------------------------------------------------------------------------------------------------

def test_token_reused_in_memory():
    t = FakeKisTransport()
    tm = TokenManager(FAKE_KEY, FAKE_SECRET, t, BASE, Redactor(FAKE_KEY, FAKE_SECRET), clock=lambda: 1000.0)
    assert tm.get() == tm.get() == FAKE_TOKEN
    assert t.token_requests == 1


def test_token_expiry_reissues():
    t = FakeKisTransport(expires_in=3600)
    now = [1000.0]
    tm = TokenManager(FAKE_KEY, FAKE_SECRET, t, BASE, Redactor(FAKE_KEY), clock=lambda: now[0])
    tm.get()
    now[0] += 3600 - 400                       # still valid (more than the 300 s margin left)
    tm.get()
    assert t.token_requests == 1
    now[0] += 200                              # inside the margin -> reissue
    tm.get()
    assert t.token_requests == 2


def test_token_file_cache_reused_and_bound_to_key(tmp_path):
    path = tmp_path / ".kis_token.json"
    t1 = FakeKisTransport()
    TokenManager(FAKE_KEY, FAKE_SECRET, t1, BASE, Redactor(), path, clock=lambda: 1000.0).get()
    t2 = FakeKisTransport()
    assert TokenManager(FAKE_KEY, FAKE_SECRET, t2, BASE, Redactor(), path, clock=lambda: 2000.0).get() == FAKE_TOKEN
    assert t2.token_requests == 0
    TokenManager("OTHER-KEY-0000", FAKE_SECRET, t2, BASE, Redactor(), path, clock=lambda: 2000.0).get()
    assert t2.token_requests == 1              # another app key never reuses the file


def test_token_error_is_sanitised():
    t = FakeKisTransport()
    t.token_error = (403, {"error_code": "EGW00133",
                           "error_description": f"echo {FAKE_KEY} and {FAKE_SECRET}"})
    tm = TokenManager(FAKE_KEY, FAKE_SECRET, t, BASE, Redactor(FAKE_KEY, FAKE_SECRET))
    with pytest.raises(KisApiError) as ei:
        tm.get()
    text = str(ei.value) + repr(ei.value)
    assert "EGW00133" in text and FAKE_KEY not in text and FAKE_SECRET not in text


def test_token_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    t = FakeKisTransport()
    TokenManager(FAKE_KEY, FAKE_SECRET, t, BASE, Redactor()).get()
    assert "KIS authentication successful" in caplog.text
    assert FAKE_TOKEN not in caplog.text


# --- rate limiter / retry ------------------------------------------------------------------------------------------

def test_rate_limiter_spacing_fake_clock():
    c = FakeClock()
    rl = RateLimiter(5.0, c, c.sleep)
    t0 = c.t
    for _ in range(10):
        rl.acquire()
    assert c.t - t0 == pytest.approx(1.8)      # 9 gaps of 0.2 s
    c.t += 5
    n = len(c.sleeps)
    rl.acquire()
    assert len(c.sleeps) == n                  # idle time -> no wait


def test_rate_limiter_rejects_bad_rate():
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_retry_transient_then_success():
    t = FakeKisTransport({"005930": make_bars(5)})
    client, clock, _ = make_client(t)
    t.script = [(500, {"rt_cd": "1", "msg_cd": "EGW00316", "msg1": "retry"}),
                (200, {"rt_cd": "1", "msg_cd": "OPSQ1002", "msg1": "SESSION FULL"}),
                (200, {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "rate"}),
                (429, None)]
    client_rows, _, _ = fetch_daily_rows(client, "005930", pd.Timestamp("2024-01-01").date(),
                                         pd.Timestamp("2024-03-15").date(), True)
    assert len(client_rows) == 5 and client.retries == 4
    backoffs = [s for s in clock.sleeps if s >= 0.5]
    assert backoffs[0] == 0.5 and backoffs[1] == 1.0 and backoffs[2] >= 2.0     # exponential
    assert clock.sleeps  # slept, on the fake clock


def test_egw00201_waits_at_least_one_second():
    t = FakeKisTransport({"005930": make_bars(3)})
    client, clock, _ = make_client(t, backoff_base=0.1)
    t.script = [(200, {"rt_cd": "1", "msg_cd": "EGW00201", "msg1": "rate"})]
    fetch_daily_rows(client, "005930", pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-03-15").date(), True)
    assert max(clock.sleeps) >= 1.0


def test_retries_exhausted_raises_sanitised():
    t = FakeKisTransport({"005930": make_bars(3)})
    client, _, _ = make_client(t, max_retries=2)
    t.script = [(500, {"rt_cd": "1", "msg_cd": "EGW00316", "msg1": f"boom {FAKE_KEY}"})] * 5
    with pytest.raises(KisApiError) as ei:
        client.get(kp.DAILY_PATH, kp.DAILY_TR_ID, {"FID_INPUT_ISCD": "005930", "FID_INPUT_DATE_1": "20240101",
                                                    "FID_INPUT_DATE_2": "20240315"})
    assert ei.value.code == "EGW00316" and FAKE_KEY not in str(ei.value) and ei.value.__cause__ is None
    assert len(t.daily_calls()) == 3           # 1 + 2 retries


def test_non_transient_error_not_retried():
    t = FakeKisTransport({"005930": make_bars(3)})
    client, _, _ = make_client(t)
    t.script = [(200, {"rt_cd": "1", "msg_cd": "OPSQ0002", "msg1": "bad tr_id"})]
    with pytest.raises(KisApiError) as ei:
        client.get(kp.DAILY_PATH, kp.DAILY_TR_ID, {})
    assert ei.value.code == "OPSQ0002" and client.retries == 0


def test_expired_token_invalidated_and_retried_once():
    t = FakeKisTransport({"005930": make_bars(3)})
    client, _, tm = make_client(t)
    assert tm.issued_count == 1
    t.script = [(401, {"rt_cd": "1", "msg_cd": "EGW00123", "msg1": "expired"})]
    client.get(kp.DAILY_PATH, kp.DAILY_TR_ID, {"FID_INPUT_ISCD": "005930", "FID_INPUT_DATE_1": "20240101",
                                                "FID_INPUT_DATE_2": "20240315"})
    assert tm.issued_count == 2                # invalidated -> a fresh token was requested


def test_network_error_retried_then_sanitised():
    t = FakeKisTransport({"005930": make_bars(3)})
    client, _, _ = make_client(t, max_retries=1)
    t.script = [KisApiError("NETWORK_ERROR", "ConnectTimeout")] * 3
    with pytest.raises(KisApiError) as ei:
        client.get(kp.DAILY_PATH, kp.DAILY_TR_ID, {})
    assert ei.value.code == "NETWORK_ERROR"


# --- pagination / frame --------------------------------------------------------------------------------------------

def test_pagination_stitches_dedupes_sorts():
    bars = make_bars(250)
    t = FakeKisTransport({"005930": bars})
    client, _, _ = make_client(t)
    rows, snap, n = fetch_daily_rows(client, "005930", pd.Timestamp("2020-01-01").date(),
                                     pd.Timestamp("2024-03-15").date(), True)
    assert n == 3 and len(rows) == 250 and snap["lstn_stcn"] == "1000000"
    rows += rows[:10]                                        # duplicates are removed by the frame builder
    df = rows_to_frame(rows)
    assert len(df) == 250 and df["date"].is_monotonic_increasing and not df["date"].duplicated().any()
    assert df["close"].iloc[0] == bars[0]["close"] and df["trading_value"].iloc[-1] == bars[-1]["tv"]


def test_pagination_respects_start_bound_and_exact_multiple():
    bars = make_bars(200)
    t = FakeKisTransport({"005930": bars})
    client, _, _ = make_client(t)
    start = pd.Timestamp(bars[50]["date"]).date()
    rows, _, _ = fetch_daily_rows(client, "005930", start, pd.Timestamp("2024-03-15").date(), True)
    assert len(rows) == 150
    # exactly 100 rows: a second (empty) request ends the loop
    t2 = FakeKisTransport({"005930": make_bars(100)})
    c2, _, _ = make_client(t2)
    rows, _, n = fetch_daily_rows(c2, "005930", pd.Timestamp("2000-01-01").date(), pd.Timestamp("2024-03-15").date(), True)
    assert len(rows) == 100 and n == 2


def test_adjusted_flag_sent():
    t = FakeKisTransport({"005930": make_bars(3)})
    client, _, _ = make_client(t)
    for adj, expect in ((True, "0"), (False, "1")):
        fetch_daily_rows(client, "005930", pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-03-15").date(), adj)
        assert t.daily_calls()[-1]["params"]["FID_ORG_ADJ_PRC"] == expect


def test_account_number_never_sent():
    t = FakeKisTransport({"005930": make_bars(3)})
    client, _, _ = make_client(t)
    fetch_daily_rows(client, "005930", pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-03-15").date(), True)
    assert FAKE_ACCOUNT not in json.dumps(t.calls)


# --- provider ---------------------------------------------------------------------------------------------------------

def test_provider_frame_shape_and_real_trading_value(tmp_path):
    bars = make_bars(30)
    p, _ = make_provider(tmp_path, FakeKisTransport({"005930": bars}))
    df = p.get_ohlcv("005930")
    assert list(df.columns)[:2] == ["date", "ticker"] and {"market_cap", "free_float_shares"} <= set(df.columns)
    assert df["date"].is_monotonic_increasing and len(df) == 30
    np.testing.assert_allclose(df["trading_value"], [b["tv"] for b in bars])       # REAL value, not close*volume
    assert not np.allclose(df["trading_value"], df["close"] * df["volume"])
    assert p.data_quality_report()["rows_without_trading_value"] == 0


def test_zero_trading_value_becomes_nan_and_is_counted(tmp_path):
    bars = make_bars(10)
    bars[3]["tv"] = 0
    bars[4]["tv"] = 0
    p, _ = make_provider(tmp_path, FakeKisTransport({"005930": bars}))
    df = p.get_ohlcv("005930")
    assert df["trading_value"].isna().sum() == 2
    rep = p.data_quality_report()
    assert rep["tickers_without_trading_value"] == 1 and rep["rows_without_trading_value"] == 2


def test_halted_rows_dropped(tmp_path):
    bars = make_bars(10)
    bars[5]["volume"], bars[5]["tv"] = 0, 0
    p, _ = make_provider(tmp_path, FakeKisTransport({"005930": bars}))
    df = p.get_ohlcv("005930")
    assert len(df) == 9 and p.data_quality_report()["halted_rows_dropped"] == 1


def test_current_snapshot_stays_in_metadata_and_preserves_units(tmp_path):
    bars = make_bars(10)
    t = FakeKisTransport({"005930": bars}, shares=2_000_000)
    p, _ = make_provider(tmp_path, t)
    df = p.get_ohlcv("005930")
    assert df[["market_cap", "free_float_shares"]].isna().all().all()
    _, meta_path = p._cache_paths("005930")
    snapshot = json.loads(meta_path.read_text())["snapshot"]
    assert snapshot["listed_shares"] == 2_000_000
    assert "as_of" not in snapshot and snapshot["observed_at"].startswith("2024-03-15")
    expected = int(bars[-1]["close"] * 2_000_000 / 1e8) * 100_000_000        # hts_avls is 억원
    assert snapshot["market_cap_won"] == expected
    rep = p.data_quality_report()
    assert rep["tickers_with_missing_market_data"] == 1 and rep["missing_market_data_rows"] == 10


def test_metadata(tmp_path):
    t = FakeKisTransport({"005930": make_bars(5)})
    p, _ = make_provider(tmp_path, t, tickers=["005930"])
    assert p.price_adjustment_mode is PriceAdjustmentMode.ADJUSTED
    assert p.share_count_basis is ShareCountBasis.OUTSTANDING
    assert not p.is_synthetic and p.fetch_start.isoformat() == "2023-01-01"
    assert p.get_tickers() == ["005930"]
    assert p.universe_basis[0]["explicit"] and p.universe_basis[0]["survivorship_bias_possible"]
    raw, _ = make_provider(tmp_path / "raw", t, adjusted=False)
    assert raw.price_adjustment_mode is PriceAdjustmentMode.RAW


def test_price_volume_pass_through_unchanged(tmp_path):
    bars = make_bars(5)
    p, _ = make_provider(tmp_path, FakeKisTransport({"005930": bars}))
    df = p.get_ohlcv("005930")
    assert df["open"].tolist() == [b["open"] for b in bars] and df["volume"].tolist() == [b["volume"] for b in bars]


# --- cache ---------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("fmt", ["parquet", "csv.gz"])
def test_cache_round_trip_and_second_run_offline(tmp_path, fmt):
    if fmt == "parquet":
        pytest.importorskip("pyarrow")
    t = FakeKisTransport({"005930": make_bars(30)})
    p, _ = make_provider(tmp_path, t, cache_format=fmt)
    first = p.get_ohlcv("005930")
    assert (tmp_path / "daily" / f"005930.{fmt}").is_file() and (tmp_path / "daily" / "005930.meta.json").is_file()
    n = len(t.daily_calls())
    p2, _ = make_provider(tmp_path, t, cache_format=fmt)
    second = p2.get_ohlcv("005930")
    assert len(t.daily_calls()) == n and p2.data_quality_report()["cache_hits"] == 1     # no request at all
    pd.testing.assert_frame_equal(first, second)


def test_csv_gz_cache_is_gzip(tmp_path):
    p, _ = make_provider(tmp_path, FakeKisTransport({"005930": make_bars(5)}), cache_format="csv.gz")
    p.get_ohlcv("005930")
    assert gzip.decompress((tmp_path / "daily" / "005930.csv.gz").read_bytes()).startswith(b"date,")


def test_incremental_append_uses_one_request(tmp_path):
    full = make_bars(125, end="2024-03-15")                         # the same series, 5 bars later
    old = full[:120]
    assert old[-1]["date"] == "20240308"
    t = FakeKisTransport({"005930": old})
    p, _ = make_provider(tmp_path, t, end_date="20240308", now=fixed_now(day="2024-03-08"))
    p.get_ohlcv("005930")
    t.bars["005930"] = full
    n = len(t.daily_calls())
    p2, _ = make_provider(tmp_path, t)
    df = p2.get_ohlcv("005930")
    assert len(t.daily_calls()) - n == 1 and len(df) == 125
    assert df["date"].max() == pd.Timestamp("2024-03-15") and not df["date"].duplicated().any()
    rep = p2.data_quality_report()
    assert rep["cache_incremental_fetches"] == 1 and rep["cache_full_fetches"] == 0


def test_restated_history_triggers_full_refetch(tmp_path):
    new = make_bars(125, end="2024-03-15")
    t = FakeKisTransport({"005930": [dict(b) for b in new[:120]]})
    p, _ = make_provider(tmp_path, t, end_date="20240308", now=fixed_now(day="2024-03-08"))
    p.get_ohlcv("005930")
    for b in new:                                                    # a split restated every old price
        b["close"], b["open"], b["high"], b["low"] = (b["close"] / 2, b["open"] / 2, b["high"] / 2, b["low"] / 2)
    t.bars["005930"] = new
    p2, _ = make_provider(tmp_path, t)
    df = p2.get_ohlcv("005930")
    assert p2.data_quality_report()["cache_restatement_refetches"] == 1
    assert df["close"].iloc[0] == new[0]["close"]                    # whole history replaced, not mixed


def test_refresh_flag_refetches_and_adjustment_change_invalidates(tmp_path):
    t = FakeKisTransport({"005930": make_bars(30)})
    make_provider(tmp_path, t)[0].get_ohlcv("005930")
    n = len(t.daily_calls())
    p, _ = make_provider(tmp_path, t, refresh=True)
    p.get_ohlcv("005930")
    p.get_ohlcv("005930")                                             # refresh applies once per ticker
    assert len(t.daily_calls()) - n == 1 and p.data_quality_report()["cache_full_fetches"] == 1
    n = len(t.daily_calls())
    make_provider(tmp_path, t, adjusted=False)[0].get_ohlcv("005930")   # cached ADJUSTED bars are not RAW bars
    assert len(t.daily_calls()) - n == 1


def test_earlier_start_than_cached_refetches(tmp_path):
    t = FakeKisTransport({"005930": make_bars(200)})
    make_provider(tmp_path, t, start_date="20240101")[0].get_ohlcv("005930")
    n = len(t.daily_calls())
    p, _ = make_provider(tmp_path, t, start_date="20230101")
    df = p.get_ohlcv("005930")
    assert len(t.daily_calls()) > n and df["date"].min() < pd.Timestamp("2024-01-01")


def test_partial_bar_today_not_cached_before_close(tmp_path):
    bars = make_bars(10, end="2024-03-15")
    t = FakeKisTransport({"005930": bars})
    p, _ = make_provider(tmp_path, t)
    p._now = fixed_now(hour=10)                                      # market still open on 2024-03-15
    df = p.get_ohlcv("005930")
    assert df["date"].max() == pd.Timestamp("2024-03-14")


def test_atomic_write_keeps_old_file_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "x.bin"
    target.write_bytes(b"old")

    def boom(*a, **k):
        raise OSError("disk")
    monkeypatch.setattr(kp.os, "replace", boom)
    with pytest.raises(OSError):
        kp._atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"old" and [p.name for p in tmp_path.iterdir()] == ["x.bin"]


def test_corrupt_cache_is_refetched(tmp_path):
    t = FakeKisTransport({"005930": make_bars(30)})
    p, _ = make_provider(tmp_path, t, cache_format="csv.gz")
    p.get_ohlcv("005930")
    (tmp_path / "daily" / "005930.csv.gz").write_bytes(b"garbage")
    n = len(t.daily_calls())
    df = make_provider(tmp_path, t, cache_format="csv.gz")[0].get_ohlcv("005930")
    assert len(df) == 30 and len(t.daily_calls()) > n


# --- universe / master ---------------------------------------------------------------------------------------------------

def master_line(market: str, ticker: str, name: str, group: str = "ST", listing: str = "20190305",
                shares_k: int = 97830, halted: str = "N") -> bytes:
    fields = {n: b"0" * w for n, w in kp._TAIL_FIELDS}
    fields["halted"] = halted.encode()
    fields["listing_date"] = listing.encode()
    fields["listed_shares_k"] = f"{shares_k:015d}".encode()
    body = b"".join(fields[n].ljust(w) for n, w in kp._TAIL_FIELDS) + b"0" * kp._AFTER_TAIL[market]
    tail = group.encode() + b"X" * (kp._RECORD_TAIL_LEN[market] - 2 - len(body)) + body
    assert len(tail) == kp._RECORD_TAIL_LEN[market]
    return ticker.encode().ljust(9) + b"KR7" + ticker.encode() + b"003" + name.encode("cp949") + tail


def test_parse_master_tiny_fake_file():
    raw = b"\r\n".join([master_line("KOSDAQ", "247540", "에코프로비엠"),
                        master_line("KOSDAQ", "123456", "테스트ETF", group="EF", halted="Y")]) + b"\r\n"
    df = parse_master(raw, "KOSDAQ")
    assert len(df) == 2
    r = df.iloc[0]
    assert (r.ticker, r["name"], r.market, r.group_code) == ("247540", "에코프로비엠", "KOSDAQ", "ST")
    assert r.listing_date == "2019-03-05" and r.listed_shares == 97_830_000 and not r.halted
    assert df.iloc[1].group_code == "EF" and bool(df.iloc[1].halted)
    kospi = parse_master(master_line("KOSPI", "005930", "삼성전자", listing="19750611") + b"\n", "KOSPI")
    assert kospi.iloc[0].ticker == "005930" and kospi.iloc[0].listing_date == "1975-06-11"


def test_get_tickers_from_master_filters_stocks_and_caches(tmp_path):
    files = {"KOSPI": master_line("KOSPI", "005930", "삼성전자") + b"\r\n" + master_line("KOSPI", "069500", "ETF", "EF"),
             "KOSDAQ": master_line("KOSDAQ", "247540", "에코프로비엠")}
    calls = []

    def fetch(market):
        calls.append(market)
        return files[market]
    p, _ = make_provider(tmp_path, FakeKisTransport(), master_fetcher=fetch)
    assert p.get_tickers() == ["005930", "247540"]
    b = p.universe_basis[0]
    assert b["survivorship_bias_possible"] and b["n_tickers"] == 2 and b["source"] == "kis_master_current"
    assert p.ticker_metadata("247540")["listed_shares"] == 97_830_000 and p.ticker_metadata("999999") is None
    assert (tmp_path / "master" / "kospi_code.mst").is_file()
    p2, _ = make_provider(tmp_path, FakeKisTransport(), master_fetcher=fetch)
    p2._wall_clock = lambda: os.path.getmtime(tmp_path / "master" / "kospi_code.mst") + 60
    p2.get_tickers()
    assert calls == ["KOSPI", "KOSDAQ"]                              # second provider used the fresh file cache


# --- credentials -----------------------------------------------------------------------------------------------------------

def test_missing_credentials_message_has_no_values(monkeypatch, tmp_path):
    monkeypatch.delenv("KIS_APP_KEY", raising=False)
    monkeypatch.delenv("KIS_APP_SECRET", raising=False)
    monkeypatch.chdir(tmp_path)                                       # no .env here
    with pytest.raises(ValueError, match="KIS_APP_KEY"):
        KisProvider(transport=FakeKisTransport(), cache_dir=tmp_path)


# --- CLI wiring --------------------------------------------------------------------------------------------------------------

def test_cli_builds_kis_provider(monkeypatch):
    from jusmo_scanner import cli
    from jusmo_scanner.backtest import cli_commands
    seen = {}

    class Spy(KisProvider):
        def __init__(self, *a, **kw):
            seen["args"], seen["kw"] = a, kw
            KisProvider.__init__(self, *a, app_key=FAKE_KEY, app_secret=FAKE_SECRET, transport=FakeKisTransport(), **kw)
    monkeypatch.setattr(kp, "KisProvider", Spy)
    args = cli._build_parser().parse_args(["backtest", "--provider", "kis", "--tickers", "005930,000660",
                                           "--cache-dir", "somewhere", "--refresh", "--fetch-start", "2020-01-01"])
    prov = cli_commands._build_provider(args, pd.Timestamp("2020-01-01").date(), pd.Timestamp("2024-01-01").date(),
                                        None, ["005930", "000660"])
    assert seen["kw"]["tickers"] == ["005930", "000660"] and seen["kw"]["refresh"] is True
    assert seen["kw"]["cache_dir"] == "somewhere" and seen["args"] == ("20200101", "20240101")
    assert prov.price_adjustment_mode is PriceAdjustmentMode.ADJUSTED
    assert cli._build_parser().parse_args(["scan", "--provider", "kis"]).provider == "kis"


# --- secrets ---------------------------------------------------------------------------------------------------------------------

def test_no_tracked_file_contains_real_env_values():
    env = REPO / ".env"
    if not env.is_file():
        pytest.skip("no .env")
    try:
        from dotenv import dotenv_values
        values = {k: v for k, v in dotenv_values(env).items() if k.startswith("KIS_") and v and len(v) >= 6}
        files = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout.split(b"\0")
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git or dotenv unavailable")
    if not values:
        pytest.skip("no KIS_ values in .env")
    offenders = []
    for name in filter(None, files):
        path = REPO / name.decode("utf-8", "replace")
        if not path.is_file():
            continue
        data = path.read_bytes()
        n = sum(data.count(v.encode("utf-8")) for v in values.values())
        if n:
            offenders.append(path.name)
    assert not offenders, f"{len(offenders)} tracked file(s) contain a KIS credential value (names withheld)"


def test_env_and_token_cache_are_git_ignored():
    for rel in (".env", "app ket.txt", "data/cache/.kis_token.json", "data/cache/daily/005930.parquet"):
        r = subprocess.run(["git", "check-ignore", "-q", rel], cwd=REPO)
        assert r.returncode == 0, f"{rel} is not git-ignored"


FAILURES = [
    [(500, {"rt_cd": "1", "msg_cd": "EGW00316", "msg1": f"key={FAKE_KEY}"})] * 9,
    [(200, {"rt_cd": "1", "msg_cd": "OPSQ0002", "msg1": f"secret={FAKE_SECRET} token={FAKE_TOKEN} acct={FAKE_ACCOUNT}"})],
    [(429, {"msg1": f"Authorization: Bearer {FAKE_TOKEN}"})] * 9,
    [(200, None)],
    [(403, {"rt_cd": "1", "msg_cd": "EGW00133", "msg1": f"appkey {FAKE_KEY} appsecret {FAKE_SECRET}"})],
    [KisApiError("NETWORK_ERROR", f"leaked {FAKE_TOKEN}")] * 9,
]


@pytest.mark.parametrize("script", FAILURES)
def test_secret_regression_failures_never_leak(tmp_path, caplog, monkeypatch, script):
    monkeypatch.setenv("KIS_ACCOUNT_NO", FAKE_ACCOUNT)
    caplog.set_level(logging.DEBUG)
    t = FakeKisTransport({"005930": make_bars(5)})
    p, _ = make_provider(tmp_path, t)
    p._tokens.get()                                                   # token exists (and is registered for redaction)
    t.script = list(script)
    with pytest.raises(KisApiError) as ei:
        p.get_ohlcv("005930")
    err = ei.value
    blob = "\n".join([str(err), repr(err), repr(err.args), err.message,
                      "".join(traceback.format_exception(type(err), err, err.__traceback__)),
                      caplog.text, repr(p), repr(p._client), repr(p._tokens)])
    for secret in (FAKE_KEY, FAKE_SECRET, FAKE_TOKEN, FAKE_ACCOUNT):
        assert secret not in blob
    assert err.__cause__ is None and err.__suppress_context__


def test_token_endpoint_failure_never_leaks(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    t = FakeKisTransport({"005930": make_bars(5)})
    t.token_error = (403, {"error_code": "EGW00103", "error_description": f"bad {FAKE_KEY}/{FAKE_SECRET}"})
    p, _ = make_provider(tmp_path, t)
    with pytest.raises(KisApiError) as ei:
        p.get_ohlcv("005930")
    blob = str(ei.value) + repr(ei.value) + caplog.text + "".join(traceback.format_exception(ei.value))
    assert FAKE_KEY not in blob and FAKE_SECRET not in blob


def test_token_file_never_in_repo_paths_and_private_mode(tmp_path):
    p, _ = make_provider(tmp_path, FakeKisTransport({"005930": make_bars(5)}))
    p.get_ohlcv("005930")
    f = tmp_path / ".kis_token.json"
    assert f.is_file() and FAKE_TOKEN in f.read_text()               # intentionally on disk, but only in the cache dir
    if os.name == "posix":
        assert (f.stat().st_mode & 0o077) == 0


@pytest.mark.skipif(os.environ.get("KIS_LIVE_TEST") != "1", reason="live KIS test: set KIS_LIVE_TEST=1")
def test_live_one_request(tmp_path):
    p = KisProvider(start_date="20260101", tickers=["005930"], cache_dir=tmp_path)
    try:
        df = p.get_ohlcv("005930")
        assert len(df) > 50 and df["trading_value"].notna().all()
    finally:
        p.close()
