# 테마 점등 알람 (키움 REST)
- 실행: Windows PC, Python 3.9 32bit, 표준 라이브러리만(ws_test.py만 websockets). 키움 IP등록 PC에서만 호출 가능.
- 원본 명세서(2.5MB json) 읽지 말 것 → kiwoom_spec.md 발췌만 참조. ka10027(등락률상위)도 사용 중.
- 확정 사실: WS 0B 실시간 등록 한도 200종목 → 전종목은 ka10027 폴링(상승 535종목 0.9s). 관심그룹 99개→테마 68개, 중복제거 2085종목.
## 파일
- kiwoom.py: 토큰, call(연속조회), watch_groups(ka01300/01301), stock_master(ka10099 일1회 캐시), risers(ka10027)
- themes.py: 2층 테마 사전 → themes.json {themes:{이름:{codes,kind(hts|kw),basket,independent,added,parent}}, kw_of}
  · hts=HTS 그룹(번호 병합), kw=data/keywords.csv(사용자 키워드 분류 2327종목)+data/alphasquare.md 보완
  · 바스켓(config.basket_groups, keyword.basket) = 화면만, 알람 제외 / 독립 키워드(HTS 겹침<35%) = 자체 알람
  · HTS에 없는 종목은 겹침 50%+ 키워드 통해 HTS 그룹에 자동 배정(added, 화면 '보완' 배지)
- engine.py: theme_scores(거래대금 상위10, min_amt억 미만 판정 제외, 주도키워드 chips) / level 0~3(최소 2종목 +5%) / alertable / Alerter / fmt
- app.py: 날짜 바뀌면 관심그룹 재조회→사전 재생성, 3초 폴링, 텔레그램, logs/alerts_YYYYMMDD.log, http://localhost:8000 (/data)
- static/index.html: 탭(메인/세부 키워드/바스켓/알람 기록), 점등 스트립, 검색, 단계 상승 카드 펄스, 모바일 대응
- run.bat: 8000포트 기존 프로세스 종료 후 재시작
## 초기 점등·장전·실시간 (10/8 추가)
- early.py: History(3초 스냅샷 6분) + detect: ①3분 +2%p 3종목 & 유입 평소 3배 ②대장 +5%p→2종목 확산 ③VI 5분 2건. EarlyAlerter(테마당 30분 1회, 2단계 이상 제외)
  · config.early.notify=false → 기록 전용(logs/early_*.log, 대시보드). 10/12 장 검증 후 켤지 결정
- ws.py: Realtime 스레드. 1h VI 전종목(item "") + 0B 대장주 동적 구독(grp 2, refresh 0, max 150). 폴링 결과에 rate/price overlay
- 장전: 08:00~08:39 NXT(ka10027 stex=2), 08:40~08:59 예상체결(ka10029), 08:55 장전 요약 알람. 세 TR 모두 응답 확인(check_api.bat)
- rotation.py: 시그널리포트 DB → rotation.json (테마별 같은날/다음날 후속 확률·lift, 이름만 다른 동일테마 제외). 점등 카드에 표시
- replay_test.py: 키움 없이 가상 장중 시나리오로 초기→점등 흐름 검증
- logs/: app_*.log(접속·구간·오류), alerts_*.log, early_*.log
## 인포스탁 (무료 = 전일자까지만, 10/8 추가)
- infostock.py: api.infostock.co.kr:9081/web/flash/list (POST menuType/startDate/endDate/count≤50, 본문 포함). PC에서만 접속 가능
  · 메뉴: MENU_TODAY_SUMMARY(증시요약 1~10, 2013.03~), MENU_DAILY_FEATURED_THEME(데일리 특징테마+세부테마 구성종목표), MENU_THEME_FLUCTUATIONS(전일 테마 등락률)
  · DB data/infostock.sqlite3: posts, market_brief(KOSPI/KOSDAQ/THEME_*), theme_events(테마·사유·관련종목·코드), surge(상한가·급등 사유·재료유형), theme_rank2, theme_members(인포스탁 테마ID=네이버 테마번호)
  · 명령: backfill(meta.backfill_until로 이어받기) / update(최근10일) / brief / reparse
  · 당일 자료(유료)는 수집하지 않음(sendDate ≤ 어제). 원문 재배포 금지 → 친구 공유 화면에 넣지 말 것
