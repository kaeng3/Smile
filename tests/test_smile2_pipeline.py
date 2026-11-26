import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from smile2.pipeline import generate,ASSETS,JSON_NAMES

class PipelineTests(unittest.TestCase):
    def test_allowlist_and_outputs(self):
        rows=[{"title":"공개 예시 뉴스","url":"https://example.org/news","seen":"2026-11-26 08:00",
               "content":"PRIVATE_SENTINEL","api_key":"SECRET_SENTINEL"}]
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/"preview"
            d=generate(rows,date(2026,11,26),date(2026,11,25),out)
            self.assertFalse(d["history_included"])
            self.assertEqual(set(p.name for p in out.iterdir()),set(ASSETS+JSON_NAMES))
            for p in out.glob("*.json"):
                s=p.read_text(encoding="utf-8")
                self.assertNotIn("PRIVATE_SENTINEL",s)
                self.assertNotIn("SECRET_SENTINEL",s)
            self.assertEqual(json.loads((out/"brief-pre.json").read_text())["unknown_articles"],1)
            with self.assertRaises(FileExistsError):
                generate(rows,date(2026,11,26),date(2026,11,25),out)
    def test_session_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                generate([],date(2026,11,26),date(2026,11,26),Path(tmp)/"preview")
if __name__=="__main__":
    unittest.main()
