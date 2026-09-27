"""Korea Investment & Securities (KIS) Open API data provider (Stage 3).

STATUS - see README "데이터 공급원 검증 상태" and .git/sdd/kis-report.md. Verified against the REAL production
service (8 tickers) 2026-09-20: OHLCV + REAL daily trading value (`acml_tr_pbmn`) + 100-row windows that are
stitched back to the first listing day. NOT available from KIS: historical (as-of) market cap / share counts,
free-float shares, delisted securities / historical universes. Those columns are always NaN (never fabricated).
CURRENT observations are stored only in cache metadata, never attached to OHLCV.

SECRETS: the app key / secret / access token / account number never appear in logs, exceptions or reprs. Every
transport failure is converted to `KisApiError` (code + redacted message, raised `from None`).
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol, Sequence

import numpy as np
import pandas as pd

from .base import DataProvider, PriceAdjustmentMode, REQUIRED_COLUMNS, ShareCountBasis

logger = logging.getLogger(__name__)

REAL_BASE_URL = "https://openapi.koreainvestment.com:9443"
MOCK_BASE_URL = "https://openapivts.koreainvestment.com:29443"
MASTER_URL = "https://new.real.download.dws.co.kr/common/master/{market}_code.mst.zip"
DAILY_PATH = "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
DAILY_TR_ID = "FHKST03010100"
PAGE_ROWS = 100                       # documented + observed: at most 100 rows per request, no tr_cont paging
EARLIEST_FETCH_DATE = date(1980, 1, 1)
DEFAULT_RATE_PER_SEC = 5.0            # documented real-account limit is higher (20/s); 5/s keeps a wide margin
KST = timezone(timedelta(hours=9))
MARKET_CLOSE_CACHE_HOUR = 16          # bars dated today are partial before this KST hour and are not cached
OVERLAP_DAYS = 10                     # incremental refresh re-reads this many calendar days to detect restatement
TRANSIENT_CODES = frozenset({"EGW00201", "EGW00316", "OPSQ1002"})   # rate limit / retry-later / SESSION FULL (all seen live)
TOKEN_INVALID_CODES = frozenset({"EGW00121", "EGW00123"})
MASTER_MAX_AGE_SECONDS = 24 * 3600


class KisApiError(Exception):
    """Sanitised KIS failure: only an error code, a redacted message and the HTTP status."""

    def __init__(self, code: str, message: str = "", status: int | None = None) -> None:
        self.code, self.message, self.status = str(code), str(message), status
        suffix = f" (HTTP {status})" if status else ""
        super().__init__(f"KIS API error {self.code}: {self.message}{suffix}")

    def __repr__(self) -> str:
        return f"KisApiError(code={self.code!r}, message={self.message!r}, status={self.status!r})"


class KisAuthenticationError(KisApiError):
    """A sanitized OAuth token acquisition failure."""


class Redactor:
    """Replaces every registered secret value with `***`."""

    def __init__(self, *secrets: str | None) -> None:
        self._secrets: set[str] = set()
        for s in secrets:
            self.add(s)

    def add(self, value: str | None) -> None:
        if value and len(value) >= 4:
            self._secrets.add(str(value))

    def clean(self, text) -> str:
        out = str(text)
        for s in sorted(self._secrets, key=len, reverse=True):
            out = out.replace(s, "***")
        return out


class Transport(Protocol):
    def request(self, method: str, url: str, headers: dict | None = None, params: dict | None = None,
                json_body: dict | None = None) -> tuple[int, dict, dict | None]: ...


class RequestsTransport:
    """`requests` based transport. Network exceptions are reduced to their class name (a requests exception
    can embed URLs and headers)."""

    def __init__(self, timeout: float = 15.0) -> None:
        import requests
        self._requests = requests
        self._session = requests.Session()
        self._timeout = timeout

    def request(self, method, url, headers=None, params=None, json_body=None):
        try:
            resp = self._session.request(method, url, headers=headers, params=params, json=json_body,
                                         timeout=self._timeout)
        except self._requests.RequestException as exc:
            raise KisApiError("NETWORK_ERROR", type(exc).__name__) from None
        try:
            body = resp.json()
        except ValueError:
            body = None
        return resp.status_code, {k.lower(): v for k, v in resp.headers.items()}, body

    def close(self) -> None:
        self._session.close()


class RateLimiter:
    """Minimum spacing between calls (rate_per_sec). Clock and sleep are injectable."""

    def __init__(self, rate_per_sec: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be positive")
        self._interval, self._clock, self._sleep = 1.0 / rate_per_sec, clock, sleep
        self._next = float("-inf")

    def acquire(self) -> None:
        now = self._clock()
        start = max(now, self._next)
        if start > now:
            self._sleep(start - now)
        self._next = start + self._interval


def _atomic_write_bytes(path: Path, data: bytes, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if private:
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class TokenManager:
    """Access-token lifecycle. KIS documents ~24h validity and that repeated issuance within ~6h returns the same
    token, so the token is kept in memory and (optionally) a git-ignored file and is reused until shortly before
    expiry. The token is NEVER logged or put in an exception."""

    EXPIRY_MARGIN_SECONDS = 300

    def __init__(self, app_key: str, app_secret: str, transport: Transport, base_url: str, redactor: Redactor,
                 cache_path: Path | str | None = None, clock: Callable[[], float] = time.time) -> None:
        self._key, self._secret, self._transport = app_key, app_secret, transport
        self._base_url, self._redactor, self._clock = base_url.rstrip("/"), redactor, clock
        self._cache_path = Path(cache_path) if cache_path else None
        self._fingerprint = hashlib.sha256(app_key.encode()).hexdigest()[:16]
        self._token: str | None = None
        self._expires_at = 0.0
        self.issued_count = 0

    def _valid(self) -> bool:
        return self._token is not None and self._clock() < self._expires_at - self.EXPIRY_MARGIN_SECONDS

    def _load_file(self) -> None:
        if not self._cache_path or not self._cache_path.is_file():
            return
        try:
            d = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if d.get("fp") == self._fingerprint and d.get("base") == self._base_url:
                self._token, self._expires_at = str(d["token"]), float(d["expires_at"])
                self._redactor.add(self._token)
        except (OSError, ValueError, KeyError, TypeError):
            self._token, self._expires_at = None, 0.0

    def _save_file(self) -> None:
        if not self._cache_path:
            return
        payload = json.dumps({"fp": self._fingerprint, "base": self._base_url, "token": self._token,
                              "expires_at": self._expires_at}).encode("utf-8")
        try:
            _atomic_write_bytes(self._cache_path, payload, private=True)
        except OSError:
            logger.warning("could not write the KIS token cache file (continuing with the in-memory token)")

    def invalidate(self) -> None:
        self._token, self._expires_at = None, 0.0
        if self._cache_path:
            try:
                self._cache_path.unlink()
            except OSError:
                pass

    def get(self) -> str:
        if self._valid():
            return self._token  # type: ignore[return-value]
        self._load_file()
        if self._valid():
            return self._token  # type: ignore[return-value]
        status, _, body = self._transport.request(
            "POST", self._base_url + "/oauth2/tokenP",
            headers={"content-type": "application/json; charset=utf-8"},
            json_body={"grant_type": "client_credentials", "appkey": self._key, "appsecret": self._secret})
        token = body.get("access_token") if isinstance(body, dict) else None
        if status != 200 or not token:
            code = (body.get("error_code") if isinstance(body, dict) else None) or f"HTTP_{status}"
            desc = (body.get("error_description") if isinstance(body, dict) else None) or "token request failed"
            raise KisAuthenticationError(code, self._redactor.clean(desc), status) from None
        self._redactor.add(token)
        self._token = str(token)
        self._expires_at = self._clock() + float(body.get("expires_in") or 86400)
        self.issued_count += 1
        self._save_file()
        logger.info("KIS authentication successful")
        return self._token


class KisClient:
    """Rate-limited GET client for KIS quotation endpoints with retry/backoff and error sanitisation."""

    def __init__(self, app_key: str, app_secret: str, transport: Transport, token_manager: TokenManager,
                 redactor: Redactor, base_url: str = REAL_BASE_URL, rate_per_sec: float = DEFAULT_RATE_PER_SEC,
                 max_retries: int = 4, backoff_base: float = 0.5, backoff_cap: float = 10.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self._key, self._secret, self._transport = app_key, app_secret, transport
        self._tokens, self._redactor, self._base_url = token_manager, redactor, base_url.rstrip("/")
        self._limiter = RateLimiter(rate_per_sec, clock, sleep)
        self._max_retries, self._backoff_base, self._backoff_cap, self._sleep = max_retries, backoff_base, backoff_cap, sleep
        self.requests_made = 0
        self.retries = 0

    def _delay(self, attempt: int, code: str | None) -> float:
        d = min(self._backoff_base * (2 ** attempt), self._backoff_cap)
        return max(d, 1.0) if code == "EGW00201" else d

    def get(self, path: str, tr_id: str, params: dict) -> tuple[dict, dict]:
        token_retried = False
        attempt = 0
        while True:
            self._limiter.acquire()
            headers = {"content-type": "application/json; charset=utf-8",
                       "authorization": "Bearer " + self._tokens.get(), "appkey": self._key,
                       "appsecret": self._secret, "tr_id": tr_id, "custtype": "P"}
            try:
                status, resp_headers, body = self._transport.request("GET", self._base_url + path, headers, params)
            except KisApiError as exc:
                if exc.code == "NETWORK_ERROR" and attempt < self._max_retries:
                    self.retries += 1
                    self._sleep(self._delay(attempt, None))
                    attempt += 1
                    continue
                raise KisApiError(exc.code, self._redactor.clean(exc.message), exc.status) from None
            self.requests_made += 1
            if status == 200 and isinstance(body, dict) and body.get("rt_cd") == "0":
                return resp_headers, body
            code = str(body.get("msg_cd")) if isinstance(body, dict) and body.get("msg_cd") else None
            message = self._redactor.clean(body.get("msg1", "") if isinstance(body, dict) else "unparseable response")
            if code in TOKEN_INVALID_CODES and not token_retried:
                token_retried = True
                self._tokens.invalidate()
                continue
            if (status == 429 or status >= 500 or code in TRANSIENT_CODES) and attempt < self._max_retries:
                self.retries += 1
                self._sleep(self._delay(attempt, code))
                attempt += 1
                continue
            raise KisApiError(code or f"HTTP_{status}", message.strip(), status) from None


# --- daily bars -------------------------------------------------------------------------------------------------

def rows_to_frame(rows: Sequence[dict]) -> pd.DataFrame:
    """KIS output2 rows -> ascending, date-deduplicated frame (date, open, high, low, close, volume, trading_value)."""
    cols = ["date", "open", "high", "low", "close", "volume", "trading_value"]
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in cols}).astype({"date": "datetime64[ns]"})
    src = pd.DataFrame(rows)
    df = pd.DataFrame({
        "date": pd.to_datetime(src["stck_bsop_date"], format="%Y%m%d"),
        "open": pd.to_numeric(src["stck_oprc"], errors="coerce"),
        "high": pd.to_numeric(src["stck_hgpr"], errors="coerce"),
        "low": pd.to_numeric(src["stck_lwpr"], errors="coerce"),
        "close": pd.to_numeric(src["stck_clpr"], errors="coerce"),
        "volume": pd.to_numeric(src["acml_vol"], errors="coerce"),
        "trading_value": pd.to_numeric(src["acml_tr_pbmn"], errors="coerce"),    # real KRW traded value
    })
    return df.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)


def fetch_daily_rows(client: KisClient, ticker: str, start: date, end: date, adjusted: bool):
    """Stitch 100-row windows back through time: each request asks [start, cur_end] and returns the newest <=100
    rows; the next window ends the day before the oldest row received. Returns (rows, output1 of the newest
    window, request count)."""
    rows: list[dict] = []
    snapshot = None
    cur_end = end
    n_requests = 0
    while cur_end >= start:
        _, body = client.get(DAILY_PATH, DAILY_TR_ID, {
            "FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": ticker,
            "FID_INPUT_DATE_1": start.strftime("%Y%m%d"), "FID_INPUT_DATE_2": cur_end.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0" if adjusted else "1"})
        n_requests += 1
        if snapshot is None:
            snapshot = body.get("output1")
        page = [r for r in (body.get("output2") or []) if r.get("stck_bsop_date")]
        if not page:
            break
        rows.extend(page)
        oldest = min(datetime.strptime(r["stck_bsop_date"], "%Y%m%d").date() for r in page)
        if len(page) < PAGE_ROWS or oldest <= start:
            break
        cur_end = oldest - timedelta(days=1)
    return rows, snapshot, n_requests


# --- master files (universe) ------------------------------------------------------------------------------------

# Fixed-width layout of the official kospi_code.mst / kosdaq_code.mst records (KIS open-trading-api stocks_info).
# Each record: short code (9) + standard code (12) + Korean name + fixed tail. Only the fields below are used;
# they are located from the START of the common tail segment (see _TAIL_FIELDS) which was verified on real rows.
_TAIL_FIELDS = [("base_price", 9), ("lot", 5), ("lot_ah", 5), ("halted", 1), ("liquidation", 1), ("admin", 1),
                ("warning", 2), ("warn_notice", 1), ("unfaithful", 1), ("backdoor", 1), ("lock", 2),
                ("par_change", 2), ("capital_increase", 2), ("margin", 3), ("credit_ok", 1), ("credit_days", 3),
                ("prev_volume", 12), ("par_value", 12), ("listing_date", 8), ("listed_shares_k", 15),
                ("capital", 21), ("settle_month", 2), ("ipo_price", 7)]
_AFTER_TAIL = {"KOSPI": 69, "KOSDAQ": 68}          # trailing bytes after ipo_price (verified on real files)
_RECORD_TAIL_LEN = {"KOSPI": 227, "KOSDAQ": 221}    # bytes after the name (group code first)
_TAIL_SPAN = sum(w for _, w in _TAIL_FIELDS)


def parse_master(raw: bytes, market: str) -> pd.DataFrame:
    """Parse a kospi/kosdaq master file into ticker, name, market, group_code (ST = stock), listing_date,
    listed_shares, flags. Current listings only (delisted securities are not in the file)."""
    tail_len, after = _RECORD_TAIL_LEN[market], _AFTER_TAIL[market]
    records = []
    for line in raw.split(b"\n"):
        line = line.rstrip(b"\r")
        if len(line) <= tail_len + 21:
            continue
        p1, tail = line[:-tail_len], line[-tail_len:]
        base = len(tail) - after - _TAIL_SPAN
        vals, pos = {}, base
        for name, width in _TAIL_FIELDS:
            vals[name] = tail[pos:pos + width].decode("ascii", "replace").strip()
            pos += width
        ld = vals["listing_date"]
        try:
            shares = int(vals["listed_shares_k"]) * 1000
        except ValueError:
            shares = None
        records.append({
            "ticker": p1[:9].decode("ascii", "replace").strip(), "name": p1[21:].decode("cp949", "replace").strip(),
            "market": market, "group_code": tail[:2].decode("ascii", "replace"),
            "listing_date": f"{ld[:4]}-{ld[4:6]}-{ld[6:8]}" if len(ld) == 8 and ld.isdigit() and ld != "00000000" else None,
            "listed_shares": shares, "halted": vals["halted"] == "Y", "liquidation": vals["liquidation"] == "Y",
            "admin": vals["admin"] == "Y"})
    return pd.DataFrame(records, columns=["ticker", "name", "market", "group_code", "listing_date",
                                          "listed_shares", "halted", "liquidation", "admin"])


def _download_master(market: str) -> bytes:
    import requests
    try:
        resp = requests.get(MASTER_URL.format(market=market.lower()), timeout=60)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise KisApiError("MASTER_DOWNLOAD_ERROR", type(exc).__name__) from None
    with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
        return z.read(f"{market.lower()}_code.mst")


# --- provider -----------------------------------------------------------------------------------------------------

def _parquet_available() -> bool:
    try:
        import pyarrow  # noqa: F401
        return True
    except ImportError:
        return False


class KisProvider(DataProvider):
    """Production-candidate provider backed by the KIS Open API (real domain).

    Data: OHLCV + REAL trading value from `inquire-daily-itemchartprice` (100 rows per request, stitched back to
    the first listing day), current universe from the official master files. `adjusted=True` (default) uses
    `FID_ORG_ADJ_PRC=0` = 수정주가: verified live that it restates price AND volume (volume x split ratio) but NOT
    the trading value. Old bars change when a new corporate action happens, so the cache re-reads
    OVERLAP_DAYS on every incremental update and re-fetches the whole ticker when the overlap disagrees.

    NOT available from KIS (columns stay NaN, counted in `data_quality_report`, never fabricated): historical
    market cap and share counts, free-float shares. CURRENT observations (`hts_avls` [억원] x 1e8,
    `lstn_stcn` listed shares) stay in cache metadata with observed_at, never a historical as_of.
    Universe = today's listing (survivorship bias possible).
    Bars dated today are not cached before 16:00 KST (partial session)."""

    def __init__(self, start_date: str | None = None, end_date: str | None = None,
                 tickers: Sequence[str] | None = None, cache_dir: str | Path = "data/cache",
                 adjusted: bool = True, refresh: bool = False, rate_per_sec: float = DEFAULT_RATE_PER_SEC,
                 app_key: str | None = None, app_secret: str | None = None, base_url: str = REAL_BASE_URL,
                 transport: Transport | None = None, markets: Sequence[str] = ("KOSPI", "KOSDAQ"),
                 master_fetcher: Callable[[str], bytes] | None = None,
                 now: Callable[[], datetime] | None = None, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep, wall_clock: Callable[[], float] = time.time,
                 cache_format: str | None = None) -> None:
        if app_key is None or app_secret is None:
            try:
                from dotenv import find_dotenv, load_dotenv
                load_dotenv(find_dotenv(usecwd=True))   # .env in the working directory (or above)
            except ImportError:
                pass
            app_key = app_key or os.environ.get("KIS_APP_KEY")
            app_secret = app_secret or os.environ.get("KIS_APP_SECRET")
        if not app_key or not app_secret:
            raise ValueError("KIS_APP_KEY and KIS_APP_SECRET must be set (environment or a git-ignored .env file)")
        self._redactor = Redactor(app_key, app_secret, os.environ.get("KIS_ACCOUNT_NO"))
        self._own_transport = transport is None
        self._transport = transport or RequestsTransport()
        self._cache_dir = Path(cache_dir)
        self._tokens = TokenManager(app_key, app_secret, self._transport, base_url, self._redactor,
                                    self._cache_dir / ".kis_token.json", wall_clock)
        self._client = KisClient(app_key, app_secret, self._transport, self._tokens, self._redactor, base_url,
                                 rate_per_sec, clock=clock, sleep=sleep)
        self._start = date.fromisoformat(start_date) if start_date and "-" in start_date else (
            datetime.strptime(start_date, "%Y%m%d").date() if start_date else EARLIEST_FETCH_DATE)
        self._end = (date.fromisoformat(end_date) if end_date and "-" in end_date else
                     datetime.strptime(end_date, "%Y%m%d").date()) if end_date else None
        self._explicit = list(dict.fromkeys(tickers)) if tickers else None
        self._adjusted, self._refresh = adjusted, refresh
        self._markets = tuple(markets)
        self._master_fetcher = master_fetcher or _download_master
        self._now = now or (lambda: datetime.now(KST))
        self._wall_clock = wall_clock
        self._fmt = cache_format or ("parquet" if _parquet_available() else "csv.gz")
        if self._fmt not in ("parquet", "csv.gz"):
            raise ValueError("cache_format must be 'parquet' or 'csv.gz'")
        self._master: pd.DataFrame | None = None
        self._universe_resolution: list[dict] | None = None
        self._refreshed: set[str] = set()
        self._missing_market_data: dict[str, int] = {}
        self._no_trading_value: dict[str, int] = {}
        self._halted_dropped: dict[str, int] = {}
        self._tv_inconsistent: dict[str, int] = {}
        self._full_fetches = self._incremental_fetches = self._cache_hits = self._restated = 0

    # -- metadata ---------------------------------------------------------------------------------------------------
    @property
    def fetch_start(self) -> date:
        return self._start

    @property
    def price_adjustment_mode(self) -> PriceAdjustmentMode:
        return PriceAdjustmentMode.ADJUSTED if self._adjusted else PriceAdjustmentMode.RAW

    @property
    def share_count_basis(self) -> ShareCountBasis:
        return ShareCountBasis.OUTSTANDING      # lstn_stcn (상장주식수); KIS has no free-float share count

    @property
    def universe_basis(self) -> list[dict] | None:
        return self._universe_resolution

    @property
    def cache_format(self) -> str:
        return self._fmt

    def data_quality_report(self) -> dict:
        return {"tickers_with_missing_market_data": len(self._missing_market_data),
                "missing_market_data_rows": sum(self._missing_market_data.values()),
                "tickers_without_trading_value": len(self._no_trading_value),
                "rows_without_trading_value": sum(self._no_trading_value.values()),
                "halted_rows_dropped": sum(self._halted_dropped.values()),
                "rows_trading_value_vs_close_volume_off_by_over_50pct": sum(self._tv_inconsistent.values()),
                "kis_requests": self._client.requests_made, "kis_retries": self._client.retries,
                "kis_tokens_issued": self._tokens.issued_count, "cache_full_fetches": self._full_fetches,
                "cache_incremental_fetches": self._incremental_fetches, "cache_hits": self._cache_hits,
                "cache_restatement_refetches": self._restated,
                "survivorship_bias_possible": True}

    def close(self) -> None:
        if self._own_transport and hasattr(self._transport, "close"):
            self._transport.close()

    # -- universe ------------------------------------------------------------------------------------------------------
    def _master_frame(self) -> pd.DataFrame:
        if self._master is not None:
            return self._master
        frames = []
        for market in self._markets:
            path = self._cache_dir / "master" / f"{market.lower()}_code.mst"
            fresh = (path.is_file() and not self._refresh
                     and self._wall_clock() - path.stat().st_mtime < MASTER_MAX_AGE_SECONDS)
            raw = path.read_bytes() if fresh else self._master_fetcher(market)
            if not fresh:
                _atomic_write_bytes(path, raw)
            frames.append(parse_master(raw, market))
        self._master = pd.concat(frames, ignore_index=True)
        return self._master

    def get_tickers(self) -> list[str]:
        """Explicit --tickers, else today's KOSPI+KOSDAQ common stocks (group ST) from the official master files.
        Delisted securities and historical universes are NOT available -> survivorship_bias_possible."""
        if self._explicit:
            self._universe_resolution = [{"requested": None, "used": None, "n_tickers": len(self._explicit),
                                          "explicit": True, "survivorship_bias_possible": True}]
            return list(self._explicit)
        m = self._master_frame()
        tickers = sorted(m.loc[m["group_code"] == "ST", "ticker"])
        self._universe_resolution = [{"requested": None, "used": self._now().date().isoformat(),
                                      "n_tickers": len(tickers), "source": "kis_master_current",
                                      "survivorship_bias_possible": True}]
        return tickers

    def ticker_metadata(self, ticker: str) -> dict | None:
        m = self._master_frame()
        row = m[m["ticker"] == ticker]
        return None if row.empty else row.iloc[0].to_dict()

    # -- cache -------------------------------------------------------------------------------------------------------------
    def _cache_paths(self, ticker: str) -> tuple[Path, Path]:
        d = self._cache_dir / "daily"
        return d / f"{ticker}.{self._fmt}", d / f"{ticker}.meta.json"

    def _cache_load(self, ticker: str) -> tuple[pd.DataFrame, dict] | None:
        data_path, meta_path = self._cache_paths(ticker)
        if not (data_path.is_file() and meta_path.is_file()):
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            df = pd.read_parquet(data_path) if self._fmt == "parquet" else pd.read_csv(data_path, parse_dates=["date"])
            df["date"] = pd.to_datetime(df["date"])
            return df, meta
        except Exception:                       # corrupt/partial cache: treat as absent and refetch
            logger.warning("%s: unreadable KIS cache, refetching", ticker)
            return None

    def _cache_save(self, ticker: str, df: pd.DataFrame, meta: dict) -> None:
        data_path, meta_path = self._cache_paths(ticker)
        buf = io.BytesIO()
        if self._fmt == "parquet":
            df.to_parquet(buf, index=False)
            payload = buf.getvalue()
        else:
            import gzip
            payload = gzip.compress(df.to_csv(index=False).encode("utf-8"), mtime=0)
        _atomic_write_bytes(data_path, payload)
        _atomic_write_bytes(meta_path, json.dumps(meta, sort_keys=True).encode("utf-8"))

    # -- daily bars ----------------------------------------------------------------------------------------------------------
    def _effective_end(self) -> date:
        return self._end or self._now().date()

    def _drop_partial_today(self, df: pd.DataFrame) -> pd.DataFrame:
        now = self._now()
        if now.hour < MARKET_CLOSE_CACHE_HOUR:
            return df[df["date"] < pd.Timestamp(now.date())].reset_index(drop=True)
        return df

    def _snapshot_meta(self, snapshot: dict | None) -> dict | None:
        if not snapshot:
            return None
        try:
            return {"observed_at": self._now().isoformat(), "listed_shares": int(snapshot["lstn_stcn"]),
                    "market_cap_won": int(snapshot["hts_avls"]) * 100_000_000}      # hts_avls is in 억원
        except (KeyError, TypeError, ValueError):
            return None

    def _covered_end(self, end: date) -> date:
        """Newest date a fetch made NOW can be complete for (today's bar is partial before the close)."""
        now = self._now()
        return min(end, now.date() if now.hour >= MARKET_CLOSE_CACHE_HOUR else now.date() - timedelta(days=1))

    def _full_fetch(self, ticker: str, start: date, end: date) -> tuple[pd.DataFrame, dict | None]:
        rows, snap, _ = fetch_daily_rows(self._client, ticker, start, end, self._adjusted)
        df = self._drop_partial_today(rows_to_frame(rows))
        self._full_fetches += 1
        return df, self._snapshot_meta(snap)

    def _load_history(self, ticker: str, start: date, end: date) -> tuple[pd.DataFrame, dict | None]:
        cached = self._cache_load(ticker)
        force_full = self._refresh and ticker not in self._refreshed
        self._refreshed.add(ticker)
        meta_base = {"adjusted": self._adjusted, "requested_start": start.isoformat(),
                     "covered_end": self._covered_end(end).isoformat()}
        if cached is not None and not force_full:
            df, meta = cached
            usable = (meta.get("adjusted") == self._adjusted and meta.get("requested_start")
                      and date.fromisoformat(meta["requested_start"]) <= start and len(df))
            if usable:
                last = df["date"].max().date()
                covered = meta.get("covered_end")
                if last >= end or (covered and date.fromisoformat(covered) >= self._covered_end(end)):
                    self._cache_hits += 1
                    return df, meta.get("snapshot")
                window_start = max(start, last - timedelta(days=OVERLAP_DAYS))
                rows, snap, _ = fetch_daily_rows(self._client, ticker, window_start, end, self._adjusted)
                new = self._drop_partial_today(rows_to_frame(rows))
                overlap = new[new["date"] <= pd.Timestamp(last)].merge(df, on="date", suffixes=("_n", "_o"))
                agrees = (len(overlap) > 0
                          and np.allclose(overlap["close_n"], overlap["close_o"], rtol=1e-9, atol=0)
                          and np.allclose(overlap["volume_n"], overlap["volume_o"], rtol=1e-9, atol=0))
                if agrees:
                    merged = (pd.concat([df, new[new["date"] > pd.Timestamp(last)]], ignore_index=True)
                              .drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True))
                    snapshot = self._snapshot_meta(snap) or meta.get("snapshot")
                    self._incremental_fetches += 1
                    self._cache_save(ticker, merged, {**meta_base, "requested_start": meta["requested_start"],
                                                      "snapshot": snapshot})
                    return merged, snapshot
                self._restated += 1
                logger.warning("%s: cached bars disagree with KIS on the overlap (corporate action / restatement?); "
                               "refetching the full history", ticker)
        df, snapshot = self._full_fetch(ticker, start, end)
        self._cache_save(ticker, df, {**meta_base, "snapshot": snapshot})
        return df, snapshot

    def get_ohlcv(self, ticker: str) -> pd.DataFrame:
        start, end = self._start, self._effective_end()
        df, _ = self._load_history(ticker, start, end)
        df = df[(df["date"] >= pd.Timestamp(start)) & (df["date"] <= pd.Timestamp(end))].copy()
        halted = df["volume"].fillna(0) <= 0            # non-trading bars: OHLC = previous close, volume 0
        if halted.any():
            self._halted_dropped[ticker] = int(halted.sum())
            df = df[~halted]
        tv = df["trading_value"].where(df["trading_value"] > 0)
        n_tv = int(tv.isna().sum())
        if n_tv:
            self._no_trading_value[ticker] = n_tv       # feature layer falls back to close*volume for these rows
        df["trading_value"] = tv
        ok = tv.notna()
        off = ((tv[ok] / (df.loc[ok, "close"] * df.loc[ok, "volume"]) - 1).abs() > 0.5).sum()
        if off:
            self._tv_inconsistent[ticker] = int(off)    # e.g. pre-2000 bars: KIS value and close*volume disagree
        df["market_cap"] = np.nan
        df["free_float_shares"] = np.nan
        # output1 is a current observation, even for historical requests. Never
        # attach it (including legacy cached snapshots) to ANY historical bar.
        n_missing = int(df[["market_cap", "free_float_shares"]].isna().any(axis=1).sum())
        if n_missing:
            self._missing_market_data[ticker] = n_missing
        df["ticker"] = ticker
        cols = ["date", "ticker"] + [c for c in REQUIRED_COLUMNS if c not in ("date", "ticker")]
        return df[cols].reset_index(drop=True)
