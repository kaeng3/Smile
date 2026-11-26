import unittest
from datetime import date,time
from smile2.briefing import bounds,briefing
from smile2.news_engine import build
DAY=date(2026,11,26)
PREV=date(2026,11,25)
SESSION={"day":"2026-11-26","previous":"2026-11-25","calendar":"XKRX",
         "open":"2026-11-26T10:00:00+09:00","close":"2026-11-26T16:30:00+09:00",
         "previous_close":"2026-11-25T15:30:00+09:00"}
class SessionIntegrationTests(unittest.TestCase):
    def test_special_hours(self):
        start,end=bounds(DAY,PREV,"pre",session=SESSION)
        self.assertEqual(end.hour,10)
        result=briefing([{"title":"예시","url":"https://example.org/a","seen":"2026-11-26 09:30"}],DAY,PREV,"pre",session=SESSION)
        self.assertEqual(result["unknown_articles"],1)
        self.assertEqual(result["calendar_basis"],"XKRX")
        with self.assertRaises(ValueError):
            bounds(DAY,PREV,"post",time(16),SESSION)
    def test_mismatched_previous(self):
        with self.assertRaises(ValueError):
            bounds(DAY,date(2026,11,24),"pre",session=SESSION)
class EvidenceTests(unittest.TestCase):
    def test_dart_issuer_and_news_mention(self):
        news={"title":"가나다 기업 계약","url":"https://news.example/a","seen":"2026-11-26 12:00",
              "stocks":[["가나다","000100"]]}
        dart={**news,"url":"https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261126000001",
              "source_kind":"official_disclosure","source_feed":"DART"}
        r=build([news,dart])
        self.assertEqual(r["event_count"],1)
        s=r["events"][0]["stocks"][0]
        self.assertEqual(s["relation"],"official_filing_issuer")
        self.assertEqual(len(s["evidence"]),2)
        fake={**dart,"url":"https://dart.fss.or.kr.example/a"}
        self.assertEqual(build([fake])["events"][0]["stocks"][0]["relation"],"title_mention_unverified")
if __name__=="__main__":
    unittest.main()
