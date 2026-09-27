# 김일구 New스캐너

평일 16:05(KST)에 KIS 일봉을 증분 갱신하고, 바닥권에서 새로 `IGNITION` 또는
`BREAKOUT`으로 전환된 종목을 최대 5개까지 공개합니다. 최근 5영업일 결과는
`results/history.json`에 보관하고 같은 날짜의 같은 결과는 텔레그램으로 다시
보내지 않습니다.

GitHub 저장소의 Actions secrets에 다음 네 값을 등록해야 합니다.

- `KIS_APP_KEY`
- `KIS_APP_SECRET`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

원시 시세 캐시, KIS 토큰, 텔레그램 발송 상태는 Actions cache에만 저장되며
Git에는 포함되지 않습니다. 수동 실행은 Actions의 **Kim Ilgu New Scanner**에서
`Run workflow`를 누르면 됩니다.
