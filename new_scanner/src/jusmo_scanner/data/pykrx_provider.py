from __future__ import annotations
import logging
from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .base import DataProvider, PriceAdjustmentMode, ShareCountBasis

logger = logging.getLogger(__name__)

# Default start of a historical fetch: "the earliest date pykrx could hold". KRX daily data
# begins in the mid-1990s, so this returns each ticker's FULL available history. Episodes have
# no expiry, so a bounded lookback would silently change episode ids / event counts / cost
# anchors; only an explicit --fetch-start may shorten it (and is then recorded as truncated).
EARLIEST_FETCH_DATE = "19900101"

# REAL pykrx 1.2.9 behaviour (verified against the live service): `get_market_ohlcv(..., adjusted=True)`
# is served by Naver, which returns AT MOST this many daily rows counted back from TODAY no matter how
# early the requested start is (2014-07-01 for a 2026-09 run) - so the "full history" default is capped.
NAVER_MAX_ROWS = 3000
_NEED_KRX_LOGIN = ("pykrx >= 1.2 needs the KRX_ID / KRX_PW environment variables for every KRX endpoint "
                   "(ticker lists, market cap, unadjusted OHLCV); without a login KRX answers 400 LOGOUT and "
                   "pykrx silently returns EMPTY results")


class PykrxProvider(DataProvider):
    """Optional adapter backed by the `pykrx` package (`pip install
    jusmo-scanner[pykrx]`). `free_float_shares` is NOT directly available
    from pykrx, so it is approximated with shares outstanding
    (상장주식수) — this is a best-effort fallback, not the true free float,
    and is documented here so callers know its limitation.

    STATUS: optional / EXPERIMENTAL - NOT production-ready. Only the Naver-served
    `adjusted=True` OHLCV path was checked against real pykrx 1.2.9 data (8 tickers).
    NOT validated (they need KRX_ID/KRX_PW login): ticker universe, market cap,
    outstanding shares, holiday/date snapping, signal_start/end universe union,
    raw adjusted=False comparison, true trading-value based Event detection.
    Trading value falls back to close*volume when no market-cap frame is available;
    Events built from that fallback are NOT equivalent to real trading-value Events.
    See README "데이터 공급원 검증 상태"."""

    # A universe date that is not a trading day (weekend/holiday) returns an EMPTY listing from pykrx
    # (as far as we know); it is then moved backward one calendar day at a time, at most this many days.
    UNIVERSE_MAX_STEP_BACK_DAYS = 10

    # More NaN market-cap/share-count rows than this (per ticker) after the join is logged as a warning.
    MISSING_MARKET_DATA_WARN_ROWS = 2

    def __init__(self, start_date: str | None = None, end_date: str | None = None,
                 universe_dates: Sequence[str] | None = None, tickers: Sequence[str] | None = None):
        try:
            import pykrx.stock as pykrx_stock
        except ImportError as exc:
            raise ImportError(
                "pykrx is required for PykrxProvider. Install with: pip install jusmo-scanner[pykrx]"
            ) from exc
        self._stock = pykrx_stock
        # concrete strings only: None must never reach pykrx
        self._start_date = start_date or EARLIEST_FETCH_DATE
        self._end_date = end_date or date.today().strftime("%Y%m%d")
        # As-of universe: YYYYMMDD dates whose listings are unioned (None = today's listing).
        self._universe_dates = sorted(set(universe_dates)) if universe_dates else None
        self._universe_resolution: list[dict] | None = None
        # Explicit ticker list: bypasses the KRX listing entirely (no universe date is used).
        self._explicit_tickers = list(dict.fromkeys(tickers)) if tickers else None
        self._missing_market_data: dict[str, int] = {}
        self._no_trading_value: dict[str, int] = {}
        self._halted_dropped: dict[str, int] = {}
        self._row_capped: dict[str, str] = {}    # ticker -> first returned date (ISO) when the Naver row cap hit

    @property
    def fetch_start(self) -> date:
        return date(int(self._start_date[:4]), int(self._start_date[4:6]), int(self._start_date[6:8]))

    @property
    def price_adjustment_mode(self) -> PriceAdjustmentMode:
        # Evidence: pykrx 1.2.9 `get_market_ohlcv_by_date(fromdate, todate, ticker,
        # freq="d", adjusted: bool = True, ...)` - `get_market_ohlcv` (the call used
        # below, with no `adjusted` argument) therefore returns split-adjusted
        # prices. Volume / trading value / shares are NOT restated.
        return PriceAdjustmentMode.ADJUSTED

    @property
    def share_count_basis(self) -> ShareCountBasis:
        # `free_float_shares` is filled with shares outstanding (see class docstring).
        return ShareCountBasis.OUTSTANDING

    @property
    def universe_basis(self) -> list[dict] | None:
        """After `get_tickers()`: one dict per requested universe date {requested, used, n_tickers}
        (ISO dates; used is None when the date stayed empty after stepping back). Without
        universe_dates: [{"requested": None, "used": None, "n_tickers": n}] = today's listing."""
        return self._universe_resolution

    def _listing_on(self, requested: str) -> tuple[str | None, list[str]]:
        """Listing on `requested` (YYYYMMDD), stepping BACKWARD one calendar day at a time (at
        most UNIVERSE_MAX_STEP_BACK_DAYS) while the listing is empty (non-trading day)."""
        d = date(int(requested[:4]), int(requested[4:6]), int(requested[6:8]))
        for k in range(self.UNIVERSE_MAX_STEP_BACK_DAYS + 1):
            cur = (d - timedelta(days=k)).strftime("%Y%m%d")
            listing = list(self._stock.get_market_ticker_list(cur, market="ALL"))
            if listing:
                return cur, listing
        return None, []

    def get_tickers(self) -> list[str]:
        """Union of the listings on `universe_dates`, each snapped back to a trading day with a
        non-empty listing (an approximation of the as-of universe: securities listed AND delisted
        strictly between the dates are still missing). The requested/used dates are recorded in
        `universe_basis`. Raises RuntimeError when every date stays empty. Without universe_dates:
        today's listing (look-ahead for historical windows; recorded as such)."""
        if self._explicit_tickers:
            self._universe_resolution = [{"requested": None, "used": None,
                                          "n_tickers": len(self._explicit_tickers), "explicit": True}]
            return list(self._explicit_tickers)
        if not self._universe_dates:
            listing = list(self._stock.get_market_ticker_list(market="ALL"))
            self._universe_resolution = [{"requested": None, "used": None, "n_tickers": len(listing)}]
            return listing
        iso = lambda s: f"{s[:4]}-{s[4:6]}-{s[6:8]}"  # noqa: E731
        union: set[str] = set()
        resolution: list[dict] = []
        for req in self._universe_dates:
            used, listing = self._listing_on(req)
            resolution.append({"requested": iso(req), "used": iso(used) if used else None,
                               "n_tickers": len(listing)})
            if used is None:
                logger.warning("universe date %s: empty listing for %d days back; it contributes NOTHING",
                               iso(req), self.UNIVERSE_MAX_STEP_BACK_DAYS)
            elif used != req:
                logger.warning("universe date %s is not a trading day with listings; using %s", iso(req), iso(used))
            union.update(listing)
        self._universe_resolution = resolution
        if not union:
            raise RuntimeError("no listing found for any universe date " +
                               ", ".join(r["requested"] for r in resolution) +
                               f" (each stepped back {self.UNIVERSE_MAX_STEP_BACK_DAYS} days); " + _NEED_KRX_LOGIN)
        return sorted(union)

    def data_quality_report(self) -> dict:
        return {"tickers_with_missing_market_data": len(self._missing_market_data),
                "missing_market_data_rows": sum(self._missing_market_data.values()),
                "tickers_without_trading_value": len(self._no_trading_value),
                "rows_without_trading_value": sum(self._no_trading_value.values()),
                "halted_rows_dropped": sum(self._halted_dropped.values()),
                "history_row_capped_tickers": len(self._row_capped),
                "history_row_cap": NAVER_MAX_ROWS,
                "history_row_capped_first_date": min(self._row_capped.values()) if self._row_capped else None}

    def get_ohlcv(self, ticker: str) -> pd.DataFrame:
        # Naver ignores the end date and counts rows back from today (see NAVER_MAX_ROWS): ask up to
        # TODAY so the row count shows whether the cap hit, then trim to the requested end ourselves.
        today = date.today().strftime("%Y%m%d")
        ohlcv = self._stock.get_market_ohlcv(self._start_date, max(self._end_date, today), ticker, adjusted=True)
        if ohlcv is None or ohlcv.empty:
            return pd.DataFrame(columns=["date", "ticker", "open", "high", "low", "close", "volume",
                                         "trading_value", "market_cap", "free_float_shares"])
        if len(ohlcv) >= NAVER_MAX_ROWS:
            self._row_capped[ticker] = ohlcv.index.min().date().isoformat()
        ohlcv = ohlcv[ohlcv.index <= pd.Timestamp(self._end_date)]
        cap = self._stock.get_market_cap(self._start_date, self._end_date, ticker)
        if cap is None or cap.empty or not {"시가총액", "상장주식수"} <= set(cap.columns):
            # no usable market-cap frame (e.g. an empty DataFrame without columns): every row is
            # "missing market data", counted below instead of failing the ticker
            cap = pd.DataFrame(index=ohlcv.index, columns=["시가총액", "상장주식수", "거래대금"], dtype=float)
        elif "거래대금" not in cap.columns:
            cap = cap.assign(거래대금=np.nan)
        df = ohlcv.drop(columns=["등락률"], errors="ignore")
        if "거래대금" in df.columns:
            df = df.join(cap[["시가총액", "상장주식수"]], how="left")
        else:
            # Naver (adjusted=True) has NO trading value: take KRX's actual traded value from the cap frame
            df = df.join(cap[["시가총액", "상장주식수", "거래대금"]], how="left")
        # halted / no-trade days: Naver reports open = high = low = 0 with volume 0 (close carried over).
        # A zero low/open would corrupt ranges and entry prices: such bars are not tradable, drop them.
        halted = (df["거래량"] == 0) & ((df[["시가", "고가", "저가"]] <= 0).any(axis=1))
        if halted.any():
            self._halted_dropped[ticker] = int(halted.sum())
            df = df[~halted]
        # dates absent from the market-cap frame become NaN market_cap / free_float_shares, which
        # silently disables the STRONG_EVENT turnover leg and capital_impact on those bars: count them
        n_missing = int(df[["시가총액", "상장주식수"]].isna().any(axis=1).sum())
        if n_missing:
            self._missing_market_data[ticker] = n_missing
            if n_missing > self.MISSING_MARKET_DATA_WARN_ROWS:
                logger.warning("%s: %d of %d rows have no market cap / share count after the join "
                               "(turnover and capital impact are missing on those bars)", ticker, n_missing, len(df))
        if "거래대금" not in df.columns:
            df["거래대금"] = np.nan
        n_tv = int(df["거래대금"].isna().sum())
        if n_tv:
            # features.add_trading_value_features then falls back to close * volume (an ADJUSTED close
            # times an unadjusted volume: understated before splits): count it, never hide it
            self._no_trading_value[ticker] = n_tv
        df = df.reset_index().rename(columns={
            "날짜": "date", "시가": "open", "고가": "high", "저가": "low",
            "종가": "close", "거래량": "volume", "거래대금": "trading_value",
            "시가총액": "market_cap", "상장주식수": "free_float_shares",
        })
        df["ticker"] = ticker
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)
