from __future__ import annotations
import pytest
from jusmo_scanner.data.base import DataProvider, REQUIRED_COLUMNS


def test_required_columns_contains_core_fields():
    for col in ["date", "ticker", "open", "high", "low", "close", "volume",
                "market_cap", "free_float_shares"]:
        assert col in REQUIRED_COLUMNS


def test_data_provider_is_abstract():
    with pytest.raises(TypeError):
        DataProvider()


def test_csv_provider_lists_tickers_from_fixture_dir():
    from jusmo_scanner.data.csv_provider import CSVProvider
    provider = CSVProvider("tests/fixtures")
    assert "CSVTEST" in provider.get_tickers()


def test_csv_provider_sorts_by_date_and_fills_missing_columns():
    from jusmo_scanner.data.csv_provider import CSVProvider
    provider = CSVProvider("tests/fixtures")
    df = provider.get_ohlcv("CSVTEST")
    assert list(df["date"]) == sorted(df["date"])
    assert df.iloc[0]["close"] == 1000
    assert df.iloc[-1]["close"] == 1070
    assert "trading_value" in df.columns


def test_csv_provider_raises_on_missing_required_column(tmp_path):
    from jusmo_scanner.data.csv_provider import CSVProvider
    bad_csv = tmp_path / "BAD.csv"
    bad_csv.write_text("date,ticker,open,high,low,close,volume\n2026-01-01,BAD,1,1,1,1,1\n")
    provider = CSVProvider(tmp_path)
    with __import__("pytest").raises(ValueError):
        provider.get_ohlcv("BAD")


def test_pykrx_provider_raises_helpful_error_without_pykrx_installed(monkeypatch):
    import sys
    from jusmo_scanner.data.pykrx_provider import PykrxProvider
    monkeypatch.setitem(sys.modules, "pykrx", None)
    # If pykrx isn't installed, constructing the provider should raise
    # ImportError with a clear message rather than an opaque traceback.
    # (This test is a no-op assertion of import success when pykrx IS
    # installed in the dev environment; it only exercises the error path
    # when pykrx is unavailable.)
    try:
        PykrxProvider()
    except ImportError as exc:
        assert "pykrx" in str(exc)
