from __future__ import annotations

import copy
import math
import re
from datetime import datetime
from collections.abc import Iterable
from typing import Any


_DATE = re.compile(r"^\d{8}$")
_PUBLIC_FIELDS = (
    "ticker",
    "name",
    "date",
    "state",
    "strategy_family",
    "cost_status",
    "final_score",
    "close",
    "estimated_cost",
    "cost_distance",
)


def select_top_candidates(rows: Iterable[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if row.get("is_latest_bar") is True
        and row.get("is_new_transition") is True
        and row.get("strategy_family") == "BOTTOM_ACCUMULATION"
        and row.get("state") in {"IGNITION", "BREAKOUT"}
        and row.get("cost_status") == "HOLD"
    ]
    eligible.sort(key=lambda row: (-float(row["final_score"]), str(row["ticker"])))
    selected = []
    for rank, row in enumerate(eligible[:limit], start=1):
        public = {field: row.get(field) for field in _PUBLIC_FIELDS}
        if "chart" in row:
            public["chart"] = copy.deepcopy(row["chart"])
        public["rank"] = rank
        selected.append(public)
    return selected


# select_top_candidates는 '오늘 막 IGNITION/BREAKOUT으로 새로 전환된' 종목만
# 골라서 하루에 0개가 나오는 날이 흔하다. select_watchlist는 그보다 넓게,
# 신규 전환 여부와 무관하게 현재 유효한 4개 상태(DORMANT/IGNITION/BREAKOUT/
# PULLBACK)에 있는 매집원가 유지 종목을 전부 후보군으로 보여주기 위한 것이다.
_WATCHLIST_STATES = {"DORMANT", "IGNITION", "BREAKOUT", "PULLBACK"}


def select_watchlist(rows: Iterable[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    eligible = [
        row
        for row in rows
        if row.get("is_latest_bar") is True
        and row.get("strategy_family") == "BOTTOM_ACCUMULATION"
        and row.get("state") in _WATCHLIST_STATES
        and row.get("cost_status") == "HOLD"
    ]
    eligible.sort(key=lambda row: (-float(row["final_score"]), str(row["ticker"])))
    selected = []
    for rank, row in enumerate(eligible[:limit], start=1):
        public = {field: row.get(field) for field in _PUBLIC_FIELDS}
        if "chart" in row:
            public["chart"] = copy.deepcopy(row["chart"])
        public["rank"] = rank
        selected.append(public)
    return selected


def _validate_candidate(candidate: object, *, valid_states: frozenset[str] = frozenset({"IGNITION", "BREAKOUT"})) -> None:
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be an object")
    required = set(_PUBLIC_FIELDS) | {"rank"}
    if not required.issubset(candidate):
        raise ValueError("candidate is missing required fields")
    if set(candidate) not in (required, required | {"chart"}):
        raise ValueError("candidate contains unexpected fields")
    if not isinstance(candidate["ticker"], str) or not candidate["ticker"]:
        raise ValueError("candidate ticker must be text")
    if not isinstance(candidate["name"], str) or not candidate["name"]:
        raise ValueError("candidate name must be text")
    if not isinstance(candidate["date"], str) or not _DATE.fullmatch(candidate["date"]):
        raise ValueError("candidate date must use YYYYMMDD")
    try:
        datetime.strptime(candidate["date"], "%Y%m%d")
    except ValueError:
        raise ValueError("candidate date is invalid") from None
    if candidate["state"] not in valid_states:
        raise ValueError("candidate state is invalid")
    if candidate["strategy_family"] != "BOTTOM_ACCUMULATION" or candidate["cost_status"] != "HOLD":
        raise ValueError("candidate strategy or cost status is invalid")
    if not isinstance(candidate["rank"], int) or isinstance(candidate["rank"], bool) or candidate["rank"] < 1:
        raise ValueError("candidate rank must be a positive integer")
    for field in ("final_score", "close"):
        if (not isinstance(candidate[field], (int, float)) or isinstance(candidate[field], bool)
                or not math.isfinite(float(candidate[field]))):
            raise ValueError(f"candidate {field} must be numeric")
    for field in ("estimated_cost", "cost_distance"):
        value = candidate[field]
        if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)
                                  or not math.isfinite(float(value))):
            raise ValueError(f"candidate {field} must be finite or null")
    if "chart" in candidate:
        chart = candidate["chart"]
        if not isinstance(chart, list) or len(chart) > 60:
            raise ValueError("candidate chart must contain at most 60 points")
        legacy_fields = {"date", "close", "volume"}
        rich_fields = legacy_fields | {"open", "high", "low", "ma20", "ma60", "ma120"}
        rich_fields_with_ma5 = rich_fields | {"ma5"}
        legacy_event_fields = rich_fields | {"is_500eok"}
        event_fields = rich_fields_with_ma5 | {"is_500eok"}
        for point in chart:
            point_fields = set(point) if isinstance(point, dict) else set()
            if point_fields not in (legacy_fields, rich_fields, legacy_event_fields, rich_fields_with_ma5, event_fields):
                raise ValueError("candidate chart point is invalid")
            if not isinstance(point["date"], str) or not _DATE.fullmatch(point["date"]):
                raise ValueError("candidate chart date is invalid")
            for field in (legacy_fields - {"date"}) | ({"open", "high", "low"} if point_fields != legacy_fields else set()):
                value = point[field]
                if (not isinstance(value, (int, float)) or isinstance(value, bool)
                        or not math.isfinite(float(value)) or value < 0):
                    raise ValueError("candidate chart value is invalid")
            if point_fields != legacy_fields:
                for field in ({"ma20", "ma60", "ma120"} | ({"ma5"} if "ma5" in point else set())):
                    value = point[field]
                    if value is not None and (not isinstance(value, (int, float)) or isinstance(value, bool)
                                              or not math.isfinite(float(value)) or value < 0):
                        raise ValueError("candidate chart moving average is invalid")
            if point_fields == event_fields and not isinstance(point["is_500eok"], bool):
                raise ValueError("candidate chart event flag is invalid")


def _validate_session(session: object) -> None:
    if not isinstance(session, dict):
        raise ValueError("session must be an object")
    required = {
        "date", "generated_at", "total_tickers", "successful_tickers",
        "failed_tickers", "candidates",
    }
    if not required.issubset(session):
        raise ValueError("session is missing required fields")
    if not isinstance(session["date"], str) or not _DATE.fullmatch(session["date"]):
        raise ValueError("session date must use YYYYMMDD")
    try:
        datetime.strptime(session["date"], "%Y%m%d")
    except ValueError:
        raise ValueError("session date is invalid") from None
    if not isinstance(session["generated_at"], str) or not session["generated_at"]:
        raise ValueError("session generated_at must be text")
    for field in ("total_tickers", "successful_tickers", "failed_tickers"):
        if not isinstance(session[field], int) or isinstance(session[field], bool) or session[field] < 0:
            raise ValueError(f"session {field} must be a non-negative integer")
    if not isinstance(session["candidates"], list):
        raise ValueError("session candidates must be a list")
    for candidate in session["candidates"]:
        _validate_candidate(candidate)
        if candidate["date"] != session["date"]:
            raise ValueError("candidate date must match session date")
    if "watchlist" in session:
        if not isinstance(session["watchlist"], list):
            raise ValueError("session watchlist must be a list")
        for item in session["watchlist"]:
            _validate_candidate(item, valid_states=frozenset(_WATCHLIST_STATES))
            if item["date"] != session["date"]:
                raise ValueError("watchlist item date must match session date")


def validate_history(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("history version must be 1")
    sessions = payload.get("sessions")
    if not isinstance(sessions, list):
        raise ValueError("history sessions must be a list")
    for session in sessions:
        _validate_session(session)
    return copy.deepcopy(payload)


def update_history(existing: dict[str, Any], session: dict[str, Any], keep: int = 5) -> dict[str, Any]:
    history = validate_history(existing)
    _validate_session(session)
    by_date = {item["date"]: item for item in history["sessions"]}
    by_date[session["date"]] = copy.deepcopy(session)
    sessions = sorted(by_date.values(), key=lambda item: item["date"], reverse=True)[:keep]
    return {"version": 1, "sessions": sessions}
