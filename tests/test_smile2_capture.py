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
if __name__=="__main__":
    unittest.main()
