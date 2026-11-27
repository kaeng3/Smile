import unittest
from datetime import date,time
from smile2.briefing import briefing,bounds
D=date(2026,11,27)
P=date(2026,11,26)
def row(n,pub,seen):
    return {"title":"예시 기업 수주 "+str(n),"url":"https://example.org/"+str(n),"score":10,"published_at":pub,"seen":seen}
class BriefTests(unittest.TestCase):
    def test_boundaries_and_unknown(self):
        rows=[row(1,"2026-11-26T15:30:00+09:00","2026-11-26 16:00"),
              row(2,"2026-11-27T06:59:00+09:00","2026-11-27 06:59"),
              row(3,"2026-11-27T07:00:00+09:00","2026-11-27 07:00"),
              row(4,"2026-11-27T08:00:00+09:00","2026-11-27 08:00"),
              row(5,"2026-11-27T15:29:00+09:00","2026-11-27 15:29"),
              row(6,"2026-11-27T15:30:00+09:00","2026-11-27 15:30"),
              row(7,None,"2026-11-27 06:30"),row(8,None,"2026-11-27 08:01")]
        pre=briefing(rows,D,P,"pre");post=briefing(rows,D,P,"post")
        self.assertEqual(pre["published_articles"],2)
        self.assertEqual(pre["unknown_articles"],1)
        self.assertEqual(post["published_articles"],2)
        self.assertEqual(post["unknown_articles"],1)
        self.assertEqual(pre["cutoff_exclusive"],"2026-11-27T07:00:00+09:00")
        self.assertEqual(post["start"],"2026-11-27T08:00:00+09:00")
        self.assertEqual(post["cutoff_exclusive"],"2026-11-27T15:30:00+09:00")
    def test_no_hindsight(self):
        r=briefing([row(1,"2026-11-27T06:00:00+09:00","2026-11-27 07:10")],D,P,"pre")
        self.assertEqual(r["published_articles"],0)
    def test_inconsistent_timestamp(self):
        r=briefing([row(1,"2026-11-27T06:00:00+09:00","2026-11-27 05:00")],D,P,"pre")
        self.assertEqual(r["excluded_inconsistent_timestamp"],1)
    def test_weekend_previous_session(self):
        r=briefing([row(1,"2026-11-21T12:00:00+09:00","2026-11-21 13:00")],date(2026,11,23),date(2026,11,20),"pre")
        self.assertEqual(r["published_articles"],1)
    def test_invalid_bounds(self):
        with self.assertRaises(ValueError):bounds(D,D,"pre")
        with self.assertRaises(ValueError):bounds(D,P,"post",time(14))
    def test_missing_seen(self):
        self.assertEqual(briefing([row(1,"2026-11-27T06:00:00+09:00",None)],D,P,"pre")["published_articles"],0)
if __name__=="__main__":unittest.main()
