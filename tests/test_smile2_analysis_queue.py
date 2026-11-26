import unittest
from smile2.news_engine import build
from smile2.analysis_queue import queue,validate
def data():
    return build([{"title":"예시 기업 공급계약 신청","url":"https://example.org/a","seen":"2026-11-26 12:00","score":9},
                  {"title":"별개 기업 실적 발표","url":"https://example.org/b","seen":"2026-11-26 12:00","score":2}])
class QueueTests(unittest.TestCase):
    def test_limit_and_priority(self):
        q=queue(data(),1,2000)
        self.assertEqual(len(q["packets"]),1)
        self.assertLessEqual(q["used_packet_chars"],2000)
        self.assertEqual(q["packets"][0]["evidence"][0]["url"],"https://example.org/a")
    def test_valid_citation_not_truth(self):
        p=queue(data(),1,2000)["packets"][0]
        d={"packet_id":p["packet_id"],"claims":[{"text":"제목상 신청 보도","kind":"headline_report","url":"https://example.org/a","quote":"공급계약 신청"}]}
        self.assertEqual(validate(p,d)["status"],"human_review_required")
        d["claims"][0]["quote"]="계약 체결"
        with self.assertRaises(ValueError):
            validate(p,d)
    def test_unprovided_url(self):
        p=queue(data(),1,2000)["packets"][0]
        with self.assertRaises(ValueError):
            validate(p,{"packet_id":p["packet_id"],"claims":[{"text":"예시","kind":"inference","url":"https://other.example","quote":"공급계약"}]})
    def test_packet_integrity(self):
        p=queue(data(),1,2000)["packets"][0]
        p["task"]="changed"
        with self.assertRaises(ValueError):
            validate(p,{"packet_id":p["packet_id"],"claims":[]})
if __name__=="__main__":
    unittest.main()
