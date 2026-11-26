import unittest
from datetime import date,timedelta
from smile2.patterns import Rules
from smile2.pattern_backtest import evaluate,summarize,Costs
R=Rules(5,2,.5,1,5,12,2,2,2,4)
D=date(2026,1,1)
def row(i,o,h,l,c,v=100):
    return {"day":(D+timedelta(days=i)).isoformat(),"open":o,"high":h,"low":l,"close":c,"volume":v,"value":c*v}
def sample():
    return [row(i,96,101,95,100) for i in range(5)]+[row(5,100,112,99,110,300),row(6,112,121,111,120,200),row(7,120,123,118,122,100)]
class BacktestTests(unittest.TestCase):
    def test_next_open_not_signal_close(self):
        s=evaluate(sample(),R,D,D+timedelta(days=7),[1,2],verify_calendar=False)
        x=next(x for x in s if x["state"]=="첫 꽃 후보")
        self.assertAlmostEqual(x["returns"][1],100*(120/112-1))
        self.assertAlmostEqual(x["returns"][2],100*(122/112-1))
    def test_end_censoring(self):
        s=evaluate(sample(),R,D,D+timedelta(days=5),[1],verify_calendar=False)
        self.assertIsNone(s[0]["returns"][1])
        self.assertIsNone(summarize(s,[1])[0]["horizons"]["1"]["mean_pct"])
    def test_future_changes_do_not_change_first_detection(self):
        b=sample()
        first=evaluate(b,R,D,D+timedelta(days=5),[1],verify_calendar=False)
        b[-1]=row(7,90,93,89,91)
        self.assertEqual(first,evaluate(b,R,D,D+timedelta(days=5),[1],verify_calendar=False))
    def test_costs_and_split_boundary(self):
        c=Costs(10,20,5,5)
        s=evaluate(sample(),R,D,D+timedelta(days=7),[1,2],verify_calendar=False,split=D+timedelta(days=7),costs=c)
        x=next(x for x in s if x["state"]=="첫 꽃 후보")
        self.assertEqual(x["phase"],"development")
        self.assertIsNone(x["returns"][2])
        self.assertIsNone(x["net_returns"][2])
        self.assertAlmostEqual(x["net_returns"][1],100*((120/112)*.9995*.998/(1.0005*1.001)-1))
        self.assertLess(x["net_returns"][1],x["returns"][1])
        self.assertTrue(any("net_mean_pct" in g["horizons"]["1"] for g in summarize(s,[1,2])))
    def test_invalid_costs(self):
        with self.assertRaises(ValueError):Costs(-1,0,0,0)
        with self.assertRaises(ValueError):Costs(0,float("nan"),0,0)
    def test_invalid_split(self):
        with self.assertRaises(ValueError):evaluate(sample(),R,D,D+timedelta(days=7),[1],verify_calendar=False,split=D)
    def test_invalid_turnover_rejected(self):
        b=sample();b[-1]["value"]=1
        with self.assertRaises(ValueError):evaluate(b,R,D,D+timedelta(days=7),[1],verify_calendar=False)
if __name__=="__main__":unittest.main()