- app.py: 날짜 바뀌면 인포스탁 update(백그라운드) → reasons 캐시(종목별 최근 사유) → 알람·카드에 '📌 사유' 첨부, 07:50 전일 시황 브리핑 텔레그램(logs/brief_sent.txt로 하루 1회), 대시보드 '시황 정리' 패널
- 장중 오전/오후 테마동향(MENU_MIDDLE_FEATURED, web/market/board·detail)은 당일=유료라 미사용
## 테마 백과 (10/9 추가)
- theme_kb.py → static/kb/{theme_kb,stock_kb,map,macro}.json : 인포스탁 13년 테마 주도 이력(주도일·지속·역대 대장·월별 계절성·다음날 후속·최근 사유·구성종목), 종목 프로필(급등 횟수·재료유형·사유·소속테마), 내 테마↔인포스탁 테마 매핑(코사인×이력), 거시 요인별 코스피 반응(2019.11~)
- themes.py 3번째 층 kind="is": 인포스탁 공식 테마('◆이름', theme_members 2회+ 종목). HTS와 겹침 35% 미만이면 독립(자체 알람). 지주사·대표주 등은 바스켓
- app.py: 하루 시작 시 KB 로드(월요일·최초는 재생성), 알람·카드에 '📚 13년 이력' 줄(kb_line)
- 대시보드 탭: '인포스탁 테마', '📚 테마 백과'(검색·이번 달 자주 뜨던 테마·거시 요인 표, 3초 갱신에도 검색창 유지)
- 주의: PC 화면 조작 시 한글 입력기(Textinputhost)가 앞에 떠서 클릭이 막힘 → open_application(파일 탐색기) 직후 클릭
## 다음 작업 (사용자 계획)
- 증시를 움직일 뉴스 키워드 채취 → 키워드로 뉴스 추출 → 텔레그램 알람. 인포스탁 13년치 사유 텍스트(surge.reason, theme_events.reason)가 키워드 사전의 원천
## 뉴스 키워드 알람 — 비활성(config.news.enable=false). 뉴스 수집은 GitHub kaeng3/Smile news_feed(30분, 24h)에서만 함
- keywords.py는 Smile news_feed/keywords.json 갱신용. 2026-10-09 인포스탁 13년치(2013.03~) 백필 완료 후 5,000개로 재생성해 반영함
  · 재생성: python keywords.py <시그널리포트 DB> → data/news_keywords.json을 Smile news_feed/keywords.json으로 복사, keywords.py의 STOP~candidates를 Smile tok.py에 동일하게 반영(규칙 불일치 시 매칭 안 됨)
- keywords.py: 시그널리포트 뉴스제목(2022~)+인포스탁 사유 → data/news_keywords.json (1·2단어, 종목명·증권사·일반어 제외, w=등장일·테마쏠림·평균등락·최근성). 인포스탁 백필 끝나면 재실행
- news.py: 네이버 금융 실시간 속보(cp949, articleSubject/press/wdate 정규식) 1분 폴링 → 키워드 상위2 가중치+종목명(3자+) 보너스 ≥ min_score(18) → 텔레그램(10분 6건 제한). python news.py = 매칭 테스트
- app.py news_loop 스레드(07:00~20:00), 대시보드 '뉴스' 탭, logs/news_*.log
## 참고 데이터 (다른 폴더)
- ~/Desktop/시그널리포트md/db/signal_reports.sqlite3: 2022.04~2026.08 일별 주도테마·종목·뉴스 (theme_blocks, stock_mentions, news_items)
- ~/Desktop/이브닝md: 키워드 분류표 원본, 알파스퀘어 452테마, analytics_v1.py(순환매 통계)
## TODO
- 장중 실측 후 기준 튜닝 / 알람에 시그널리포트 과거 맥락(마지막 등장일·대장주) 첨부 / WS 200칸 대장주 실시간 / 모바일·친구 공유(Firebase)
