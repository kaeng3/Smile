import unittest
from news_feed.retention_rules import retention_reasons
class RetentionRulesTests(unittest.TestCase):
    def test_reviewed_development_examples(self):
        for title,k in [
            ("자회사 유동성 위기에 기업회생 기로","corporate"),
            ("주식 700억원어치 추가취득","corporate"),
            ("바이오 기업과 오픈이노베이션 추진","biotech"),
            ("희귀 혈관염 3상서 대등","biotech"),
            ("코스닥 급등에 매수 사이드카","market"),
            ("전기차 전환 목표","policy")]:
            self.assertIn(k,retention_reasons(title))
    def test_no_blanket_inclusion(self):
        for title in ("일반 예시","[인사] 예시기업","[표] 코스닥 외국인 순매수도 상위종목","오늘의 날씨"):
            self.assertEqual(retention_reasons(title),[])
if __name__=="__main__":unittest.main()
