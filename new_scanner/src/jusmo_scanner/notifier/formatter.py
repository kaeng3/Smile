from __future__ import annotations
import math

from jusmo_scanner.scanner import state_machine as sm

STATE_EMOJI: dict[sm.State, str] = {
    sm.State.EVENT: "⚡",
    sm.State.ACCUMULATION: "📦",
    sm.State.DORMANT: "😴",
    sm.State.IGNITION: "🔥",
    sm.State.BREAKOUT: "🚀",
    sm.State.PULLBACK: "🔻",
    sm.State.INVALIDATED: "❌",
}

STATE_TITLE: dict[sm.State, str] = {
    sm.State.EVENT: "EVENT",
    sm.State.ACCUMULATION: "ACCUMULATION",
    sm.State.DORMANT: "DORMANT",
    sm.State.IGNITION: "IGNITION",
    sm.State.BREAKOUT: "BREAKOUT",
    sm.State.PULLBACK: "PULLBACK",
    sm.State.INVALIDATED: "INVALIDATED",
}


def _is_missing(x: float | None) -> bool:
    return x is None or not math.isfinite(x)


def format_krw(value: float | None) -> str:
    if _is_missing(value):
        return "N/A"
    return f"{value:,.0f}원"


def format_billion_krw(value: float | None) -> str:
    if _is_missing(value):
        return "N/A"
    return f"{value / 100_000_000:,.0f}억원"


def _format_number(value: float | None, spec: str) -> str:
    return "N/A" if _is_missing(value) else format(value, spec)


def format_scan_message(
    ticker: str, name: str, state: sm.State, prev_state: sm.State,
    close: float, event_date: str, event_trading_value: float | None,
    estimated_cost: float | None, cost_distance: float | None, vcr: float | None, rvol20: float | None,
    ma120: float | None, ma240: float | None, prior_high: float | None,
    structure_score: float, trigger_score: float, final_score: float,
    strategy_family: str | None = None, cost_status: str | None = None,
) -> str:
    emoji = STATE_EMOJI.get(state, "")
    title = STATE_TITLE.get(state, state.name)
    if _is_missing(cost_distance):
        distance_text = "N/A"
    else:
        distance_text = f"{'+' if cost_distance >= 0 else ''}{cost_distance * 100:.2f}%"
    return (
        f"{emoji} [{title}] {name}({ticker})\n\n"
        + (f"전략: {strategy_family} / 원가: {cost_status}\n" if strategy_family else "")
        +
        f"현재가: {format_krw(close)}\n"
        f"Event: {event_date} / {format_billion_krw(event_trading_value)}\n"
        f"추정 매집원가: {format_krw(estimated_cost)}\n"
        f"원가 대비: {distance_text}\n\n"
        f"VCR: {_format_number(vcr, '.2f')}\n"
        f"RVOL20: {_format_number(rvol20, '.2f')}\n\n"
        f"MA120: {format_krw(ma120)}\n"
        f"MA240: {format_krw(ma240)}\n"
        f"전고점: {format_krw(prior_high)}\n\n"
        f"Structure: {_format_number(structure_score, '.0f')}\n"
        f"Trigger: {_format_number(trigger_score, '.0f')}\n"
        f"Final: {_format_number(final_score, '.1f')}\n\n"
        f"상태:\n{STATE_TITLE.get(prev_state, prev_state.name)} → {title}"
    )
