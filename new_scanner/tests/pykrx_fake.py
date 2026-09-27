"""A fake `pykrx.stock` module (no network) mimicking the REAL pykrx 1.2.9 structure (verified live):
`get_market_ohlcv(..., adjusted=True)` is a Naver frame with columns 시가 고가 저가 종가 거래량 등락률 and NO
거래대금, at most `naver_max_rows` rows counted back from the last date whatever the start is, halted days as
open = high = low = 0 / volume 0; `get_market_cap` (KRX) has 시가총액 거래량 거래대금 상장주식수."""
from __future__ import annotations

import sys
import types

import pandas as pd


class FakePykrx:
    """frames: ticker -> scanner-style frame (date, open, high, low, close, volume, trading_value,
    market_cap, free_float_shares). `listings`: {"YYYYMMDD": [tickers]} for as-of universe calls;
    dates not present fall back to `default_listing` (all tickers). `cap_gaps`: ticker -> list of
    Timestamps missing from the market-cap frame."""

    def __init__(self, frames: dict[str, pd.DataFrame], listings=None, cap_gaps=None, holidays=(),
                 empty_cap=(), naver_max_rows=None, ohlcv_trading_value=False, halted=None):
        self.naver_max_rows = naver_max_rows   # real Naver: 3000 (None = uncapped)
        self.ohlcv_trading_value = ohlcv_trading_value   # True mimics the KRX (adjusted=False) 7-column frame
        self.halted = halted or {}             # ticker -> list of dates traded as halted (zero OHLC, volume 0)
        self.holidays = set(holidays)        # "YYYYMMDD" dates on which the listing is EMPTY (like pykrx)
        self.empty_cap = set(empty_cap)      # tickers whose market-cap frame is an empty DataFrame()
        self.frames = frames
        self.listings = listings or {}
        self.cap_gaps = cap_gaps or {}
        self.ohlcv_calls: list[tuple] = []
        self.cap_calls: list[tuple] = []
        self.list_calls: list[tuple] = []

    def _slice(self, ticker, start, end):
        df = self.frames[ticker]
        d = pd.to_datetime(df["date"])
        keep = (d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))
        return df[keep]

    def get_market_ticker_list(self, date=None, market="KOSPI"):
        self.list_calls.append((date, market))
        if date is not None and (pd.Timestamp(date).weekday() >= 5 or date in self.holidays):
            return []                          # non-trading day: pykrx returns an empty listing
        return list(self.listings.get(date, self.frames))

    def get_market_ohlcv(self, start, end, ticker, freq="d", adjusted=True, **kw):
        self.ohlcv_calls.append((start, end, ticker, adjusted))
        if not isinstance(start, str) or not isinstance(end, str):
            raise TypeError(f"pykrx got non-string dates: {start!r}, {end!r}")   # None must never reach pykrx
        df = self.frames[ticker]
        if self.naver_max_rows:
            df = df.iloc[-self.naver_max_rows:]          # counted back from the LAST date, like from today
        d = pd.to_datetime(df["date"])
        df = df[(d >= pd.Timestamp(start)) & (d <= pd.Timestamp(end))]
        out = pd.DataFrame({"시가": df["open"].values, "고가": df["high"].values, "저가": df["low"].values,
                            "종가": df["close"].values, "거래량": df["volume"].values},
                           index=pd.DatetimeIndex(pd.to_datetime(df["date"].values), name="날짜"))
        if self.ohlcv_trading_value:
            out["거래대금"] = df["trading_value"].values
        out["등락률"] = out["종가"].pct_change() * 100
        halted = pd.to_datetime(self.halted.get(ticker, []))
        h = out.index.isin(halted)
        out.loc[h, ["시가", "고가", "저가", "거래량"]] = 0
        return out

    def get_market_cap(self, start, end, ticker, **kw):
        self.cap_calls.append((start, end, ticker))
        if ticker in self.empty_cap:
            return pd.DataFrame()
        df = self._slice(ticker, start, end)
        out = pd.DataFrame({"시가총액": df["market_cap"].values, "거래량": df["volume"].values,
                            "거래대금": df["trading_value"].values, "상장주식수": df["free_float_shares"].values},
                           index=pd.DatetimeIndex(pd.to_datetime(df["date"].values), name="날짜"))
        gaps = pd.to_datetime(self.cap_gaps.get(ticker, []))
        return out[~out.index.isin(gaps)]

    def install(self, monkeypatch) -> "FakePykrx":
        pkg, stock = types.ModuleType("pykrx"), types.ModuleType("pykrx.stock")
        pkg.stock = stock
        for name in ("get_market_ticker_list", "get_market_ohlcv", "get_market_cap"):
            setattr(stock, name, getattr(self, name))
        monkeypatch.setitem(sys.modules, "pykrx", pkg)
        monkeypatch.setitem(sys.modules, "pykrx.stock", stock)
        return self
