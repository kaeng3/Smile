import json
from pathlib import Path
import tempfile
import unittest

from cleanup_artifacts import cleanup_artifacts, retention_cutoff


class RetentionTest(unittest.TestCase):
    def test_five_sessions_exclude_weekends_and_krx_holiday(self):
        self.assertEqual(retention_cutoff('2026-09-09'), '20260903')
        self.assertEqual(retention_cutoff('2026-08-18'), '20260811')
        self.assertEqual(retention_cutoff('2026-09-13'), '20260907')

    def test_cleanup_keeps_boundary_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = ['charts/20260902/001.png',
                   'cloud_scanner/charts/20260902/001.png',
                   'cloud_scanner/scan_results_yey_20260902.json',
                   '김일청의_양음양기법_20260902.pdf',
                   'cloud_scanner/charts/000002.png']
            keep = ['charts/20260903/001.png', 'charts/logo.png',
                    'cloud_scanner/charts/000001.png',
                    'cloud_scanner/stock_ohlcv_cache.db',
                    'cloud_scanner/scan_results_yey_latest.json',
                    'notes_20260902.pdf', 'charts/20990101/future.png']
            for name in old + keep:
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('{}', encoding='utf-8')
            recent = root / 'cloud_scanner/scan_results_integrated_20260903.json'
            recent.write_text(json.dumps({'scan_results': [], 'ma_stocks': [{'code': '000001'}]}))
            history = root / 'scan_history.json'
            history.write_text(json.dumps({'20260902': {}, '20260903': {
                'b500m': [{'code': '000001', 'chart': 'charts/20260902/001.png'}]}}))
            cleanup_artifacts(root, '2026-09-09', dry_run=True)
            self.assertTrue(all((root / p).exists() for p in old))
            self.assertIn('20260902', json.loads(history.read_text()))
            cleanup_artifacts(root, '2026-09-09')
            self.assertTrue(all(not (root / p).exists() for p in old))
            self.assertTrue(all((root / p).exists() for p in keep))
            self.assertEqual(list(json.loads(history.read_text())), ['20260903'])
            self.assertEqual(json.loads(history.read_text())['20260903']['b500m'][0]['chart'], '')
            self.assertEqual(cleanup_artifacts(root, '2026-09-09'), [])


if __name__ == '__main__':
    unittest.main()
