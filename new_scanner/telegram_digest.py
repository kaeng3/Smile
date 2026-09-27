from __future__ import annotations

import copy
import hashlib
import json
from typing import Any


def format_top5_message(session: dict[str, Any]) -> str:
    date = session["date"]
    title = f"🔎 김일구 New스캐너 TOP5 ({date[:4]}-{date[4:6]}-{date[6:]})"
    candidates = session["candidates"]
    if not candidates:
        return f"{title}\n오늘 신규 후보 없음"

    lines = [title]
    for item in candidates:
        cost = item.get("estimated_cost")
        cost_text = f"{cost:,.0f}원" if cost is not None else "-"
        distance = item.get("cost_distance")
        distance_text = f"{distance * 100:.2f}%" if distance is not None else "-"
        lines.extend(
            [
                "",
                f"{item['rank']}. {item['name']} ({item['ticker']}) · {item['state']}",
                f"종가 {item['close']:,.0f}원 | 매집원가 {cost_text}",
                f"원가 대비 {distance_text} | 점수 {item['final_score']:.1f}",
            ]
        )
    return "\n".join(lines)


def _result_hash(session: dict[str, Any]) -> str:
    canonical = json.dumps(
        {"date": session["date"], "candidates": session["candidates"]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def send_digest(notifier, session: dict[str, Any], sent_state: dict[str, Any]) -> dict[str, Any]:
    date = session["date"]
    digest = _result_hash(session)
    sent = sent_state.get("sent", {})
    if sent.get(date) == digest:
        return copy.deepcopy(sent_state)

    try:
        notifier.send_message(format_top5_message(session))
    except Exception as exc:
        raise RuntimeError(f"Telegram digest send failed: {type(exc).__name__}") from None

    updated = copy.deepcopy(sent_state)
    updated.setdefault("sent", {})[date] = digest
    return updated
