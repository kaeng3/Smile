import unittest
from datetime import datetime
from news_feed.publication_meta import Metadata,enrich_publication,parse
class PublicationMetaTests(unittest.TestCase):
    def test_published_not_modified(self):
        p=Metadata();p.feed('<meta property="article:published_time" content="2026-11-27T06:20:00+09:00"><meta property="article:modified_time" content="2026-11-27T09:20:00+09:00">')
        self.assertEqual(p.result(),parse("2026-11-27T06:20:00+09:00"))
    def test_jsonld_and_conflict(self):
        p=Metadata();p.feed('<script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-11-27T06:20:00+09:00","dateModified":"2026-11-27T09:20:00+09:00"}</script>')
        self.assertEqual(p.result(),parse("2026-11-27T06:20:00+09:00"))
        p.feed('<meta property="article:published_time" content="2026-11-27T06:30:00+09:00">')
        self.assertIsNone(p.result())
        self.assertIsNone(parse("2026-11-27T06:20:00"))
    def test_recovery_never_backdates_observation(self):
        now=parse("2026-11-27T20:00:00+09:00")
        row={"url":"https://n.news.naver.com/mnews/article/001/123","observed_at":"2026-11-27T06:40:00+09:00"}
        r=enrich_publication([row],fetch=lambda u:(parse("2026-11-27T06:20:00+09:00"),"metadata"),now=now)
        self.assertEqual(r["recovered"],1)
        self.assertEqual(row["publication_verified_at"],now.isoformat())
        self.assertEqual(row["observed_at"],"2026-11-27T06:40:00+09:00")
        self.assertEqual(enrich_publication([row],now=now)["attempted"],0)
    def test_reject_future_and_unsupported_host(self):
        now=parse("2026-11-27T20:00:00+09:00")
        rows=[{"url":"https://n.news.naver.com/mnews/article/001/123","observed_at":"2026-11-27T06:40:00+09:00"},
              {"url":"https://example.org/a","observed_at":"2026-11-27T06:40:00+09:00"}]
        r=enrich_publication(rows,fetch=lambda u:(parse("2026-11-27T07:20:00+09:00"),"metadata"),now=now)
        self.assertEqual(r["attempted"],1);self.assertEqual(r["recovered"],0)
        self.assertFalse(rows[0].get("published_at"))
if __name__=="__main__":unittest.main()
