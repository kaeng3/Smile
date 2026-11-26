import unittest
from smile2.session_check import compare_sessions,require_sessions
from unittest.mock import patch
class SessionTests(unittest.TestCase):
    def test_missing_not_consecutive(self):
        r=compare_sessions([{"day":"2026-11-23"},{"day":"2026-11-25"}],["2026-11-23","2026-11-24","2026-11-25"])
        self.assertEqual(r["missing"],["2026-11-24"])
    def test_weekend_not_missing(self):
        rows=[{"day":"2026-11-20"},{"day":"2026-11-23"}]
        self.assertEqual(compare_sessions(rows,[r["day"] for r in rows]),{"missing":[],"unexpected":[]})
    def test_single_session_and_weekend_with_calendar(self):
        try:
            import exchange_calendars
        except ImportError:
            self.skipTest("exchange_calendars unavailable")
        from smile2.session_check import expected_sessions
        self.assertEqual(expected_sessions("2026-11-26","2026-11-26"),("2026-11-26",))
        self.assertEqual(expected_sessions("2026-11-21","2026-11-22"),())
        self.assertEqual(expected_sessions("2026-11-20","2026-11-23"),("2026-11-20","2026-11-23"))
    def test_reject_gap(self):
        with patch("smile2.session_check.expected_sessions",return_value=("2026-11-23","2026-11-24","2026-11-25")):
            with self.assertRaises(ValueError):
                require_sessions([{"day":"2026-11-23"},{"day":"2026-11-25"}])
if __name__=="__main__":
    unittest.main()
