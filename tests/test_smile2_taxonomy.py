import unittest
from smile2.taxonomy import classify,group,audit,CATEGORIES
class TaxonomyTests(unittest.TestCase):
    def test_real_snapshot_regressions(self):
        # Short title fragments from 2026-11-27 Pages snapshot, manually labeled.
        examples=[
          ("화장품 경쟁 치열한 폴란드도 뚫었다","IP / 엔터","consumer"),
          ("카카오게임즈, 신작 '오딘Q' 내년 1월 26일 출시 확정","코인 / STO","ent"),
          ("유니테스트, 마이크론 인도와 반도체 123억 규모 공급계약 체결","M&A / 공시","semi"),
          ("아센디오, 9억원 규모 화장품 공급계약","M&A / 공시","consumer"),
          ("美수출통제 강화에 삼성전자·TSMC 中반도체 출하 일부 중단","미중 패권","rivalry"),
          ("샤페론, 폐섬유증 치료용 조성물 유럽 특허 등록","BIO / 의료","bio"),
          ("스페이스X, 우주 데이터센터 위성 승인","국방 / 우주","space"),
          ("우원개발, 1528억원 규모 GTX-C노선 공사 수주","건설 / 대북","infra"),
          ("코스피 5000선 붕괴…반도체 급락, 화장품·여행주는 강세","IP / 엔터","economy"),
        ]
        for title,old,expected in examples:
            with self.subTest(title=title):
                self.assertEqual(classify(title,old)["category_id"],expected)
    def test_ambiguous_and_unknown(self):
        self.assertTrue(classify("반도체와 배터리 투자 확대")["review_required"])
        self.assertEqual(classify("오늘의 소식","반도체")["category_id"],"other")
        self.assertEqual(classify("STOP 계획")["category_id"],"other")
    def test_group_no_dropped_or_double_events(self):
        events=[{"id":"a","headline":"화장품 수출 증가","category":"정치"},
                {"id":"b","headline":"새 소식","category":"기타"}]
        sections=group(events)
        self.assertEqual(len(sections),26)
        self.assertEqual(sum(x["count"] for x in sections),2)
        self.assertEqual(sorted(e["id"] for s in sections for e in s["events"]),["a","b"])
        self.assertEqual(events[0]["category"],"정치")
        self.assertEqual(audit(events)["total"],2)
if __name__=="__main__":unittest.main()
