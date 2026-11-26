import json
import unittest
from smile2.ai_runner import run
from smile2.news_engine import build
DATA=build([{"title":"가나다 기업 공급계약 신청","url":"https://example.org/a","seen":"2026-11-26 12:00","score":9}])
class RunnerTests(unittest.TestCase):
    def test_budget_blocks_generation(self):
        calls=[]
        def fake(m,op,p,k):
            calls.append(op)
            return {"totalTokens":500}
        r=run(DATA,"gemini-test","dummy","1","2","0.000001",transport=fake)
        self.assertEqual(calls,["countTokens"])
        self.assertEqual(r["attempted"],0)
    def test_valid_draft_local(self):
        def fake(m,op,p,k):
            if op=="countTokens":return {"totalTokens":500}
            from smile2.analysis_queue import queue
            pid=queue(DATA,5,60000)["packets"][0]["packet_id"]
            result={"packet_id":pid,"claims":[{"text":"신청 보도","kind":"headline_report","url":"https://example.org/a","quote":"공급계약 신청"}]}
            return {"usageMetadata":{"promptTokenCount":500,"candidatesTokenCount":100},
                    "candidates":[{"finishReason":"STOP","content":{"parts":[{"text":json.dumps(result)}]}}]}
        r=run(DATA,"gemini-test","dummy","1","2","0.01",transport=fake)
        self.assertEqual(r["drafts"][0]["status"],"human_review_required")
        self.assertEqual(r["attempted"],1)
    def test_failed_request_no_retry(self):
        calls=[]
        def fake(m,op,p,k):
            calls.append(op)
            if op=="countTokens":return {"totalTokens":500}
            raise RuntimeError("simulated")
        r=run(DATA,"gemini-test","dummy","1","2","0.01",transport=fake)
        self.assertEqual(calls,["countTokens","generateContent"])
        self.assertEqual(len(r["errors"]),1)
    def test_invalid_parameters(self):
        for price in ("NaN","0","-1"):
            with self.assertRaises(ValueError):
                run(DATA,"gemini-test","dummy",price,"2","0.01")
        with self.assertRaises(ValueError):
            run(DATA,"gemini-flash-latest","dummy","1","2","0.01")
if __name__=="__main__":unittest.main()
