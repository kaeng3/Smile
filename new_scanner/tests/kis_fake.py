"""Fake KIS transport (no network) mimicking the REAL behaviour observed on 2026-09-20: <=100 rows per window,
newest first, `output1` = current snapshot, token endpoint, transient error bodies. All secrets are obviously fake."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

FAKE_KEY = "PSFAKEAPPKEY0123456789ABCDEFGHIJKLMN"
FAKE_SECRET = "FAKE-APP-SECRET-" + "x9Zq" * 20
FAKE_ACCOUNT = "99998888-01"
FAKE_TOKEN = "eyFAKE.TOKEN.PAYLOAD-abcdefghijklmnopqrstuvwxyz"
KST = timezone(timedelta(hours=9))


def make_bars(n: int, end: str = "2024-03-15", base: float = 1000.0, volume: int = 1000) -> list[dict]:
    """n weekday bars ending at `end`, ascending: dicts with iso date + numeric fields."""
    days = pd.bdate_range(end=end, periods=n)
    return [{"date": d.strftime("%Y%m%d"), "open": base + i, "high": base + i + 5, "low": base + i - 5,
             "close": base + i + 1, "volume": volume + i, "tv": (base + i + 1) * (volume + i) * 1.01}
            for i, d in enumerate(days)]


class FakeKisTransport:
    """`bars`: ticker -> ascending list of make_bars() dicts. `script`: list of (status, body) injected on the next
    calls of ANY endpoint (consumed in order) before normal behaviour resumes; an Exception instance is raised."""

    def __init__(self, bars: dict[str, list[dict]] | None = None, token: str = FAKE_TOKEN, shares: int = 1_000_000,
                 expires_in: int = 86400) -> None:
        self.bars = bars or {}
        self.token, self.shares, self.expires_in = token, shares, expires_in
        self.script: list = []
        self.calls: list[dict] = []
        self.token_requests = 0
        self.token_error: tuple[int, dict] | None = None

    def request(self, method, url, headers=None, params=None, json_body=None):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "params": dict(params or {})})
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item[0], {}, item[1]
        if url.endswith("/oauth2/tokenP"):
            self.token_requests += 1
            if self.token_error:
                return self.token_error[0], {}, self.token_error[1]
            return 200, {}, {"access_token": self.token, "token_type": "Bearer", "expires_in": self.expires_in}
        ticker = params["FID_INPUT_ISCD"]
        d1, d2 = params["FID_INPUT_DATE_1"], params["FID_INPUT_DATE_2"]
        rows = [b for b in self.bars[ticker] if d1 <= b["date"] <= d2][-100:][::-1]
        last = self.bars[ticker][-1]
        out2 = [{"stck_bsop_date": b["date"], "stck_clpr": str(b["close"]), "stck_oprc": str(b["open"]),
                 "stck_hgpr": str(b["high"]), "stck_lwpr": str(b["low"]), "acml_vol": str(b["volume"]),
                 "acml_tr_pbmn": str(b["tv"]), "flng_cls_code": "00", "mod_yn": "N"} for b in rows]
        out1 = {"stck_prpr": str(last["close"]), "lstn_stcn": str(self.shares),
                "hts_avls": str(int(last["close"] * self.shares / 1e8))}
        return 200, {}, {"rt_cd": "0", "msg_cd": "MCA00000", "msg1": "ok", "output1": out1, "output2": out2}

    def daily_calls(self):
        return [c for c in self.calls if c["url"].endswith("inquire-daily-itemchartprice")]


class FakeClock:
    """Fake monotonic clock whose sleep advances it."""

    def __init__(self, t: float = 1000.0) -> None:
        self.t = t
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.sleeps.append(s)
        self.t += s


def fixed_now(hour: int = 17, day: str = "2024-03-15"):
    dt = datetime.fromisoformat(day).replace(hour=hour, tzinfo=KST)
    return lambda: dt
