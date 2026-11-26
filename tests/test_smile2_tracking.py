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
    def test_observed_support_loss_not_invalidation(self):
        first=item("첫 꽃 후보")
        first["patterns"][0]["first"]={"close":100}
        first["patterns"][0]["box"]={"upper":98,"lower":90}
        r=merge({},snap("2026-11-25",[first]))
        s={**snap("2026-11-26",[]),"source":"DAUM_KRX_REGULAR","calendar_verified":True,
           "observations":{"000100":{"day":"2026-11-26","close":95}}}
        r=merge(r,s);x=next(iter(r["items"].values()))
        self.assertEqual(x["state"],"미검출·기준 지지선 종가 이탈 주의")
        self.assertEqual(x["latest_observation"]["reference_status"]["initial_box_lower"],"held")
        self.assertEqual(x["last_detected"],"2026-11-25")
    def test_unverified_and_missing_data_not_support_loss(self):
        first=item("첫 꽃 후보");first["patterns"][0]["first"]={"close":100}
        r=merge({},snap("2026-11-25",[first]))
        s={**snap("2026-11-26",[]),"source":"DAUM_KRX_REGULAR","calendar_verified":False,
           "observations":{"000100":{"day":"2026-11-26","close":90}}}
        x=next(iter(merge(r,s)["items"].values()))
        self.assertIsNone(x["latest_observation"])
        self.assertEqual(x["state"],"미검출·재검토")
        s["observations"]={}
        x=next(iter(merge(r,s)["items"].values()))
        self.assertEqual(x["state"],"당일 자료 미확인")
    def test_reference_frozen(self):
        first=item("첫 꽃 후보");first["patterns"][0]["first"]={"close":100}
        r=merge({},snap("2026-11-25",[first]))
        again=item("완성 후보");again["patterns"][0]["first"]={"close":110}
        r=merge(r,snap("2026-11-26",[again]))
        self.assertEqual(next(iter(r["items"].values()))["reference_levels"]["first_close"],100)
    def test_stale(self):
        r=merge({},snap("2026-11-25",[]))
        with self.assertRaises(ValueError):
            merge(r,snap("2026-11-25",[]))
if __name__=="__main__":
    unittest.main()
