import unittest
from smile2.material_stage import material_stage,annotate_sections
class MaterialStageTests(unittest.TestCase):
    def event(self,*titles):
        return {"id":"x","articles":[{"title":t,"url":"https://example.org/"+str(i)} for i,t in enumerate(titles)]}
    def keys(self,r):return {x["id"] for x in r["signals"]}
    def test_application_not_approval(self):
        r=material_stage(self.event("신약 허가 신청"))
        self.assertIn("application",self.keys(r))
        self.assertTrue(r["mixed_stage_cues"])
        self.assertEqual(r["status"],"unverified")
    def test_negation_and_risk_retained(self):
        r=material_stage(self.event("인수설 사실무근","계약 체결 후 계약 해지","유상증자 결정"))
        self.assertTrue({"rumor","denial","negative","contract","risk"}<=self.keys(r))
        self.assertTrue(r["review_required"])
    def test_empty_not_confirmed(self):
        r=material_stage(self.event("기업 소식"))
        self.assertEqual(r["signals"],[])
        self.assertEqual(r["status"],"unverified")
    def test_annotations_preserve_events(self):
        e=self.event("법안 통과 보도")
        a=annotate_sections([{"id":"policy","count":1,"events":[e]}])
        self.assertEqual(a[0]["count"],1)
        self.assertNotIn("material_stage",e)
        self.assertEqual(a[0]["events"][0]["material_stage"]["evidence_type"],"title_only")
if __name__=="__main__":unittest.main()
