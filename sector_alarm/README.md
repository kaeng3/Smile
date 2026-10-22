# 섹터 상승 — 키움 테마 점등 알람 (PC 전용)

PC(키움 IP 등록)에서 돌아가는 테마 점등 알람 프로그램의 코드입니다. 원본 폴더: `C:\Users\pc\Desktop\섹터 상승`.
자세한 구조는 [CLAUDE.md](CLAUDE.md) 참고.

## Smile 대시보드 '🔥 상승 테마' 탭 연동
1. `run.bat` 으로 알람 프로그램 실행 (http://localhost:8000)
2. `publish_snapshot.bat` 실행 → 장중 5분마다 화면 상태를 Smile `data` 브랜치 `sector_alarm/snapshot.json` 으로 올림
3. 처음 한 번: 같은 폴더에 `github_token.txt` (Smile 저장소 Contents 쓰기 권한 토큰 한 줄) 만들기 — 깃에 올라가지 않음

## 깃에 올리지 않는 것 (.gitignore)
- 키움 키(`*_appkey.txt`, `*_secretkey.txt`), GitHub 토큰, `logs/`, `__pycache__/`
- 인포스탁 DB·테마 백과(`data/infostock.sqlite3`, `static/kb/`): 원문 재배포 금지 → 공개 저장소에 두지 않음
- 대용량/외부 원본: 키움 명세서 json, `data/alphasquare.md`, `data/news_keywords.json`(= `news_feed/keywords.json`)

- `config.json`: 텔레그램 봇 토큰이 저장되는 파일이라 저장소 규칙상 올라가지 않음(Smile은 공개 저장소). 설정값은 PC 원본에만 있음
