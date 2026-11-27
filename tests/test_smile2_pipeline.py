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

class EditorialDateAndIncidentTests(unittest.TestCase):
    def test_premarket_main_is_today_and_clusters_same_breach(self):
        headlines=[
            "올리브영, 해킹 공격에 직원·고객 포함 790명 이름·연락처 등 개인정보 유출",
            "CJ올리브영, 해킹 당했다…임직원·고객 790명 개인정보 유출",
            "CJ올리브영, 업무시스템 해킹으로 임직원·고객 개인정보 유출",
            "CJ올리브영, 해킹으로 임직원·소비자 등 790명 개인정보 유출",
            "CJ올리브영 업무 시스템 외부 침입…총 790명 개인정보 유출",
            "CJ올리브영, 해킹으로 123명 개인정보 유출",
            "다른기업 해킹으로 790명 개인정보 유출",
        ]
        rows=[{"title":title,"url":"https://example"+str(i)+".org/article","press":"매체"+str(i),
               "published_at":"2026-11-27T04:00:00+09:00","seen":"2026-11-27 04:10"}
              for i,title in enumerate(headlines)]
        rows.append({"title":"전날 금융 뉴스","url":"https://example.org/previous",
                     "published_at":"2026-11-26T21:00:00+09:00","seen":"2026-11-26 21:10"})
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"preview"
            generate(rows,date(2026,11,27),date(2026,11,26),out)
            data=json.loads((out/"editorial-pre.json").read_text(encoding="utf-8"))
            events=[e for section in data["sections"] for e in section["events"]]
            self.assertEqual([e["article_count"] for e in events],[5])
            raw=json.loads((out/"events.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(e["article_count"] for e in raw["events"]),[1,1,1,5])
            self.assertTrue(all(a["published_at"].startswith("2026-11-27")
                                for e in events for a in e["articles"]))

class PremarketSignalTests(unittest.TestCase):
    def test_selection_uses_official_or_distinct_direct_hourly_coverage(self):
        from smile2.editorial_evidence import premarket_signals
        def article(press,host,title,time="05:00",kind="source_url"):
            return {"press":press,"url":"https://"+host+"/news","title":title,
                    "published_at":"2026-11-27T"+time+":00+09:00","link_kind":kind}
        foundation=article("A","a.example","갑사 신규 계약")
        events=[
            {"id":"independent","articles":[foundation,article("B","b.example","갑사 공급 계약 보도","05:30")]},
            {"id":"same-title","articles":[foundation,article("B","b.example","갑사 신규 계약","05:30")]},
            {"id":"slow","articles":[foundation,article("B","b.example","갑사 공급 계약 보도","06:01")]},
            {"id":"aggregator","articles":[foundation,article("B","b.example","갑사 공급 계약 보도","05:30","aggregator")]},
            {"id":"official","articles":[{**foundation,"source_kind":"official_disclosure","source_feed":"DART",
                         "url":"https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261127000001"}]},
        ]
        result=premarket_signals([{"id":"corp","count":len(events),"events":events}])[0]
        self.assertEqual([event["id"] for event in result["events"]],["official","independent"])
        self.assertEqual(result["count"],2)
