import csv
from datetime import date
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from smile2.turnover import lookup,audit,validate_row
DAY=date(2026,11,26)
META={"adjusted":False,"requested_start":"2026-11-01","covered_end":"2026-11-26"}
ROW={"date":"2026-11-26","open":100,"high":110,"low":90,"close":108,"volume":1000,"trading_value":103000}
class TurnoverTests(unittest.TestCase):
    def test_reported_not_proxy(self):
        r=validate_row(ROW,DAY,META)
        self.assertEqual(r["reported_value_won"],103000)
        self.assertEqual(r["estimated_close_times_volume_won"],"108000")
        self.assertEqual(r["session_scope"],"unverified")
    def test_reject_invalid_or_adjusted(self):
        for row,meta in (({**ROW,"trading_value":0},META),({**ROW,"trading_value":120000},META),
                         (ROW,{**META,"adjusted":True}),(ROW,{**META,"covered_end":"2026-11-25"}),
                         ({**ROW,"trading_value":"NaN"},META)):
            with self.assertRaises(ValueError):validate_row(row,DAY,meta)
    def test_read_cache_without_auth(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);d=root/"daily";d.mkdir()
            (d/"000100.meta.json").write_text(json.dumps(META))
            with gzip.open(d/"000100.csv.gz","wt",encoding="utf-8",newline="") as f:
                w=csv.DictWriter(f,fieldnames=list(ROW));w.writeheader();w.writerow(ROW)
            (root/".kis_token.json").write_text("SECRET_SENTINEL")
            self.assertEqual(lookup(root,"000100",DAY)["reported_value_won"],103000)
            r=audit(root,DAY)
            self.assertEqual(r["usable_reported_values"],1)
            self.assertNotIn("SECRET_SENTINEL",str(r))
            (d/"000100.meta.json").write_text(json.dumps({**META,"adjusted":True}))
            self.assertEqual(audit(root,DAY)["usable_reported_values"],0)
if __name__=="__main__":unittest.main()
