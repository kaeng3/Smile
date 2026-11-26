# 공식 출처 수집기 (독립 실험)
- 한국은행: https://www.bok.or.kr/static/view/popup/rss_popup.html
- 금융위원회: https://www.fsc.go.kr/ut060101
- 미국 연준: https://www.federalreserve.gov/feeds/feeds.htm
- DART: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001
- python -m smile2.official_feeds --output /local/official.json
- DART는 환경변수 DART_API_KEY와 --dart-day YYYY-MM-DD를 설정한 경우만 조회. 접수일을 발표 시각으로 바꾸지 않는다.
- 공식 RSS 목록을 근거로 시험 수집기를 만들었으며, 실제 응답 및 제공 조건은 배포 전 검증해야 한다. 운영 수집기와 분리. 기사 전체 본문 저장 또는 유료 자료 접근 없음.
- 공식 자료의 score=6은 시범 정렬용이며 중요도 판단이 아니다.

- 추가 공식 목록: https://www.bls.gov/feed/ ; https://www.bea.gov/resources/for-developers ; https://www.sec.gov/newsroom/press-releases . 실제 연결 검증은 CI에서 시행. 금융위 RSS HTTPS는 기존 HTTPError 상태, 인증/차단 우회하지 않음.
