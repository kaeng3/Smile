from __future__ import annotations

import copy

import pytest

from telegram_digest import format_top5_message, send_digest


def session(candidates=None):
    return {
        "date": "20260925",
        "generated_at": "2026-09-25T15:55:00+09:00",
        "total_tickers": 100,
        "successful_tickers": 99,
        "failed_tickers": 1,
        "candidates": candidates or [],
    }


def candidate():
    return {
        "rank": 1,
        "ticker": "005930",
        "name": "삼성전자",
        "date": "20260925",
        "state": "IGNITION",
        "strategy_family": "BOTTOM_ACCUMULATION",
        "cost_status": "HOLD",
        "final_score": 87.5,
        "close": 75000.0,
        "estimated_cost": 70000.0,
        "cost_distance": 0.0714,
    }


class FakeNotifier:
    def __init__(self, error=None):
        self.messages = []
        self.error = error

    def send_message(self, text):
        self.messages.append(text)
        if self.error:
            raise self.error


def test_format_top5_message_handles_candidates_and_empty_day():
    text = format_top5_message(session([candidate()]))
    assert "삼성전자 (005930)" in text
    assert "75,000원" in text
    assert "7.14%" in text
    assert "87.5" in text
    assert "오늘 신규 후보 없음" in format_top5_message(session())


def test_send_digest_records_only_after_success_and_deduplicates():
    notifier = FakeNotifier()
    state = {"sent": {}}
    first = send_digest(notifier, session([candidate()]), state)
    second = send_digest(notifier, session([candidate()]), first)

    assert len(notifier.messages) == 1
    assert first == second
    assert first["sent"]["20260925"]


def test_send_digest_failure_does_not_mutate_state_or_leak_secret():
    secret = "123456:ABC-SECRET"
    url = f"https://api.telegram.org/bot{secret}/sendMessage"
    notifier = FakeNotifier(RuntimeError(url))
    state = {"sent": {}}
    before = copy.deepcopy(state)

    with pytest.raises(RuntimeError) as caught:
        send_digest(notifier, session([candidate()]), state)

    assert state == before
    assert secret not in str(caught.value)
    assert url not in str(caught.value)


def test_changed_result_for_same_date_is_sent_again():
    notifier = FakeNotifier()
    first = send_digest(notifier, session([candidate()]), {"sent": {}})
    changed = candidate()
    changed["final_score"] = 88.0
    second = send_digest(notifier, session([changed]), first)

    assert len(notifier.messages) == 2
    assert second["sent"]["20260925"] != first["sent"]["20260925"]
