from __future__ import annotations
from datetime import date
from jusmo_scanner.notifier.freshness import is_signal_fresh

D = date(2026, 3, 10)


def test_same_day_is_fresh():
    assert is_signal_fresh(D, D, 3)


def test_boundary_is_inclusive():
    assert is_signal_fresh(D, date(2026, 3, 13), 3)      # 3 days old
    assert not is_signal_fresh(D, date(2026, 3, 14), 3)  # 4 days old


def test_zero_max_age_only_allows_same_day():
    assert is_signal_fresh(D, D, 0)
    assert not is_signal_fresh(D, date(2026, 3, 11), 0)


def test_future_dated_transition_is_fresh():
    assert is_signal_fresh(date(2026, 3, 12), D, 3)
