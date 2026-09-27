from __future__ import annotations

import copy
import math

import pytest

from reporting import select_top_candidates, update_history, validate_history


def row(ticker: str, **overrides):
    value = {
        "ticker": ticker,
        "name": f"종목 {ticker}",
        "date": "20260925",
        "is_latest_bar": True,
        "is_new_transition": True,
        "strategy_family": "BOTTOM_ACCUMULATION",
        "state": "IGNITION",
        "cost_status": "HOLD",
        "final_score": 80.0,
        "close": 10000.0,
        "estimated_cost": 9000.0,
        "cost_distance": 0.1111,
    }
    value.update(overrides)
    return value


def session(date: str, ticker: str = "005930"):
    candidate = row(ticker, date=date)
    candidate = {
        key: value
        for key, value in candidate.items()
        if key not in {"is_latest_bar", "is_new_transition"}
    }
    candidate["rank"] = 1
    return {
        "date": date,
        "generated_at": f"{date[:4]}-{date[4:6]}-{date[6:]}T15:55:00+09:00",
        "total_tickers": 100,
        "successful_tickers": 99,
        "failed_tickers": 1,
        "candidates": [candidate],
    }


def test_select_top_candidates_filters_and_sorts_deterministically():
    valid = [row(f"00000{i}") for i in range(6, 0, -1)]
    invalid = [
        row("100001", is_latest_bar=False),
        row("100002", is_new_transition=False),
        row("100003", strategy_family="HIGH_COST_TRACKING"),
        row("100004", state="DORMANT"),
        row("100005", cost_status="BREACHED"),
        row("100006", state="INVALIDATED"),
    ]

    selected = select_top_candidates(valid + invalid)

    assert [item["ticker"] for item in selected] == ["000001", "000002", "000003", "000004", "000005"]
    assert [item["rank"] for item in selected] == [1, 2, 3, 4, 5]
    assert all("is_latest_bar" not in item for item in selected)


def test_update_history_replaces_same_date_and_keeps_latest_five():
    existing = {"version": 1, "sessions": [session(f"202609{day:02d}") for day in range(20, 25)]}
    replacement = session("20260922", "000660")
    updated = update_history(existing, replacement)

    assert [item["date"] for item in updated["sessions"]] == [
        "20260924", "20260923", "20260922", "20260921", "20260920"
    ]
    assert updated["sessions"][2]["candidates"][0]["ticker"] == "000660"


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {"version": 2, "sessions": []},
        {"version": 1, "sessions": [{"date": "2026-09-25", "candidates": []}]},
        {"version": 1, "sessions": [{"date": "20260925", "candidates": [{"ticker": "005930"}]}]},
    ],
)
def test_validate_history_rejects_invalid_schema(payload):
    with pytest.raises(ValueError):
        validate_history(payload)


def test_validate_history_does_not_mutate_input():
    payload = {"version": 1, "sessions": [session("20260925")]}
    before = copy.deepcopy(payload)
    assert validate_history(payload) == payload
    assert payload == before


def test_validate_history_rejects_unexpected_candidate_fields():
    payload = {"version": 1, "sessions": [session("20260925")]}
    payload["sessions"][0]["candidates"][0]["access_token"] = "secret"
    with pytest.raises(ValueError):
        validate_history(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("date", "20269999"),
        ("final_score", math.nan),
        ("estimated_cost", "10000"),
        ("cost_distance", {}),
        ("strategy_family", "HIGH_COST_TRACKING"),
        ("cost_status", "BREACHED"),
    ],
)
def test_validate_history_rejects_non_json_and_strategy_invalid_values(field, value):
    payload = {"version": 1, "sessions": [session("20260925")]}
    payload["sessions"][0]["candidates"][0][field] = value
    with pytest.raises(ValueError):
        validate_history(payload)
