import json
import tempfile
import unittest
from pathlib import Path
from smile2.site_release import release,add_entry,fallback
from smile2.pipeline import ASSETS,JSON_NAMES
SESSION={"calendar":"XKRX","day":"2026-11-26","previous":"2026-11-25","open":"2026-11-26T09:00:00+09:00","close":"2026-11-26T15:30:00+09:00","previous_close":"2026-11-25T15:30:00+09:00"}
class ReleaseTests(unittest.TestCase):
    def test_release_allowlist_and_legacy_preserved(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)
            (root/"index.html").write_text("<header>legacy</header><main>scanner</main>")
            (root/"news_feed").mkdir()
            (root/"news_feed"/"news.json").write_text(json.dumps([{"title":"test","url":"https://example.org/a","seen":"2026-11-26 08:00","content":"PRIVATE_SENTINEL"}]))
            (root/"smile2").mkdir()
            (root/"smile2"/"internal.py").write_text("internal")
            release(root,session=SESSION)
            self.assertEqual(set(p.name for p in (root/"smile2").iterdir()),set(ASSETS+JSON_NAMES))
            self.assertNotIn("PRIVATE_SENTINEL",(root/"smile2"/"events.json").read_text())
            add_entry(root);add_entry(root)
            self.assertIn('href="./smile2/"',(root/"index.html").read_text())
            self.assertEqual((root/"smile2"/"index.html").read_text(),(root/"smile2"/"editorial.html").read_text())
            self.assertEqual((root/"smile2"/"brief.html").read_text(),(root/"smile2"/"editorial.html").read_text())
            self.assertIn("app.js",(root/"smile2"/"search.html").read_text())
            self.assertIn("<main>scanner</main>",(root/"index.html").read_text())
            self.assertEqual((root/"index.html").read_text().count('id="smile2-entry"'),1)
    def test_failure_preserves_legacy(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/"index.html").write_text("<header>legacy</header>")
            with self.assertRaises(FileNotFoundError):release(root,session=SESSION)
            fallback(root);add_entry(root)
            self.assertTrue((root/"smile2"/"index.html").exists())
            self.assertIn("legacy",(root/"index.html").read_text())
if __name__=="__main__":unittest.main()
