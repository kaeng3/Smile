# src/jusmo_scanner/jobs/scan_eod.py
from __future__ import annotations
from datetime import date
import logging

from jusmo_scanner.config import ScannerConfig
from jusmo_scanner.notifier.formatter import format_scan_message
from jusmo_scanner.notifier.freshness import is_signal_fresh
from jusmo_scanner.scanner import engine
from jusmo_scanner.storage import sqlite_store as store

logger = logging.getLogger(__name__)


def run(provider, cfg: ScannerConfig, db_path, notifier=None, today: date | None = None) -> None:
    # NOTE: Stage 1 only sends a per-transition notification; it has no
    # "ranked top-N candidates" output. If a future feature adds one, it MUST
    # filter with `scoring.is_candidate(r.state)` first — an INVALIDATED
    # ticker is never a candidate regardless of its score, even though it
    # still gets its own INVALIDATED transition notification below.
    today = today or date.today()
    tickers = provider.get_tickers()
    if not tickers:
        raise RuntimeError("Universe is empty; data provider is not configured")
    store.init_db(db_path)
    all_scans = engine.run_scan(provider, tickers, cfg)
    if not all_scans:
        raise RuntimeError(
            f"No ticker scanned successfully ({len(tickers)} tickers attempted); check data and logs")

    for ticker, scan in all_scans.items():
        event_rows = [
            (ticker, str(ee.event.event_date.date()), ee.episode_id,
             ee.event.open, ee.event.high, ee.event.low, ee.event.close, ee.event.volume,
             ee.event.trading_value, ee.event.turnover, ee.event.value_ratio,
             ee.event.capital_impact, ee.event.location120, ee.event.event_score,
             ee.event.event_price)
            for ee in scan.events
        ]
        ticker_results = scan.results
        result_rows = [
            (r.ticker, str(r.scan_date.date()), r.state.name, r.structure_score, r.trigger_score,
             r.theme_score, r.final_score, r.structure_components, r.trigger_components,
             r.close, r.estimated_cost, r.cost_distance, r.vcr, r.rvol20,
             r.distribution_warning, r.episode_id, r.event_count, r.event_trading_value,
             r.ma120, r.ma240, r.prior_high, r.strategy_family, r.anchor_event_location,
             r.event_location, r.current_location, r.cost_status)
            for r in ticker_results
        ]
        transitions = [r for r in ticker_results if r.state != r.prev_state]
        transition_rows = [
            (r.ticker, r.episode_id, str(r.scan_date.date()), r.prev_state.name, r.state.name)
            for r in transitions
        ]
        # One connection / one transaction per ticker (bulk backfills would
        # otherwise pay a connect+commit per row).
        store.persist_ticker_batch(db_path, event_rows, result_rows, transition_rows)
        if not ticker_results:
            continue
        # Gate on the ticker's last DATA bar, not the last bar with a result:
        # a long-terminated (INVALIDATED) episode must not notify as if new.
        latest_scan_date = scan.last_bar_date

        for r in transitions:
            scan_date = str(r.scan_date.date())

            # Bootstrap safety: build the FULL history into scan_results /
            # state_history above regardless of date (that's just a
            # snapshot log), but a transition is only ever ELIGIBLE for a
            # Telegram notification if it's on the most recent bar in this
            # run's results — historical transitions from a first/backfill
            # run must never be replayed as if they just happened.
            if r.scan_date != latest_scan_date:
                continue
            # Freshness gate (Telegram only; DB rows above are always written):
            # an old CSV / stale data feed must not announce old signals.
            if not is_signal_fresh(r.scan_date.date(), today, cfg.telegram_max_signal_age_days):
                logger.info("skip stale notification for %s %s (%s)", r.ticker, r.state.name, scan_date)
                continue
            if notifier is None:
                continue

            # Independent idempotency layer on top of state_history's own
            # dedup — belt and suspenders against ever double-notifying the
            # same (ticker, episode, state, date). Checked BEFORE sending so
            # that a transient send failure leaves no row behind, allowing
            # the next run to retry rather than silently skipping forever.
            # NOTE: state_history's own insert above is intentionally NOT
            # used to gate this (its dedup fires on first insert regardless
            # of notify outcome, which would permanently block same-day
            # retries after a failed send) — notification_log is the sole
            # idempotency gate for notifications.
            if store.has_been_notified(db_path, ticker=r.ticker, episode_id=r.episode_id,
                                        state=r.state.name, transition_date=scan_date):
                continue

            message = format_scan_message(
                ticker=r.ticker, name=r.ticker, state=r.state, prev_state=r.prev_state,
                close=r.close, event_date=str(r.anchor_event_date.date()),
                event_trading_value=r.event_trading_value, estimated_cost=r.estimated_cost,
                cost_distance=r.cost_distance, vcr=r.vcr, rvol20=r.rvol20,
                ma120=r.ma120, ma240=r.ma240, prior_high=r.prior_high,
                structure_score=r.structure_score, trigger_score=r.trigger_score,
                final_score=r.final_score,
                strategy_family=r.strategy_family, cost_status=r.cost_status,
            )
            try:
                notifier.send_message(message)
            except Exception:
                logger.exception("failed to send Telegram notification for %s", ticker)
            else:
                store.insert_notification(db_path, ticker=r.ticker, episode_id=r.episode_id,
                                           state=r.state.name, transition_date=scan_date)
