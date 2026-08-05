# -*- coding: utf-8 -*-
"""
run_cloud_scan.py
GitHub Actions에서 매일 스케줄러로 실행되는 진입점 스크립트.
"""
import os
import sys
import datetime
import subprocess

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLOUD_SCANNER_DIR = os.path.join(BASE_DIR, 'cloud_scanner')

now = datetime.datetime.now()
date_str = now.strftime('%Y%m%d')

print(f"==========================================")
print(f" [{date_str}] GitHub Actions 클라우드 스캔 시작")
print(f"==========================================")

os.environ['PYTHONPATH'] = CLOUD_SCANNER_DIR
sys.path.insert(0, CLOUD_SCANNER_DIR)

print("\n[STEP 1/3] 양음양 / v2 / 포도시 스캔 진행 중...")
subprocess.run([sys.executable, "-u", "-X", "utf8", "run_full_rescan.py"], cwd=CLOUD_SCANNER_DIR, check=True)

print("\n[STEP 2/3] 500억봉 / 150억봉 스캔 진행 중...")
subprocess.run([sys.executable, "-u", "-X", "utf8", "run_scan_and_report.py"], cwd=CLOUD_SCANNER_DIR, check=True)

print("\n[STEP 3/3] scan_history.json 갱신 및 파일 정리 진행 중...")
subprocess.run([sys.executable, "-u", "-X", "utf8", "sync_and_push.py"], cwd=BASE_DIR, check=True)

print("\n모든 스캔이 성공적으로 완료되었습니다!")
