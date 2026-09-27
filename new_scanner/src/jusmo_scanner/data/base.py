from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum
import pandas as pd

REQUIRED_COLUMNS = [
    "date", "ticker", "open", "high", "low", "close",
    "volume", "trading_value", "market_cap", "free_float_shares",
]


class PriceAdjustmentMode(Enum):
    """Whether OHLC prices are adjusted for splits/mergers/dividends."""
    ADJUSTED = "ADJUSTED"
    RAW = "RAW"
    UNKNOWN = "UNKNOWN"


class ShareCountBasis(Enum):
    """What `free_float_shares` (and so turnover) really counts."""
    FREE_FLOAT = "FREE_FLOAT"
    OUTSTANDING = "OUTSTANDING"
    UNKNOWN = "UNKNOWN"


class DataProvider(ABC):
    """Abstract source of daily OHLCV+market data for tickers. Implementations
    must return data sorted ascending by date. `trading_value` may be NaN for
    rows where the source doesn't supply it directly — feature computation
    falls back to close*volume."""

    @property
    def price_adjustment_mode(self) -> PriceAdjustmentMode:
        """Backtest metadata; UNKNOWN unless a provider knows better."""
        return PriceAdjustmentMode.UNKNOWN

    @property
    def share_count_basis(self) -> ShareCountBasis:
        """Backtest metadata; UNKNOWN unless a provider knows better."""
        return ShareCountBasis.UNKNOWN

    @property
    def universe_basis(self) -> list[str] | None:
        """ISO dates whose listings define the universe (as-of universe), or None if unknown."""
        return None

    @property
    def fetch_start(self):
        """`date` of the earliest bar the provider was asked for (None = not a range fetch)."""
        return None

    def data_quality_report(self) -> dict:
        """Aggregate data-quality counters after get_ohlcv calls, e.g.
        {"tickers_with_missing_market_data": int, "missing_market_data_rows": int}. Default {}."""
        return {}

    @property
    def is_synthetic(self) -> bool:
        """True for generated (non-market) data; backtest reports then say so."""
        return False

    @abstractmethod
    def get_tickers(self) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def get_ohlcv(self, ticker: str) -> pd.DataFrame:
        raise NotImplementedError
