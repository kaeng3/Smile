import unittest
from smile2.editorial_eval import sample,evaluate
def event(i,title):
    return {"id":str(i),"headline":title,"category":"기타","articles":[{"title":title,"url":"https://example.org/"+str(i),"press":"test"}]}
class EditorialEvalTests(unittest.TestCase):
    def setUp(self):
        self.data={"events":[event(1,"반도체 공급계약"),event(2,"알 수 없는 제목"),event(3,"은행 실적")]}
    def test_blind_repeatable(self):
        a=sample(self.data,2,"frozen-v1")
        b=sample({"events":list(reversed(self.data["events"]))},2,"frozen-v1")
        self.assertEqual(a,b)
        self.assertNotIn("category_id",a["items"][0])
        self.assertNotIn("classification",a["items"][0])
        self.assertEqual(len(sample(self.data,3,"seed","review")["items"]),1)
    def test_metrics_and_missing_labels(self):
        p=sample(self.data,3,"seed")
        gold={"1":"semi","2":"other","3":"economy"}
        labels={"sample_id":p["sample_id"],"labels":[{"content_id":x["content_id"],"category_id":gold[x["event_id"]],"basis":"title_only"} for x in p["items"]]}
        r=evaluate(self.data,p,labels)
        self.assertEqual(r["agreement"],0.6667)
        self.assertEqual(r["classified_agreement"],0.5)
        self.assertEqual(r["abstention_rate"],0.3333)
        self.assertEqual(r["per_category"]["finance"]["precision"],0)
        self.assertEqual(r["status"],"complete_label_set")
        labels["labels"].pop()
        self.assertEqual(evaluate(self.data,p,labels)["status"],"incomplete_labels")
    def test_changed_source_or_wrong_label_rejected(self):
        p=sample(self.data,3,"seed")
        labels={"sample_id":"wrong","labels":[]}
        with self.assertRaises(ValueError):evaluate(self.data,p,labels)
        labels["sample_id"]=p["sample_id"]
        self.data["events"][0]["headline"]="changed"
        with self.assertRaises(ValueError):evaluate(self.data,p,labels)
    def test_no_labels_not_accuracy(self):
        p=sample(self.data,3,"seed")
        r=evaluate(self.data,p,{"sample_id":p["sample_id"],"labels":[]})
        self.assertIsNone(r["agreement"])
        self.assertEqual(r["unlabeled"],3)
if __name__=="__main__":unittest.main()
