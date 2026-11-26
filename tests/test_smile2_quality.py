import unittest
from smile2.news_engine import build
from smile2.quality import review,signature
def row(n,title):
    return {"title":title,"url":"https://example.org/"+str(n),"seen":"2026-11-26 12:00","score":10}
class QualityTests(unittest.TestCase):
    def test_quantity_and_sign(self):
        self.assertNotEqual(signature("매출 +10%"),signature("매출 -10%"))
    def test_review_only(self):
        d=build([row(1,"가나다기업 대규모 반도체공장 증설 추진 계획 발표"),
                 row(2,"가나다기업 대규모 반도체 공장 증설 추진 계획 공개")])
        self.assertEqual(d["event_count"],2)
        r=review(d)
        self.assertEqual(r["review_pair_count"],1)
        self.assertEqual(r["review_pairs"][0]["status"],"human_review_required")
    def test_stage_conflict(self):
        d=build([row(1,"가나다기업 대규모 반도체 공장 증설 승인 신청"),
                 row(2,"가나다기업 대규모 반도체 공장 증설 승인 완료")])
        self.assertEqual(d["event_count"],2)
        self.assertEqual(review(d)["review_pair_count"],0)
    def test_signed_values_not_merged(self):
        d=build([row(1,"기업 실적 매출 +10%"),row(2,"기업 실적 매출 -10%")])
        self.assertEqual(d["event_count"],2)
if __name__=="__main__":
    unittest.main()
