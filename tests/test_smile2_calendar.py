import importlib.util
import unittest
from datetime import date
from smile2.calendar import session_window
@unittest.skipUnless(importlib.util.find_spec("exchange_calendars"),"optional XKRX calendar dependency")
class CalendarTests(unittest.TestCase):
    def test_monday(self):
        r=session_window(date(2026,11,23))
        self.assertEqual(r["previous"],"2026-11-20")
        self.assertTrue(r["open"].endswith("+09:00"))
    def test_weekend(self):
        with self.assertRaises(ValueError):
            session_window(date(2026,11,22))
if __name__=="__main__":
    unittest.main()
