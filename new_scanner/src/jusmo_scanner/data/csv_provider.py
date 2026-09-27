from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

from .base import DataProvider, PriceAdjustmentMode, REQUIRED_COLUMNS, ShareCountBasis

_OPTIONAL_COLUMNS = {"trading_value"}


def _coerce(enum_cls, value):
    if value is None:
        return enum_cls.UNKNOWN
    if isinstance(value, enum_cls):
        return value
    try:
        return enum_cls[str(value).upper()]
    except KeyError:
        raise ValueError(f"invalid {enum_cls.__name__}: {value!r}") from None


class CSVProvider(DataProvider):
    """CSV directory provider. `price_adjustment_mode` / `share_count_basis` are
    UNKNOWN unless given as constructor arguments (enum or its name) or via an
    optional sidecar `meta.json` in the csv dir, e.g.
    {"price_adjustment_mode": "ADJUSTED", "share_count_basis": "FREE_FLOAT"};
    an explicit argument wins over the sidecar."""

    def __init__(self, csv_dir: str | Path,
                 price_adjustment_mode: PriceAdjustmentMode | str | None = None,
                 share_count_basis: ShareCountBasis | str | None = None):
        self._csv_dir = Path(csv_dir)
        meta: dict = {}
        meta_path = self._csv_dir / "meta.json"
        if meta_path.is_file():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            if not isinstance(meta, dict):
                raise ValueError(f"{meta_path} must contain a JSON object")
        self._synthetic = bool(meta.get("synthetic", False))
        self._adjustment = _coerce(
            PriceAdjustmentMode, price_adjustment_mode if price_adjustment_mode is not None
            else meta.get("price_adjustment_mode"))
        self._share_basis = _coerce(
            ShareCountBasis, share_count_basis if share_count_basis is not None
            else meta.get("share_count_basis"))

    @property
    def is_synthetic(self) -> bool:
        return self._synthetic

    @property
    def price_adjustment_mode(self) -> PriceAdjustmentMode:
        return self._adjustment

    @property
    def share_count_basis(self) -> ShareCountBasis:
        return self._share_basis

    def get_tickers(self) -> list[str]:
        return sorted(p.stem for p in self._csv_dir.glob("*.csv"))

    def get_ohlcv(self, ticker: str) -> pd.DataFrame:
        path = self._csv_dir / f"{ticker}.csv"
        df = pd.read_csv(path)
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns and c not in _OPTIONAL_COLUMNS]
        if missing:
            raise ValueError(f"{path} is missing required columns: {missing}")
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)
        if "trading_value" not in df.columns:
            df["trading_value"] = pd.NA
        return df
