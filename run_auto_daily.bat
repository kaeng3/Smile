@echo off
chcp 65001 > nul
title [김일청 주식 자동 스캐너] 매일 15:40 자동 실행 중...
echo ========================================================
echo  [STEP 1/3] 양음양/v2/포도시/500억 전 종목 스캔 시작
echo ========================================================

cd /d "C:\Users\pc\Desktop\Smile_Stock_Auto_Scanner"
python -u -X utf8 run_full_rescan.py

echo.
echo ========================================================
echo  [STEP 2/3] 스캔 결과 깃허브 폴더 동기화 및 반영
echo ========================================================

cd /d "C:\Users\pc\Desktop\Smile_Stock_System"
python -u -X utf8 sync_and_push.py

echo.
echo ========================================================
echo  [STEP 3/3] 완료! 웹사이트 https://kaeng3.github.io/Smile/ 갱신됨
echo ========================================================
