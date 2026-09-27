from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from jusmo_scanner.config import load_config
from jusmo_scanner.data.kis_provider import KisApiError, KisAuthenticationError, KisProvider, TOKEN_INVALID_CODES
from jusmo_scanner.notifier.telegram import TelegramNotifier
from jusmo_scanner.scanner.engine import scan_ticker
from reporting import select_top_candidates, update_history, validate_history
from telegram_digest import send_digest


KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _read_history(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "sessions": []}
    return validate_history(json.loads(path.read_text(encoding="utf-8")))


def _read_sent_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"sent": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("sent"), dict):
        raise ValueError("sent state is invalid")
    return value


def _state_value(value: Any) -> str:
    name = getattr(value, "name", None)
    return str(name if name is not None else getattr(value, "value", value))


def _is_500eok_strong_candle(previous: pd.Series, candle: pd.Series) -> bool:
    return bool(
        float(candle["trading_value"]) >= 50_000_000_000
        and float(candle["close"]) >= float(candle["open"]) * 1.09
        and float(candle["high"]) >= float(previous["close"]) * 1.15
        and float(candle["high"]) >= float(candle["low"]) * 1.15
    )


def _chart_points(
    df: pd.DataFrame,
    limit: int = 60,
) -> list[dict[str, Any]]:
    chart = df.copy()
    close = pd.to_numeric(chart["close"], errors="coerce")
    for window in (5, 20, 60, 120):
        chart[f"ma{window}"] = close.rolling(window, min_periods=window).mean()
    chart["is_500eok"] = False
    for idx in range(1, len(chart)):
        chart.iloc[idx, chart.columns.get_loc("is_500eok")] = _is_500eok_strong_candle(
            chart.iloc[idx - 1], chart.iloc[idx]
        )

    def number(row: Any, field: str, fallback: float) -> float:
        value = getattr(row, field, fallback)
        return fallback if pd.isna(value) else float(value)

    def moving_average(row: Any, field: str) -> float | None:
        value = getattr(row, field)
        return None if pd.isna(value) else float(value)

    return [
        {
            "date": pd.Timestamp(row.date).strftime("%Y%m%d"),
            "close": float(row.close),
            "open": number(row, "open", float(row.close)),
            "high": number(row, "high", float(row.close)),
            "low": number(row, "low", float(row.close)),
            "volume": int(getattr(row, "volume", 0)),
            "ma5": moving_average(row, "ma5"),
            "ma20": moving_average(row, "ma20"),
            "ma60": moving_average(row, "ma60"),
            "ma120": moving_average(row, "ma120"),
            "is_500eok": bool(row.is_500eok),
        }
        for row in chart.tail(limit).itertuples()
    ]


def run_daily(
    *,
    target_date: date,
    provider_factory: Callable[[date], Any],
    notifier,
    history_path: Path,
    sent_state_path: Path,
) -> dict[str, Any]:
    existing = _read_history(history_path)
    try:
        provider = provider_factory(target_date)
    except Exception as exc:
        raise RuntimeError(f"KIS provider initialization failed: {type(exc).__name__}") from None

    cfg = load_config(str(ROOT / "config" / "scanner.yaml"))
    rows: list[dict[str, Any]] = []
    failed = 0
    successful = 0
    fresh = 0
    scan_attempted = 0
    scan_completed = 0
    try:
        try:
            tickers = provider.get_tickers()
        except Exception as exc:
            raise RuntimeError(f"KIS universe fetch failed: {type(exc).__name__}") from None
        for ticker in tickers:
            counted_success = False
            try:
                metadata = provider.ticker_metadata(ticker) or {}
                if any(bool(metadata.get(flag)) for flag in ("halted", "admin", "liquidation")):
                    continue
                df = provider.get_ohlcv(ticker)
                successful += 1
                counted_success = True
                if df.empty or pd.Timestamp(df["date"].iloc[-1]).date() != target_date:
                    continue
                fresh += 1
                if len(df) < 240:
                    continue
                scan_attempted += 1
                scan = scan_ticker(df, ticker, cfg)
                scan_completed += 1
                if not scan.results:
                    continue
                latest = scan.results[-1]
                if pd.Timestamp(latest.scan_date).date() != target_date:
                    continue
                state = _state_value(latest.state)
                previous = _state_value(latest.prev_state)
                rows.append(
                    {
                        "ticker": ticker,
                        "name": metadata.get("name") or metadata.get("korean_name") or ticker,
                        "date": target_date.strftime("%Y%m%d"),
                        "is_latest_bar": True,
                        "is_new_transition": state != previous,
                        "strategy_family": latest.strategy_family,
                        "state": state,
                        "cost_status": latest.cost_status,
                        "final_score": float(latest.final_score),
                        "close": float(latest.close),
                        "estimated_cost": None if latest.estimated_cost is None else float(latest.estimated_cost),
                        "cost_distance": None if latest.cost_distance is None else float(latest.cost_distance),
                        "chart": _chart_points(df),
                    }
                )
            except KisApiError as exc:
                if (isinstance(exc, KisAuthenticationError) or exc.code in TOKEN_INVALID_CODES
                        or exc.status in {401, 403}):
                    raise RuntimeError(f"KIS authentication failed: {exc.code}") from None
                if counted_success:
                    successful -= 1
                failed += 1
            except Exception:
                if counted_success:
                    successful -= 1
                failed += 1
        if successful == 0:
            raise RuntimeError("all ticker fetches failed")
        if fresh == 0:
            raise RuntimeError("no fresh market data for target session")
        if scan_attempted > 0 and scan_completed == 0:
            raise RuntimeError("all current-session analyses failed")

        session = {
            "date": target_date.strftime("%Y%m%d"),
            "generated_at": datetime.now(KST).isoformat(timespec="seconds"),
            "total_tickers": len(tickers),
            "successful_tickers": successful,
            "failed_tickers": failed,
            "candidates": select_top_candidates(rows),
        }
        _atomic_json(history_path, update_history(existing, session))
        if notifier is not None:
            sent_state = _read_sent_state(sent_state_path)
            updated_state = send_digest(notifier, session, sent_state)
            if updated_state != sent_state:
                _atomic_json(sent_state_path, updated_state)
        return session
    finally:
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def _provider_factory(target: date) -> KisProvider:
    start = target - timedelta(days=365 * 3 + 7)
    return KisProvider(
        start_date=start.isoformat(),
        end_date=target.isoformat(),
        cache_dir=ROOT / "data" / "cache",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Kim Ilgu New Scanner daily digest")
    parser.add_argument("--date", help="target session in YYYY-MM-DD format")
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args(argv)
    target = date.fromisoformat(args.date) if args.date else datetime.now(KST).date()
    notifier = None
    if not args.no_telegram:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat_id:
            raise RuntimeError("Telegram credentials are not configured")
        notifier = TelegramNotifier(token, chat_id)
    run_daily(
        target_date=target,
        provider_factory=_provider_factory,
        notifier=notifier,
        history_path=ROOT / "results" / "history.json",
        sent_state_path=ROOT / "state" / "sent.json",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
