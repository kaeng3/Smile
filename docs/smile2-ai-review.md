# AI 분석 검토 대기열 (로컬 전용)
- python -m smile2.analysis_queue --input /local/events.json --output /local/review-queue.json --max-events 30 --max-chars 60000
- 키워드 점수와 원문 수로 분석 후보를 제한한다. 실제 시장 영향도 순위가 아니다. 30건/60000자는 예시 실행 설정이며 운영 예산이 아니다.
- 패킷에는 제목, 출처 URL, 발표 시각, 제목 언급 또는 공시 발행 기업만 제공한다. 기사 본문은 아직 연결하지 않으며 구독 자료는 입력하지 않는다.
- validate(packet, draft)는 패킷 식별자, URL 및 제목 인용의 정확 일치를 검사하고 human_review_required 상태를 반환한다. 문장 의미와 근거 사이의 논리적 일치나 사실 여부를 보증하지 않는다.
- 실제 AI API 연결, 토큰/금액 예산, 모델 선정, 본문 수집 허가, 검토 UI 및 게시 승인은 별도 단계이다. 자동 호출과 자동 게시는 없다.
