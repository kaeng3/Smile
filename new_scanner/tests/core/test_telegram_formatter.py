from __future__ import annotations
from jusmo_scanner.scanner import state_machine as sm
from jusmo_scanner.notifier import formatter


def test_format_scan_message_contains_key_fields():
    msg = formatter.format_scan_message(
        ticker="005930", name="삼성전자", state=sm.State.IGNITION, prev_state=sm.State.DORMANT,
        close=8240, event_date="2026-08-27", event_trading_value=87_300_000_000,
        estimated_cost=7820, cost_distance=0.0537, vcr=0.27, rvol20=1.84,
        ma120=8020, ma240=8190, prior_high=8560,
        structure_score=91, trigger_score=78, final_score=86.5,
    )
    assert "IGNITION" in msg
    assert "삼성전자" in msg
    assert "005930" in msg
    assert "8,240" in msg
    assert "873억원" in msg
    assert "DORMANT" in msg and "IGNITION" in msg
    assert len(msg) < 1000


def test_format_scan_message_uses_correct_emoji_per_state():
    for state, emoji in formatter.STATE_EMOJI.items():
        msg = formatter.format_scan_message(
            ticker="T", name="테스트", state=state, prev_state=sm.State.NONE,
            close=1000, event_date="2026-01-01", event_trading_value=50_000_000_000,
            estimated_cost=1000, cost_distance=0.0, vcr=0.3, rvol20=1.0,
            ma120=1000, ma240=1000, prior_high=1000,
            structure_score=50, trigger_score=50, final_score=50,
        )
        assert emoji in msg


def test_format_krw_adds_thousands_separator():
    assert formatter.format_krw(8240) == "8,240원"


def test_format_billion_krw():
    assert formatter.format_billion_krw(87_300_000_000) == "873억원"


def test_missing_formatter_values_display_na_not_zero():
    nan = float("nan")
    for missing in (None, nan, float("inf")):
        msg = formatter.format_scan_message(
            ticker="T", name="테스트", state=sm.State.DORMANT, prev_state=sm.State.ACCUMULATION,
            close=1000, event_date="2026-01-01", event_trading_value=missing,
            estimated_cost=missing, cost_distance=missing, vcr=missing, rvol20=missing,
            ma120=missing, ma240=missing, prior_high=missing,
            structure_score=50, trigger_score=50, final_score=50,
        )
        assert "Event: 2026-01-01 / N/A" in msg
        assert "추정 매집원가: N/A" in msg
        assert "원가 대비: N/A" in msg
        assert "VCR: N/A" in msg
        assert "RVOL20: N/A" in msg
        assert "MA120: N/A" in msg
        assert "MA240: N/A" in msg
        assert "전고점: N/A" in msg
        assert "nan" not in msg.lower()
        assert "inf" not in msg.lower()
        assert "0억원" not in msg
        assert ": 0원" not in msg


def test_format_scan_message_scores_missing_values_render_na():
    msg = formatter.format_scan_message(
        ticker="005930", name="X", state=sm.State.IGNITION, prev_state=sm.State.DORMANT,
        close=8240, event_date="2026-08-27", event_trading_value=None,
        estimated_cost=None, cost_distance=None, vcr=None, rvol20=None,
        ma120=None, ma240=None, prior_high=None,
        structure_score=float("nan"), trigger_score=None, final_score=float("inf"),
    )
    assert "Structure: N/A" in msg and "Trigger: N/A" in msg and "Final: N/A" in msg
    assert "nan" not in msg.lower() and "inf" not in msg.lower()
