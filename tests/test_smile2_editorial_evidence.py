import unittest
from smile2.editorial_evidence import evidence_review,official_link,annotate_sections
class EditorialEvidenceTests(unittest.TestCase):
    def article(self,**kw):
        return {"url":"https://example.org/a","title":"기업 계약 체결","press":"test","link_kind":"source_url",**kw}
    def test_official_origin_not_publisher_name(self):
        a=self.article()
        a.update(source_kind="official_rss",source_feed="한국은행 통화정책",url="https://www.bok.or.kr/portal/example")
        self.assertTrue(official_link(a))
        self.assertFalse(official_link({**a,"url":"https://www.bok.or.kr.example.org/a"}))
        self.assertFalse(official_link({**a,"source_kind":"news_metadata"}))
        self.assertFalse(official_link({**a,"url":"http://www.bok.or.kr/a"}))
    def test_dart_exact_origin(self):
        a={"source_kind":"official_disclosure","source_feed":"DART","url":"https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261127000001"}
        self.assertTrue(official_link(a))
        self.assertFalse(official_link({**a,"url":"https://dart.fss.or.kr/dsaf001/main.do?rcpNo=abc"}))
    def test_conflicting_cues_not_confirmation(self):
        a=self.article();a["title"]="기업 계약 체결 후 계약 해지"
        e={"id":"x","headline":a["title"],"articles":[a,{**a,"url":"https://example.org/b","press":"other"}]}
        r=evidence_review(e)
        self.assertIn("caution",r["review_reasons"])
        self.assertEqual(r["publisher_count"],2)
        self.assertEqual(r["independent_confirmation"],"not_assessed")
        self.assertFalse(r["body_checked"])
        self.assertEqual(r["official_urls"],[])
        s=annotate_sections([{"id":"corp","count":1,"events":[e]}])
        self.assertEqual(s[0]["events"][0]["id"],"x")
        self.assertNotIn("evidence_review",e)
if __name__=="__main__":unittest.main()
