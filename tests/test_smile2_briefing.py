import unittest
from datetime import date,time
from smile2.briefing import briefing,bounds

D=date(2026,11,26)
P=date(2026,11,25)
def row(n,pub,seen):
    return {"title":"예시 기업 수주 "+str(n),"url":"https://example.org/"+str(n),
            "score":10,"published_at":pub,"seen":seen}
class BriefTests(unittest.TestCase):
    def test_boundaries_and_unknown(self):
        rows=[row(1,"2026-11-25T15:30:00+09:00","2026-11-25 16:00"),
              row(2,"2026-11-26T08:59:00+09:00","2026-11-26 08:59"),
              row(3,"2026-11-26T09:00:00+09:00","2026-11-26 09:00"),
              row(4,None,"2026-11-26 08:00")]
        pre=briefing(rows,D,P,"pre")
        post=briefing(rows,D,P,"post")
        self.assertEqual(pre["published_articles"],2)
        self.assertEqual(pre["unknown_articles"],1)
        self.assertEqual(post["published_articles"],1)
        self.assertEqual(post["unknown_articles"],0)
    def test_no_hindsight(self):
        r=briefing([row(1,"2026-11-26T07:00:00+09:00","2026-11-26 10:00")],D,P,"pre")
        self.assertEqual(r["published_articles"],0)
    def test_inconsistent_timestamp(self):
        r=briefing([row(1,"2026-11-26T08:00:00+09:00","2026-11-26 07:00")],D,P,"pre")
        self.assertEqual(r["excluded_inconsistent_timestamp"],1)
    def test_weekend_previous_session(self):
        r=briefing([row(1,"2026-11-21T12:00:00+09:00","2026-11-21 13:00")],
                   date(2026,11,23),date(2026,11,20),"pre")
        self.assertEqual(r["published_articles"],1)
    def test_invalid_bounds(self):
        with self.assertRaises(ValueError):
            bounds(D,D,"pre")
        with self.assertRaises(ValueError):
            bounds(D,P,"post",time(14))
    def test_missing_seen(self):
        self.assertEqual(briefing([row(1,"2026-11-26T07:00:00+09:00",None)],D,P,"pre")["published_articles"],0)
if __name__=="__main__":
    unittest.main()
