from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import run_daily as daily


TARGET = date(2026, 9, 25)


def frame(last="2026-09-25", bars=240):
    dates = pd.bdate_range(end=last, periods=bars)
    return pd.DataFrame({"date": dates, "close": range(bars)})


def result(ticker, state="IGNITION", prev_state="DORMANT", family="BOTTOM_ACCUMULATION", cost="HOLD"):
    return SimpleNamespace(
        ticker=ticker,
        scan_date=pd.Timestamp(TARGET),
        state=SimpleNamespace(value=state),
        prev_state=SimpleNamespace(value=prev_state),
        strategy_family=family,
        cost_status=cost,
        final_score=85.0,
        close=12000.0,
        estimated_cost=10000.0,
        cost_distance=0.2,
    )


class Provider:
    def __init__(self, frames, metadata=None):
        self.frames = frames
        self.metadata = metadata or {}

    def get_tickers(self):
        return list(self.frames)

    def get_ohlcv(self, ticker):
        value = self.frames[ticker]
        if isinstance(value, Exception):
            raise value
        return value

    def ticker_metadata(self, ticker):
        return {"name": ticker, **self.metadata.get(ticker, {})}

    def close(self):
        pass


def paths(tmp_path):
    history = tmp_path / "history.json"
    history.write_text('{"version":1,"sessions":[]}', encoding="utf-8")
    return history, tmp_path / "sent.json"


def patch_scan(monkeypatch, values):
    monkeypatch.setattr(daily, "load_config", lambda _: object())
    monkeypatch.setattr(
        daily,
        "scan_ticker",
        lambda df, ticker, cfg: SimpleNamespace(results=[values[ticker]], last_bar_date=df["date"].iloc[-1]),
    )


def test_run_daily_filters_metadata_short_stale_and_non_bottom(monkeypatch, tmp_path):
    provider = Provider(
        {
            "GOOD": frame(),
            "HIGH": frame(),
            "SHORT": frame(bars=239),
            "STALE": frame(last="2026-09-24"),
            "HALT": frame(),
        },
        {"HALT": {"halted": True}},
    )
    patch_scan(monkeypatch, {"GOOD": result("GOOD"), "HIGH": result("HIGH", family="HIGH_COST_TRACKING")})
    history, sent = paths(tmp_path)

    session = daily.run_daily(
        target_date=TARGET,
        provider_factory=lambda _: provider,
        notifier=None,
        history_path=history,
        sent_state_path=sent,
    )

    assert [item["ticker"] for item in session["candidates"]] == ["GOOD"]
    assert session["total_tickers"] == 5
    assert session["successful_tickers"] == 4
    assert session["failed_tickers"] == 0


def test_partial_failure_is_counted_but_result_is_written(monkeypatch, tmp_path):
    provider = Provider({"GOOD": frame(), "BAD": RuntimeError("private response")})
    patch_scan(monkeypatch, {"GOOD": result("GOOD")})
    history, sent = paths(tmp_path)

    session = daily.run_daily(
        target_date=TARGET, provider_factory=lambda _: provider, notifier=None,
        history_path=history, sent_state_path=sent,
    )

    assert session["failed_tickers"] == 1
    assert json.loads(history.read_text(encoding="utf-8"))["sessions"][0]["date"] == "20260925"
    assert "private response" not in history.read_text(encoding="utf-8")


@pytest.mark.parametrize("factory_error", [True, False])
def test_provider_or_total_fetch_failure_preserves_existing(monkeypatch, tmp_path, factory_error):
    history, sent = paths(tmp_path)
    original = history.read_bytes()
    factory = (lambda _: (_ for _ in ()).throw(RuntimeError("auth secret"))) if factory_error else (
        lambda _: Provider({"BAD": RuntimeError("raw KIS body")})
    )
    monkeypatch.setattr(daily, "load_config", lambda _: object())

    with pytest.raises(RuntimeError):
        daily.run_daily(
            target_date=TARGET, provider_factory=factory, notifier=None,
            history_path=history, sent_state_path=sent,
        )
    assert history.read_bytes() == original


def test_all_stale_tickers_preserve_existing(monkeypatch, tmp_path):
    history, sent = paths(tmp_path)
    original = history.read_bytes()
    monkeypatch.setattr(daily, "load_config", lambda _: object())
    with pytest.raises(RuntimeError, match="fresh"):
        daily.run_daily(
            target_date=TARGET,
            provider_factory=lambda _: Provider({"STALE": frame(last="2026-09-24")}),
            notifier=None, history_path=history, sent_state_path=sent,
        )
    assert history.read_bytes() == original


def test_universe_failure_is_redacted_and_preserves_existing(monkeypatch, tmp_path):
    history, sent = paths(tmp_path)
    original = history.read_bytes()
    monkeypatch.setattr(daily, "load_config", lambda _: object())
    provider = Provider({})
    provider.get_tickers = lambda: (_ for _ in ()).throw(RuntimeError("SECRET-RAW-URL"))
    with pytest.raises(RuntimeError) as caught:
        daily.run_daily(
            target_date=TARGET, provider_factory=lambda _: provider, notifier=None,
            history_path=history, sent_state_path=sent,
        )
    assert "SECRET-RAW-URL" not in str(caught.value)
    assert history.read_bytes() == original


def test_history_is_saved_before_telegram_and_sent_state_after_success(monkeypatch, tmp_path):
    provider = Provider({"GOOD": frame()})
    patch_scan(monkeypatch, {"GOOD": result("GOOD")})
    history, sent = paths(tmp_path)
    events = []

    class Notifier:
        def send_message(self, text):
            assert json.loads(history.read_text(encoding="utf-8"))["sessions"]
            assert not sent.exists()
            events.append(text)

    daily.run_daily(
        target_date=TARGET, provider_factory=lambda _: provider, notifier=Notifier(),
        history_path=history, sent_state_path=sent,
    )
    assert events
    assert json.loads(sent.read_text(encoding="utf-8"))["sent"]["20260925"]
