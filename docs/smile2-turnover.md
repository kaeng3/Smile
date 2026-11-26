# 거래대금 원본 경로 감사
기존 daily_issues.json 및 SQLiteMarketProvider는 종가×거래량 추정치. KIS 공급자 rows_to_frame은 acml_tr_pbmn을 trading_value로 저장한다. 이 모듈은 기존 KIS 공급자 캐시 daily/{code}.csv.gz 또는 parquet와 meta.json만 읽는다. 토큰 파일·인증키·네트워크 요청 없음.
수정주가 캐시, 최신 거래일 미충족, 중복 날짜, 실제 값 결측, OHLC×거래량 범위 밖 값, 형식 불명은 거부한다. 같은 가격·거래량 범위에 들어오는지 확인하는 필요조건이며 원천 값 자체나 정규장 범위의 증명이 아니다. KIS 캐시 메타에는 정규장/NXT 범위의 근거가 없으므로 session_scope=unverified를 유지한다. 실제 DAUM_KRX_REGULAR 로컬 자료 또는 확인된 정규장 데이터 확보 전에는 운영 스캐너의 거래대금을 대체하지 않는다.
실행: python -m smile2.turnover --cache-dir new_scanner/data/cache --day YYYY-MM-DD (집계만). --code 지정 시 로컬 단일 종목 조회. parquet는 pandas 및 parquet 엔진 필요. 사용자 PC의 실제 캐시에는 아직 접근하지 못했다.
