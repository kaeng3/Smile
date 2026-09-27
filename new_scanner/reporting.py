from __future__ import annotations

import copy
import re
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
        public["rank"] = rank
        selected.append(public)
    return selected


def _validate_candidate(candidate: object) -> None:
    if not isinstance(candidate, dict):
        raise ValueError("candidate must be an object")
    required = set(_PUBLIC_FIELDS) | {"rank"}
    if not required.issubset(candidate):
        raise ValueError("candidate is missing required fields")
    if set(candidate) != required:
        raise ValueError("candidate contains unexpected fields")
    if not isinstance(candidate["ticker"], str) or not candidate["ticker"]:
        raise ValueError("candidate ticker must be text")
    if candidate["state"] not in {"IGNITION", "BREAKOUT"}:
        raise ValueError("candidate state is invalid")
    for field in ("rank", "final_score", "close"):
        if not isinstance(candidate[field], (int, float)) or isinstance(candidate[field], bool):
            raise ValueError(f"candidate {field} must be numeric")


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
    if not isinstance(session["generated_at"], str) or not session["generated_at"]:
        raise ValueError("session generated_at must be text")
    for field in ("total_tickers", "successful_tickers", "failed_tickers"):
        if not isinstance(session[field], int) or isinstance(session[field], bool) or session[field] < 0:
            raise ValueError(f"session {field} must be a non-negative integer")
    if not isinstance(session["candidates"], list):
        raise ValueError("session candidates must be a list")
    for candidate in session["candidates"]:
        _validate_candidate(candidate)


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
