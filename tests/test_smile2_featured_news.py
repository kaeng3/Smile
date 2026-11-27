import unittest
from datetime import date,time
from news_feed.sources import is_featured_title
from smile2.featured_news import featured_editions
class FeaturedTests(unittest.TestCase):
    def test_marker(self):
        for s in ("[특징주] ABC","［특징주］ ABC","[ 특징주 ] ABC","&#91;특징주&#93; ABC","[속보] [특징주] ABC"):
            self.assertTrue(is_featured_title(s),s)
        for s in ("특징주 관련 분석","급등주 ABC","[특징주 분석] ABC","[단독] ABC",None):
            self.assertFalse(is_featured_title(s),s)
    def test_tagged_before_clustering_and_cutoffs(self):
        def row(t,u,seen="2026-11-27T10:00:00+09:00",pub="2026-11-27T09:55:00+09:00",score=1):
            return {"title":t,"url":"https://example.org/"+u,"observed_at":seen,"published_at":pub,"score":score,"cat":"기타"}
        rows=[row("ABC 반도체 계약","same",score=100),row("[특징주] ABC 반도체 계약","same"),
              row("[특징주] DEF 게임","unknown",pub=None),
              row("[특징주] GHI 자동차","late",seen="2026-11-27T18:01:00+09:00"),
              row("급등주 XYZ","not-tagged")]
        f=featured_editions(rows,date(2026,11,27),date(2026,11,26),"post",time(15,30))
        self.assertEqual(f["article_count"],2)
        self.assertEqual(f["known_article_count"],1)
        self.assertEqual(f["unknown_article_count"],1)
        self.assertEqual(f["events"][0]["headline"],"[특징주] ABC 반도체 계약")
        self.assertEqual(f["events"][0]["classification"]["category_id"],"semi")
        self.assertEqual(f["unknown_events"][0]["headline"],"[특징주] DEF 게임")
    def test_late_marker_not_backdated(self):
        r={"title":"ABC 반도체 계약","url":"https://example.org/late-marker",
           "observed_at":"2026-11-27T06:00:00+09:00","published_at":"2026-11-27T05:55:00+09:00",
           "featured_title":"[특징주] ABC 반도체 계약","featured_observed_at":"2026-11-27T09:05:00+09:00"}
        d,p=date(2026,11,27),date(2026,11,26)
        self.assertEqual(featured_editions([r],d,p,"pre",time(15,30))["article_count"],0)
        # Publication belongs to pre; newly found marker must not imply post publication.
        self.assertEqual(featured_editions([r],d,p,"post",time(15,30))["article_count"],0)
        r["featured_observed_at"]="2026-11-27T06:30:00+09:00"
        self.assertEqual(featured_editions([r],d,p,"pre",time(15,30))["article_count"],1)
if __name__=="__main__":unittest.main()
