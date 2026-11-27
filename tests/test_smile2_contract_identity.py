import unittest
from smile2.news_engine import build
from smile2.taxonomy import classify
TITLES=["넥사다이내믹스, 755억원 AI 서버 공급 본계약…하반기 누적 수주 1082억",
        "넥사다이내믹스, AI 서버 755억 추가 수주…하반기 누적 1000억 넘어",
        "넥사다이내믹스, 한 달여 만에 AI 서버 755억 후속 수주"]
def row(t,i,code="351320",pub="2026-11-27T09:40:00+09:00"):
    return {"title":t,"url":"https://example.org/"+str(i),"stocks":[["넥사다이내믹스",code]],
            "published_at":pub,"observed_at":"2026-11-27T13:00:00+09:00","press":"출처"+str(i)}
class ContractIdentityTests(unittest.TestCase):
    def test_user_report(self):
        data=build([row(t,i) for i,t in enumerate(TITLES)])
        self.assertEqual(data["event_count"],1)
        self.assertEqual(data["events"][0]["article_count"],3)
        self.assertEqual(classify(data["events"][0]["headline"])["category_id"],"tech")
    def test_nonduplicate_guardrails(self):
        variants=[row("넥사다이내믹스, AI 서버 756억 추가 수주",1),
                  row("넥사다이내믹스, AI 서버 755억 계약 해지",1),
                  row("넥사다이내믹스, AI 서버 755억 계약 추진",1),
                  row("넥사다이내믹스, AI 서버 755억 수주 정정",1),
                  row("넥사다이내믹스, 미국 AI 서버 755억 수주",1),
                  row("넥사다이내믹스, AI 서버 755억 추가 수주",1,code="000100"),
                  row("넥사다이내믹스, AI 서버 755억 추가 수주",1,pub="2026-11-26T09:40:00+09:00"),
                  row("넥사다이내믹스, AI 서버 755억 추가 수주",1,pub=None)]
        for v in variants:
            with self.subTest(title=v["title"],code=v["stocks"],pub=v["published_at"]):
                self.assertEqual(build([row(TITLES[0],0),v])["event_count"],2)
if __name__=="__main__":unittest.main()
