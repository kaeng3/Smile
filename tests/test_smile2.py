import unittest
from smile2.news_engine import build, canonical_url, parse_time
from smile2.audit_history import audit

def row(title,url,**kwargs):
    return dict(title=title,url=url,seen="2026-11-26 18:00",press="source",score=10,**kwargs)

class NewsTests(unittest.TestCase):
    def test_url_dedup(self):
        r=build([row("기업 수주", "https://example.org/a?utm_source=x"),row("기업 수주","https://example.org/a")])
        self.assertEqual(r["unique_url_count"],1)
    def test_exact_title_multiple_sources(self):
        r=build([row("기업 공급계약 체결","https://a.example/1"),row("[속보] 기업 공급계약 체결","https://b.example/2")])
        self.assertEqual(r["event_count"],1)
        self.assertEqual(r["events"][0]["article_count"],2)
    def test_different_event_stage(self):
        r=build([row("우주 기업 대형 위성 승인 신청","https://a.example/1"),row("우주 기업 대형 위성 승인","https://b.example/2")])
        self.assertEqual(r["event_count"],2)
    def test_unknown_publication(self):
        r=build([row("기업 수주","https://example.org/a")])
        self.assertEqual(r["missing_published_at"],1)
        self.assertIsNone(r["events"][0]["articles"][0]["published_at"])
    def test_timezone(self):
        self.assertEqual(parse_time("2026-11-25T18:30:00Z").isoformat(),"2026-11-26T03:30:00+09:00")
        self.assertIsNone(parse_time("2026-11-25T18:30:00"))
    def test_invalid_link(self):
        self.assertEqual(canonical_url("javascript:alert(1)"),"")
        self.assertEqual(build([row("기업 수주","javascript:alert(1)")])["event_count"],0)
    def test_stock_code(self):
        r=build([row("기업 수주","https://a.example/1",stocks=[["예시","000100"],["예시2","0123A0"]])])
        self.assertEqual([s["code"] for s in r["events"][0]["stocks"]],["000100","0123A0"])
    def test_history(self):
        r=audit({"000100":[{"date":"2022-01-01","title":"YQ==","content":"Yg==","enc":True},
                           {"date":"2022-01-01","title":"YQ==","content":"Yg==","enc":True}]})
        self.assertEqual(r["stock_news_rows"],2)
        self.assertEqual(r["duplicate_stock_date_title"],1)
        self.assertNotIn("title",r)

class SourceTimeTests(unittest.TestCase):
    def test_rss_midnight_rollover(self):
        from news_feed.sources import publication_time
        self.assertEqual(publication_time("Wed, 25 Nov 2026 18:30:00 GMT"),"2026-11-26T03:30:00+09:00")
        self.assertEqual(publication_time("2026-11-26T07:00:00+02:00"),"2026-11-26T14:00:00+09:00")
        self.assertIsNone(publication_time("2026-11-26 07:00:00"))
    def test_portal_does_not_invent_publication(self):
        from unittest.mock import patch
        from news_feed import sources
        html='<a href="https://n.news.naver.com/mnews/article/001/123456">테스트용 뉴스 제목입니다</a>'
        with patch.object(sources,"_get",return_value=html):
            items=sources.fetch_portal("네이버 증권속보","https://news.naver.com/test")
        self.assertEqual(len(items),1)
        self.assertIsNone(items[0]["published_at"])
        self.assertEqual(items[0]["time"],"")

class ArticleIdentityTests(unittest.TestCase):
    def test_distinct_urls_with_same_title(self):
        from news_feed.sources import article_key
        self.assertNotEqual(article_key("https://example.org/a"),article_key("https://example.org/b"))
        self.assertEqual(article_key("https://example.org/a?utm_source=x"),article_key("https://example.org/a"))
        self.assertEqual(article_key("https://example.org/a?id=1") == article_key("https://example.org/a?id=2"),False)
    def test_atom_updated_is_not_published(self):
        from unittest.mock import patch
        from news_feed import sources
        xml='<entry><title>예시 기사</title><link href="https://example.org/a"/><updated>2026-11-26T02:00:00Z</updated></entry>'
        with patch.object(sources,"_get",return_value=xml):
            result=sources.fetch_rss("예시","https://example.org/rss")
        self.assertEqual(len(result),1)
        self.assertIsNone(result[0]["published_at"])
        self.assertTrue(result[0]["observed_at"])
    def test_precise_observation(self):
        r=build([row("기업 수주","https://example.org/a",observed_at="2026-11-26T18:00:25+09:00")])
        self.assertEqual(r["events"][0]["articles"][0]["seen_at"],"2026-11-26T18:00:25+09:00")

if __name__=="__main__":
    unittest.main()
