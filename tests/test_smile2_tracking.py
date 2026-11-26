import unittest
from smile2.track import merge
def snap(day,candidates,errors=None):
    return {"as_of":day,"status":"research_candidates","candidates":candidates,"errors":errors or []}
def item(state):
    return {"code":"000100","patterns":[{"strategy":"이일홍","first_day":"2026-11-25","state":state,"today":{"close":100}}]}
class TrackingTests(unittest.TestCase):
    def test_transition(self):
        r=merge({},snap("2026-11-25",[item("첫 꽃 후보")]))
        r=merge(r,snap("2026-11-26",[item("완성 후보")]))
        self.assertEqual(len(r["items"]),1)
        self.assertEqual(list(r["items"].values())[0]["state"],"완성 후보")
    def test_missing_not_invalid(self):
        r=merge({},snap("2026-11-25",[item("첫 꽃 후보")]))
        r=merge(r,snap("2026-11-26",[]))
        self.assertEqual(list(r["items"].values())[0]["state"],"미검출·재검토")
    def test_stale(self):
        r=merge({},snap("2026-11-25",[]))
        with self.assertRaises(ValueError):
            merge(r,snap("2026-11-25",[]))
if __name__=="__main__":
    unittest.main()
