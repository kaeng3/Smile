import ast
import datetime
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class SyncCommentsTest(unittest.TestCase):
    def test_actions_does_not_push_from_sync_script(self):
        tree = ast.parse((ROOT / 'sync_and_push.py').read_text(encoding='utf-8'))
        calls = []
        subprocess = types.SimpleNamespace(run=lambda *args, **kwargs: calls.append(args))
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}):
            exec(compile(ast.Module(body=[tree.body[-1]], type_ignores=[]),
                         'sync_and_push.py', 'exec'),
                 dict(os=os, subprocess=subprocess, GIT_DIR=str(ROOT), date_str='20260909'))
        self.assertEqual(calls, [])

    def test_repairs_use_each_stock_price_even_with_global_price(self):
        # Load the real function without running network calls, cleanup, or git push.
        tree = ast.parse((ROOT / 'sync_and_push.py').read_text(encoding='utf-8'))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'load_scan_with_comments')
        for global_price in (None, 999999):
            for comment, expected in [
                ('원의 상승', '오늘 10,000원의 상승'),
                ('.0원으로 상승', '오늘 10,000원으로 상승'),
                ('전저점(0원)', '전저점(8,800원)'),
                ('전고점(0원)', '전고점(11,200원)'),
            ]:
                with self.subTest(global_price=global_price, comment=comment), tempfile.TemporaryDirectory() as tmp:
                    Path(tmp, 'scan.json').write_text(json.dumps([
                        {'code': '001', 'close': 10000},
                        {'code': '002', 'close': 20000},
                    ]), encoding='utf-8')
                    scope = dict(os=os, sys=sys, json=json, SCANNER_DIR=tmp,
                                 theme_db={}, now=datetime.datetime(2026, 9, 9),
                                 copy_chart=lambda code: '')
                    if global_price is not None:
                        scope['close'] = global_price
                    commentator = types.ModuleType('ai_commentator')
                    commentator.get_ai_commentary = lambda **kwargs: comment
                    exec(compile(ast.Module(body=[function], type_ignores=[]), 'sync_and_push.py', 'exec'), scope)
                    with patch.dict(sys.modules, {'ai_commentator': commentator}), patch.object(sys, 'path', sys.path.copy()):
                        rows = scope['load_scan_with_comments']('scan.json')
                    self.assertEqual(rows[0]['comment'], expected)
                    second = {'오늘 10,000원의 상승': '오늘 20,000원의 상승',
                              '오늘 10,000원으로 상승': '오늘 20,000원으로 상승',
                              '전저점(8,800원)': '전저점(17,600원)',
                              '전고점(11,200원)': '전고점(22,400원)'}[expected]
                    self.assertEqual(rows[1]['comment'], second)


if __name__ == '__main__':
    unittest.main()
