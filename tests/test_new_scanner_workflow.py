from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "new_scanner.yml"


class NewScannerWorkflowTests(unittest.TestCase):
    def test_schedule_runtime_secrets_cache_and_pages_contract(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("cron: '5 7 * * 1-5'", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn('group: "pages"', text)
        self.assertIn("python-version: '3.12'", text)
        for name in ("KIS_APP_KEY", "KIS_APP_SECRET", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            self.assertIn(f"secrets.{name}", text)
        self.assertIn("new_scanner/data/cache", text)
        self.assertIn("hashFiles('new_scanner/config/scanner.yaml')", text)
        self.assertIn("python -m pytest tests -q", text)
        self.assertIn("working-directory: new_scanner", text)
        self.assertIn("${{ github.workspace }}/new_scanner/src", text)
        self.assertIn("exchange-calendars==4.13.2", text)
        self.assertIn("actions/deploy-pages@v4", text)
        self.assertIn("actions/cache/restore@v4", text)
        self.assertIn("actions/cache/save@v4", text)
        self.assertIn("github.run_attempt", text)
        self.assertLess(text.index("Run daily scanner"), text.index("Save scanner cache and notification receipt"))
        self.assertLess(text.index("Save scanner cache and notification receipt"), text.index("Commit scanner history"))
        self.assertIn("git archive HEAD", text)
        self.assertNotIn("path: '.'", text)

    def test_commit_scope_and_private_runtime_files(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("git add new_scanner/results/history.json", text)
        self.assertNotIn("git add .", text)
        for path in ("new_scanner/data/cache/.kis_token.json", "new_scanner/state/sent.json"):
            result = subprocess.run(["git", "check-ignore", "--quiet", path], cwd=ROOT)
            self.assertEqual(result.returncode, 0, path)

    def test_no_secret_or_token_files_are_tracked(self):
        tracked = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
        normalized = {item.replace("\\", "/") for item in tracked}
        self.assertFalse(any(Path(item).name == ".env" for item in normalized))
        self.assertFalse(any(item.endswith(".kis_token.json") for item in normalized))
        self.assertNotIn("new_scanner/state/sent.json", normalized)


if __name__ == "__main__":
    unittest.main()
