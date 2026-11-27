import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from smile2.pipeline import generate,ASSETS,JSON_NAMES

class PipelineTests(unittest.TestCase):
    def test_allowlist_and_outputs(self):
        rows=[{"title":"공개 예시 뉴스","url":"https://example.org/news","seen":"2026-11-26 06:00",
               "content":"PRIVATE_SENTINEL","api_key":"SECRET_SENTINEL"}]
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"preview"
            d=generate(rows,date(2026,11,26),date(2026,11,25),out)
            self.assertFalse(d["history_included"])
            self.assertEqual(set(p.name for p in out.iterdir()),set(ASSETS+JSON_NAMES))
            for p in out.glob("*.json"):
                s=p.read_text(encoding="utf-8")
                self.assertNotIn("PRIVATE_SENTINEL",s)
                self.assertNotIn("SECRET_SENTINEL",s)
            self.assertEqual(json.loads((out/"brief-pre.json").read_text())["unknown_articles"],1)
            with self.assertRaises(FileExistsError):
                generate(rows,date(2026,11,26),date(2026,11,25),out)
    def test_additional_media_separate_and_as_of(self):
        base={"title":"기존 기사","url":"https://example.org/base","seen":"2026-11-26 06:00"}
        media={"title":"추가 기사","url":"https://news.google.com/rss/articles/a","seen":"2026-11-26 06:10",
               "published_at":"2026-11-26T06:00:00+09:00","source_kind":"media_probe_aggregator"}
        late={**media,"url":"https://news.google.com/rss/articles/b","seen":"2026-11-26 07:01"}
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"preview"
            generate([base],date(2026,11,26),date(2026,11,25),out,media_rows=[media,late])
            d=json.loads((out/"brief-pre.json").read_text())
            self.assertEqual(d["published_articles"],0)
            self.assertEqual(d["supplemental_media"]["published_articles"],1)
            self.assertEqual(d["supplemental_media"]["excluded_late_or_after_cutoff"],1)
            e=json.loads((out/"events.json").read_text())
            self.assertEqual(e["unique_url_count"],3)
            self.assertEqual(d["supplemental_media"]["events"][0]["articles"][0]["link_kind"],"aggregator")
    def test_session_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                generate([],date(2026,11,26),date(2026,11,26),Path(tmp)/"preview")
if __name__=="__main__":
    unittest.main()

class EditorialCarryTests(unittest.TestCase):
    def test_prior_session_delays_go_through_next_premarket_selection(self):
        from smile2.briefing import briefing
        def article(key, published, observed):
            return {"title":key,"url":"https://example.org/"+key,
                    "published_at":published+"+09:00","observed_at":observed+"+09:00"}
        rows=[
            article("late","2026-11-26T12:00:00","2026-11-26T18:00:00"),
            article("gap","2026-11-26T07:30:00","2026-11-26T07:45:00"),
            article("already-covered","2026-11-26T12:00:00","2026-11-26T12:30:00"),
            article("after-pre-cutoff","2026-11-26T13:00:00","2026-11-27T07:01:00"),
            article("after-close","2026-11-26T16:00:00","2026-11-26T16:30:00"),
        ]
        result=briefing(rows,date(2026,11,27),date(2026,11,26),"pre",include_late_pre=True)
        self.assertEqual({a["url"].rsplit("/",1)[-1] for e in result["events"] for a in e["articles"]},
                         {"late","gap","after-close"})
