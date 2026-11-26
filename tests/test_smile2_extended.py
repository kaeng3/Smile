import unittest
from datetime import date,timedelta
from smile2.patterns import Rules,scan,bars
from smile2.extended_patterns import Extensions,trend_box,scan_extended,older_resistance
R=Rules(5,2,.5,1,5,25,3,2,2,4)
E=Extensions(5,.5,15,1,3,2,10,5,3,6,15,1,2)
def bar(i,o,h,l,c,v=100):
    return {"day":(date(2026,1,1)+timedelta(days=i)).isoformat(),"open":o,"high":h,"low":l,"close":c,"volume":v,"value":c*v}
def rising():
    return [bar(i,95+i*2,101+i*2,94+i*2,100+i*2) for i in range(5)]
class ExtensionTests(unittest.TestCase):
    def test_rising_separate_and_completed(self):
        b=rising()+[bar(5,108,121,107,120,300)]
        self.assertIsNotNone(trend_box(b,5,E))
        r=scan(b,R,E)
        self.assertTrue(any(x["strategy"]=="이일홍 상승형" and x["state"]=="첫 꽃 후보" for x in r))
        self.assertFalse(any(x["strategy"]=="이일홍" for x in r))
        r=scan(b+[bar(6,120,126,119,125,200)],R,E)
        self.assertTrue(any(x["strategy"]=="이일홍 상승형" and x["state"]=="완성 후보" for x in r))
        self.assertFalse(any(x["strategy"].startswith("이일홍") and x["state"]=="첫 꽃 후보" for x in r))
    def test_horizontal_not_rising(self):
        b=[bar(i,95,101,94,100) for i in range(5)]
        self.assertIsNone(trend_box(b,5,E))
    def test_older_resistance_informational(self):
        b=[bar(0,200,201,195,200)]+[bar(i+1,95+i*2,101+i*2,94+i*2,100+i*2) for i in range(5)]+[bar(6,108,121,107,120,300)]
        r=scan_extended(b,R,E)
        x=next(x for x in r if x["strategy"]=="이일홍 상승형")
        self.assertEqual(x["older_resistance"]["level"],200)
        self.assertLess(x["older_resistance"]["distance_pct"],0)
    def test_high_play_support_break_and_loss(self):
        b=[bar(0,95,101,94,100),bar(1,110,125,109,120,300),
           bar(2,117,122,113,120),bar(3,120,121,114,116)]
        for today,state in [(bar(4,116,120,115,118),"하단 지지 후보"),
                            (bar(4,116,126,115,125),"조정 후 상단 재돌파 후보"),
                            (bar(4,116,117,105,109),"하단 이탈 주의")]:
            r=scan_extended(b+[today],R,E)
            self.assertTrue(any(x["strategy"]=="고가놀이" and x["state"]==state for x in r),r)
if __name__=="__main__":unittest.main()
