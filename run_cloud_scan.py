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

debug_lines = []

def run_step(step_label, args, cwd):
    print(f"\n{step_label}")
    result = subprocess.run(
        [sys.executable, "-u", "-X", "utf8"] + args,
        cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace'
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    if result.returncode != 0:
        debug_lines.append(f"=== {step_label} 실패 (exit {result.returncode}) ===")
        debug_lines.append("--- STDOUT ---")
        debug_lines.append(result.stdout or "(없음)")
        debug_lines.append("--- STDERR ---")
        debug_lines.append(result.stderr or "(없음)")
        with open(os.path.join(BASE_DIR, 'debug_scan_error.txt'), 'w', encoding='utf-8') as f:
            f.write("\n".join(debug_lines))
        sys.exit(result.returncode)

run_step("[STEP 1/3] 양음양 / v2 / 포도시 스캔 진행 중...", ["run_full_rescan.py"], CLOUD_SCANNER_DIR)
run_step("[STEP 2/3] 500억봉 / 150억봉 스캔 진행 중...", ["run_scan_and_report.py"], CLOUD_SCANNER_DIR)
run_step("[STEP 3/3] scan_history.json 갱신 및 파일 정리 진행 중...", ["sync_and_push.py"], BASE_DIR)

print("\n모든 스캔이 성공적으로 완료되었습니다!")
