# 로컬 과거 재료 검색 및 차트 연구

- 과거 자료는 승인된 로컬 파일에서만 조회한다. 공개 CI에 원문 검색 결과를 출력하거나 웹 페이지에 게시하지 않는다.
- 집계: python -m smile2.history_search /local/private/history.json --code 000100 --query "검색어"
- 로컬 상세 제목: 위 명령에 --local-details (공개 CI 금지).
- 기술적 분석: python -m smile2.patterns --input-dir /local/krx-regular-daily --rules /local/rules.json --as-of YYYY-MM-DD --output /local/candidates.json
- 입력은 schema=1, source=DAUM_KRX_REGULAR, records 배열 및 day/open/high/low/close/volume/value 필드라는 인계서 가정. 실제 파일 구조 확인 필요. 실거래대금 value 필수, 대체 추정하지 않음. 거래일 연속성은 공급자 데이터 및 공식 캘린더와 별도 검증 필요.
- Rules 필드는 body_pct, volume_ratio_min, reduced_volume_max, upper_wick_body_min, box_days, box_width_max_pct, box_touch_tolerance_pct, box_min_touches, near_breakout_pct, ma5_distance_pct. 테스트의 수치는 합성 데이터 검증용일 뿐 실제 매매 기준이 아니다. 사용자 검증 없이 기본값을 지정하지 않는다.
- 수평 몸통 박스 후보, 이일홍 첫 꽃/연속 양봉 후보, 두 가지 거감음봉, 박스 돌파 후 조정·회복 구현 초안. 상승 추세 박스, 오래된 저항과 최근 저항 구분, 고가놀이, 상태 영속화, 공식 거래일 검증 및 실제 사례 회귀는 미구현. 매집 주체 추정 금지.
- 기존 500억봉, 포도시 코드는 변경하지 않는다. 신규 전략에는 150억/500억 거래대금 필터를 적용하지 않는다.

- 로컬 후보 추적: python -m smile2.track --snapshot /local/candidates.json --state /local/watchlist.json. 날짜는 엄격히 증가해야 함. 미검출은 무효화로 간주하지 않는다. 후보 화면 candidates.html은 브라우저에서 로컬 JSON을 읽고 종목코드를 복사한다. 차트 자체 및 실제 상태 판정은 추가 구현 필요.

### 2.2 추적 개선
스캔 성공 종목 전체의 당일 관측값을 로컬 snapshot에 포함한다. --verify-calendar 옵션으로 거래일 연속성을 검사하고 DAUM_KRX_REGULAR 출처 표식이 있을 때만 추적 관측을 사용한다. 출처 표식 자체가 실제 공급자 검증을 대신하지 않는다. 첫 봉 종가와 최초 박스 상·하단을 고정 기준으로 저장한다. 고가놀이는 최초 박스 하단을 기준 지지선으로 표시한다. 미검출, 당일 자료 없음, 자료 오류, 관측된 기준선 유지/이탈을 구분한다. 상승 채널 기준은 첫 탐지 당시 값이며 미래 기울기 연장값이 아니다. 이탈 주의는 자동 무효화가 아니다. 전체 관측 snapshot 및 추적 파일은 로컬 전용이며 공개 Pages에 포함하지 않는다.
