from __future__ import annotations

import json
import sys
import types

import pandas as pd
import pytest

from jusmo_scanner.data.base import DataProvider, PriceAdjustmentMode, ShareCountBasis
from jusmo_scanner.data.csv_provider import CSVProvider


class _Minimal(DataProvider):
    def get_tickers(self):
        return []

    def get_ohlcv(self, ticker):
        return pd.DataFrame()


def test_enums_and_default_metadata_is_unknown():
    assert {m.name for m in PriceAdjustmentMode} == {"ADJUSTED", "RAW", "UNKNOWN"}
    assert {m.name for m in ShareCountBasis} == {"FREE_FLOAT", "OUTSTANDING", "UNKNOWN"}
    p = _Minimal()
    assert p.price_adjustment_mode is PriceAdjustmentMode.UNKNOWN
    assert p.share_count_basis is ShareCountBasis.UNKNOWN


def test_csv_provider_defaults_to_unknown():
    p = CSVProvider("tests/fixtures")
    assert p.price_adjustment_mode is PriceAdjustmentMode.UNKNOWN
    assert p.share_count_basis is ShareCountBasis.UNKNOWN


def test_csv_provider_constructor_kwargs(tmp_path):
    p = CSVProvider(tmp_path, price_adjustment_mode=PriceAdjustmentMode.ADJUSTED, share_count_basis="free_float")
    assert p.price_adjustment_mode is PriceAdjustmentMode.ADJUSTED
    assert p.share_count_basis is ShareCountBasis.FREE_FLOAT
    with pytest.raises(ValueError, match="PriceAdjustmentMode"):
        CSVProvider(tmp_path, price_adjustment_mode="bogus")


def test_csv_provider_reads_sidecar_meta_json_and_kwargs_win(tmp_path):
    (tmp_path / "meta.json").write_text(json.dumps(
        {"price_adjustment_mode": "RAW", "share_count_basis": "OUTSTANDING"}), encoding="utf-8")
    p = CSVProvider(tmp_path)
    assert p.price_adjustment_mode is PriceAdjustmentMode.RAW
    assert p.share_count_basis is ShareCountBasis.OUTSTANDING
    q = CSVProvider(tmp_path, price_adjustment_mode=PriceAdjustmentMode.ADJUSTED)
    assert q.price_adjustment_mode is PriceAdjustmentMode.ADJUSTED and q.share_count_basis is ShareCountBasis.OUTSTANDING
    assert "meta" not in p.get_tickers()          # the sidecar is not a ticker


def test_csv_provider_rejects_bad_sidecar(tmp_path):
    (tmp_path / "meta.json").write_text('{"share_count_basis": "nope"}', encoding="utf-8")
    with pytest.raises(ValueError, match="ShareCountBasis"):
        CSVProvider(tmp_path)
    (tmp_path / "meta.json").write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        CSVProvider(tmp_path)


def test_pykrx_provider_metadata(monkeypatch):
    fake = types.ModuleType("pykrx")
    stock = types.ModuleType("pykrx.stock")
    fake.stock = stock
    monkeypatch.setitem(sys.modules, "pykrx", fake)
    monkeypatch.setitem(sys.modules, "pykrx.stock", stock)
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    p = PykrxProvider()
    assert p.share_count_basis is ShareCountBasis.OUTSTANDING
    assert p.price_adjustment_mode is PriceAdjustmentMode.ADJUSTED
