import unittest
from datetime import date,timedelta
from smile2.history_search import search
from smile2.patterns import Rules,scan,metrics,bars

# Synthetic fixture only. Not approved production thresholds.
R=Rules(5,2,.5,1,5,12,2,2,2,4)
def bar(i,o,h,l,c,v=100,value=123456):
    return {"day":(date(2026,1,1)+timedelta(days=i)).isoformat(),
            "open":o,"high":h,"low":l,"close":c,"volume":v,"value":value}
def seed():
    return [bar(i,96,101,95,100) for i in range(5)]
class PatternTests(unittest.TestCase):
    def test_first_and_second(self):
        b=seed()+[bar(5,100,112,99,110,300,999)]
        r=scan(b,R)
        self.assertEqual(r[0]["state"],"첫 꽃 후보")
        self.assertEqual(r[0]["first"]["actual_value_won"],999)
        r=scan(b+[bar(6,110,116,109,115,200)],R)
        self.assertEqual(r[0]["state"],"완성 후보")
    def test_three_candle(self):
        b=seed()+[bar(5,100,112,99,110,300),bar(6,111,126,110,114,400),bar(7,114,116,109,111,100)]
        self.assertTrue(any(x["strategy"]=="양봉-윗꼬리양봉-거감음봉" for x in scan(b,R)))
    def test_bearish_middle_not_allowed(self):
        b=seed()+[bar(5,100,112,99,110,300),bar(6,115,126,110,114,400),bar(7,114,116,109,111,100)]
        self.assertFalse(any(x["strategy"]=="양봉-윗꼬리양봉-거감음봉" for x in scan(b,R)))
    def test_recovery(self):
        b=seed()+[bar(5,100,112,99,110,300),bar(6,112,113,105,107,150),bar(7,107,114,106,113,170)]
        self.assertTrue(any(x["state"]=="회복 확인" for x in scan(b,R)))
    def test_doji(self):
        self.assertEqual(metrics(bars([bar(0,100,110,90,100)]),0)["candle"],"doji")
    def test_no_imputed_value(self):
        a=bar(0,100,110,90,100);del a["value"]
        with self.assertRaises(KeyError):
            bars([a])
    def test_duplicate_date(self):
        a=bar(0,100,110,90,100)
        with self.assertRaises(ValueError):
            bars([a,a])
class HistoryTests(unittest.TestCase):
    def test_local_search(self):
        d={"000100":[{"date":"2026-01-01","title":"dGVzdA==","content":"eHl6","enc":True,"stock_name":"예시"}]}
        self.assertEqual(search(d,"test",code="000100")["total_matches"],1)
        self.assertEqual(search(d,"test",start=date(2026,2,1))["total_matches"],0)
        self.assertEqual(search(d,"missing")["total_matches"],0)
    def test_bad_code(self):
        with self.assertRaises(ValueError):
            search({},code="../")
if __name__=="__main__":
    unittest.main()
