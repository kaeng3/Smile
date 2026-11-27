import unittest
from datetime import date,datetime,time
from smile2.followup_news import followup
class FollowupTests(unittest.TestCase):
    def test_windows_and_future(self):
        d=date(2026,11,27);p=date(2026,11,26)
        def row(i,pub,seen,**extra):
            return {"title":"예시 기사 "+str(i),"url":"https://example.org/"+str(i),
                    "published_at":pub,"observed_at":seen,**extra}
        def dt(hm):return "2026-11-27T"+hm+":00+09:00"
        rows=[row(1,dt("06:30"),dt("07:30")),row(2,dt("15:00"),dt("15:31")),
              row(3,dt("18:20"),dt("18:30")),row(4,None,dt("18:40")),
              row(5,dt("08:00"),dt("08:30")),row(6,dt("19:10"),dt("19:15")),row(8,dt("07:30"),dt("07:40")),
              row(7,dt("06:00"),dt("06:30"),featured_title="[특징주] 예시 기사 7",featured_observed_at=dt("10:00"))]
        r=followup(rows,d,p,datetime.fromisoformat(dt("19:00")),time(15,30))
        es=[e for s in r["sections"] for e in s["events"]]
        self.assertEqual(r["event_count"],6)
        self.assertEqual({e["headline"] for e in es},{"예시 기사 1","예시 기사 2","예시 기사 3","[특징주] 예시 기사 7","예시 기사 8"})
        self.assertEqual(sum(s["count"] for s in r["unknown_sections"]),1)
        self.assertIn("late_featured",next(e["followup_reasons"] for e in es if "7" in e["headline"]))
if __name__=="__main__":unittest.main()
