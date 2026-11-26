from datetime import date,timedelta
import json
from pathlib import Path
import tempfile
import unittest
from smile2.local_audit import audit
DAY=date(2026,11,26)
def data():
    return {"schema":1,"source":"DAUM_KRX_REGULAR","records":[
       {"day":(DAY-timedelta(days=4-i)).isoformat(),"open":100,"high":110,"low":90,"close":105,"volume":1000,"value":102000}
       for i in range(5)]}
class AuditTests(unittest.TestCase):
    def test_counts_and_privacy(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            def write(code,x): (root/(code+".json")).write_text(json.dumps(x),encoding="utf-8")
            write("000100",data())
            d=data();d["records"][-1]["value"]=0;write("000200",d)
            d=data();d["records"][-1]["value"]=200000;write("000300",d)
            d=data();d["records"].pop();write("000400",d)
            d=data();d["source"]="UNKNOWN";write("000500",d)
            (root/"000600.json").write_text("invalid JSON")
            (root/"config.json").write_text("SECRET_SENTINEL")
            r=audit(root,DAY,5,False)
            self.assertEqual(r["files"],6)
            self.assertEqual(r["window_passed"],1)
            self.assertEqual(sum(r["rejected"].values()),5)
            self.assertEqual(r["rejected"]["stale"],1)
            self.assertEqual(r["rejected"]["turnover_outside_price_range"],1)
            self.assertNotIn("000100",str(r))
            self.assertNotIn("SECRET_SENTINEL",str(r))
    def test_missing_directory(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):audit(Path(t)/"missing",DAY,5,False)
if __name__=="__main__":unittest.main()
