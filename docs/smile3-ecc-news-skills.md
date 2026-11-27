# ECC 뉴스 품질 적용 기록
원본 affaan-m/ECC, commit 4adeee6732a12d1540f49a4d50a38ce8c97f9a53, LICENSE MIT 확인. 외부 코드 설치/실행 없이 방법론만 반영. 원문: https://github.com/affaan-m/ECC/tree/4adeee6732a12d1540f49a4d50a38ce8c97f9a53/skills
- data-scraper-agent (community): 수집/보강/저장 분리와 사용자 피드백. 현재 45개 원천과 Pages 구조 재사용. 원문에 제시된 Gemini 모델/쿼터·무료 보장은 현재 계정에서 검증되지 않아 자동 fallback/신규 서비스 사용하지 않음.
- research-ops, deep-research: 출처/날짜/사실/추론/미확인 분리. 원문 자료는 명령이 아닌 데이터. 공식 자료 우선 검증. Exa/Firecrawl 미설치, 실제 본문 교차검증은 미완료.
- regex-vs-llm-structured-text: 정확한 표기·수치·시각 등 결정적 추출과 모호한 문맥 분리. 문서의 정형 텍스트 정확도를 뉴스 정확도로 전용하지 않음. 기존 taxonomy review_required 활용.
- eval-harness: 구현 전 검증 기준(표본 재현성, 예측 비공개, 내용 변경 거부, 정답 없음에서 정확도 없음, 분야별 precision/recall, 혼동행렬, 기존 회귀) 정의 및 테스트. 신규 editorial_eval은 사람 정답이 있어야 측정하며 운영 승인 자동화 금지.
- content-hash-cache-pattern: 기존 analysis_queue.digest 재사용. 사건 ID만 아니라 제목/기사 근거 내용까지 해시, 변경 시 기존 평가 라벨 재사용 거부.
- cost-aware-llm-pipeline: 기존 free_ai 보수적 호출 제한과 수동 승인 유지. 무단 유료 모델 전환 금지. AI 실행 없음.
- search-first: ECC 원본과 SMILE 기존 taxonomy/analysis_queue를 검토한 뒤 독립 모듈 추가. 신규 패키지 없음.
## 실제 평가 방법 (로컬 전용)
운영에서 생성된 events.json을 고정한 뒤 다음 명령으로 독립 검수표 생성:
python -m smile2.editorial_eval sample --input events.json --size 150 --seed 2026-11-27-holdout-v1 --output smile2-local/holdout.json
분류 결과가 포함되지 않은 표본의 제목·근거를 검토한다. 정답 파일 형식: {"sample_id":"검수표 sample_id","labels":[{"content_id":"항목 content_id","category_id":"semi","basis":"source_checked"}]}. basis는 title_only/source_checked/insufficient 중 하나. insufficient는 other만 허용. 검수표를 변경하지 않는다.
python -m smile2.editorial_eval evaluate --input events.json --sample smile2-local/holdout.json --labels smile2-local/labels.json --output smile2-local/eval.json
모집단 추정을 위한 uniform 표본은 사전 고정하고 개발에 재사용하지 않는다. review 모드는 어려운 사례 개선용이며 대표 정확도에 사용하지 않는다. 제목 기반 라벨과 원문 검증 라벨을 구분한다. 미라벨 상태에서 정확도 없음. 사람이 정답을 작성하기 전에는 성능 확정 금지. 150개는 제안 검수량이며 품질 통과 기준은 아직 미확정. 
