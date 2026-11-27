import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from news_feed import collect
class LiveCaptureTests(unittest.TestCase):
    def test_isolated_capture_and_health(self):
        f={"portals":{"empty":"https://example.org/empty"},"rss":{"news":"https://example.org/feed"},
           "categories":{"경제":["금리"]},"theme_sector":[],"event_words":["수주"],
           "min_spec":.3,"store_min_score":8,"macro_score":6,"keep_days":5}
        row={"title":"예시기업 수주 계약","url":"https://example.org/news","press":"source","time":"08:00",
             "published_at":"2026-11-26T08:00:00+09:00","observed_at":"2026-11-26T08:01:00+09:00"}
        def load(name,default=None):
            return {"feeds.json":f,"keywords.json":{},"stocks.json":{"예시기업":"000100"}}[name]
        # Use runtime date for retention logic.
        now=collect.datetime.datetime.now(collect.KST)
        row["observed_at"]=now.isoformat()
        row["published_at"]=now.isoformat()
        with tempfile.TemporaryDirectory() as tmp,patch.object(collect,"load",side_effect=load),patch.object(collect.sources,"fetch_portal",return_value=[]),patch.object(collect.sources,"fetch_rss",return_value=[row]),patch.object(collect.brief,"update") as brief:
            collect.main(tmp,False)
            data=json.loads((Path(tmp)/"news.json").read_text(encoding="utf-8"))
            stats=json.loads((Path(tmp)/"keyword_stats.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data),1)
            self.assertEqual(stats["publication_timestamp_count"],1)
            self.assertEqual(stats["sources_ok"],1)
            self.assertIn("empty",stats["sources_bad"])
            brief.assert_not_called()
    def test_featured_below_threshold_and_later_tag(self):
        f={"portals":{},"rss":{"news":"https://example.org/feed"},
           "categories":{"경제":["금리"]},"theme_sector":[],"event_words":[],
           "min_spec":.3,"store_min_score":100,"macro_score":6,"keep_days":5}
        now=collect.datetime.datetime.now(collect.KST).isoformat()
        def row(title,path):
            return {"title":title,"url":"https://example.org/"+path,"press":"source","time":"08:00",
                    "published_at":now,"observed_at":now}
        def load(name,default=None):
            return {"feeds.json":f,"keywords.json":{},"stocks.json":{}}[name]
        with tempfile.TemporaryDirectory() as tmp,patch.object(collect,"load",side_effect=load),patch.object(collect.sources,"fetch_rss") as fetch:
            fetch.return_value=[row("[특징주] 예시","tag"),row("일반 예시","drop"),row("금리 발표","later")]
            collect.main(tmp,False)
            path=Path(tmp)/"news.json"
            data={a["url"]:a for a in json.loads(path.read_text(encoding="utf-8"))}
            self.assertEqual(len(data),2)
            self.assertEqual(data["https://example.org/tag"]["score"],0)
            fetch.return_value=[row("[특징주] 금리 발표","later")]
            collect.main(tmp,False)
            data={a["url"]:a for a in json.loads(path.read_text(encoding="utf-8"))}
            self.assertEqual(data["https://example.org/later"]["title"],"금리 발표")
            self.assertEqual(data["https://example.org/later"]["featured_title"],"[특징주] 금리 발표")
            self.assertEqual(data["https://example.org/later"]["featured_observed_at"],now)
            stats=json.loads((Path(tmp)/"keyword_stats.json").read_text(encoding="utf-8"))
            self.assertEqual(stats["featured_raw_count"],1)
            self.assertEqual(stats["featured_retained_count"],2)
    def test_filter_audit_excludes_later_retained_duplicate(self):
        f={"portals":{},"rss":{"news":"https://example.org/feed"},
           "categories":{"경제":["금리"]},"theme_sector":[],"event_words":[],
           "min_spec":.3,"store_min_score":100,"macro_score":6,"keep_days":5}
        now=collect.datetime.datetime.now(collect.KST).isoformat()
        def row(title,path):
            return {"title":title,"url":"https://example.org/"+path,"press":"source","time":"08:00",
                    "published_at":now,"observed_at":now,"source_feed":"news","body":"PRIVATE_SENTINEL"}
        def load(name,default=None):
            return {"feeds.json":f,"keywords.json":{},"stocks.json":{"예시기업":"000100"}}[name]
        with tempfile.TemporaryDirectory() as tmp,patch.object(collect,"load",side_effect=load),patch.object(collect.sources,"fetch_rss",return_value=[
            row("일반 예시","drop"),row("예시기업 동향","later"),row("[특징주] 예시기업 동향","later"),row("일반 예시","drop")]):
            collect.main(tmp,False,True)
            raw=(Path(tmp)/"filter-audit.json").read_text(encoding="utf-8")
            audit=json.loads(raw)
            self.assertEqual(audit["rejected_unique"],1)
            self.assertEqual(audit["rows"][0]["url"],"https://example.org/drop")
            self.assertEqual(audit["review_sample"],audit["rows"])
            self.assertNotIn("PRIVATE_SENTINEL",raw)
            stats=json.loads((Path(tmp)/"keyword_stats.json").read_text(encoding="utf-8"))
            self.assertEqual(stats["score_filtered_unique_urls"],1)
            self.assertEqual(stats["raw_unique_not_retained"],1)
        with self.assertRaises(ValueError):collect.main(audit_filter=True)
if __name__=="__main__":
    unittest.main()
