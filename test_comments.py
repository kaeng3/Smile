# -*- coding: utf-8 -*-
import json
import sys
import time
from ai_commentator import get_ai_commentary

with open('scan_results_20260714.json', 'r', encoding='utf-8') as f:
    stocks = json.load(f)

for s in stocks:
    comment = get_ai_commentary(s['code'], s['name'], s['pattern'], s['close'], s['rate'], s['match_type'], '2026-07-14')
    msg = f"{s['code']} {s['name']}: {comment}\n"
    sys.stdout.buffer.write(msg.encode('utf-8'))
    time.sleep(1.0)
