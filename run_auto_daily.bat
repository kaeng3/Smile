@echo off
chcp 65001 > nul
title [김일청 주식 자동 스캐너] 매일 15:40 자동 실행 중...

echo ========================================================
echo  [STEP 1/4] 양음양/v2/포도시 전 종목 스캔 + PDF 발행
echo ========================================================
cd /d "C:\Users\pc\Desktop\Smile_Stock_Auto_Scanner"
python -u -X utf8 run_full_rescan.py

echo.
echo ========================================================
echo  [STEP 2/4] 500억/150억 기준봉 스캐너 실행
echo ========================================================
cd /d "C:\Users\pc\Desktop\Smile_Stock_System\stock_scanner_500m"
python -u -X utf8 run_scan_and_report.py

echo.
echo ========================================================
echo  [STEP 3/4] 스캔 결과 깃허브 폴더 동기화 및 반영
echo ========================================================
cd /d "C:\Users\pc\Desktop\Smile_Stock_System"
python -u -X utf8 sync_and_push.py

echo.
echo ========================================================
echo  [STEP 4/4] 완료! 웹사이트 https://kaeng3.github.io/Smile/ 갱신됨
echo ========================================================
