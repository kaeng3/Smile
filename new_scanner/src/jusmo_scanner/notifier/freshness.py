from __future__ import annotations
from datetime import date


def is_signal_fresh(transition_date: date, today: date, max_age_days: int) -> bool:
    """True iff the transition is recent enough to announce on Telegram.

    Calendar-day based (weekends/holidays count), so a Friday signal is 3 days
    old on Monday. This can later be replaced by a trading-day calendar.
    A future-dated transition (negative age, e.g. clock skew or a timezone
    difference) is treated as fresh."""
    return (today - transition_date).days <= max_age_days
