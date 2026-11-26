import json
import unittest
from datetime import datetime,timedelta,timezone
from smile2.free_ai import execute,MODEL
from smile2.analysis_queue import queue
from smile2.news_engine import build
DATA=build([{"title":"예시 기업 공급계약 신청","url":"https://example.org/a","seen":"2026-11-26 12:00","score":9}])
NOW=datetime(2026,11,26,20,tzinfo=timezone.utc)
class FreeTests(unittest.TestCase):
    def fake(self,model,op,payload,key):
        self.assertEqual(model,MODEL)
        self.assertEqual(op,"generateContent")
        self.assertNotIn("tools",payload)
        packet=queue(DATA,30,60000,max_articles=3)["packets"][0]
        draft={"packet_id":packet["packet_id"],"claims":[{"text":"신청 보도","kind":"headline_report","url":"https://example.org/a","quote":"공급계약 신청"}]}
        return {"candidates":[{"finishReason":"STOP","content":{"parts":[{"text":json.dumps(draft)}]}}]}
    def test_reservation_first_and_dedup(self):
        ledger={"entries":[]}; states=[]
        def persist(d):states.append(d["entries"][-1]["status"])
        def transport(*args):
            self.assertEqual(states,["reserved"])
            return self.fake(*args)
        r=execute(DATA,ledger,"dummy",NOW,persist,transport)
        self.assertEqual(r["status"],"human_review_required")
        self.assertEqual(states,["reserved","success"])
        r=execute(DATA,ledger,"dummy",NOW+timedelta(minutes=11),persist,transport)
        self.assertEqual(r["status"],"no_unseen_candidate")
    def test_failure_stops_day(self):
        ledger={"entries":[]}
        def fail(*a):raise RuntimeError()
        r=execute(DATA,ledger,"dummy",NOW,lambda _:None,fail)
        self.assertEqual(r["status"],"failed_no_retry")
        r=execute(DATA,ledger,"dummy",NOW+timedelta(hours=1),lambda _:None,fail)
        self.assertEqual(r["attempted"],0)
    def test_persist_failure_no_call(self):
        def fail(*a):raise RuntimeError("persist")
        def no_call(*a):self.fail("must not call API")
        with self.assertRaises(RuntimeError):
            execute(DATA,{"entries":[]},"dummy",NOW,fail,no_call)
    def test_local_cap(self):
        entries=[{"at":(NOW-timedelta(minutes=20+i)).isoformat(),"status":"success","event_id":str(i),"packet_id":str(i)} for i in range(3)]
        r=execute(DATA,{"entries":entries},"dummy",NOW,lambda _:None,self.fake)
        self.assertEqual(r["status"],"daily_local_cap")
if __name__=="__main__":unittest.main()
