# 김일구 New스캐너 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `smile`의 베타 실험실 2를 매일 장 마감 후 KIS로 계산한 신규 바닥권 `IGNITION/BREAKOUT` TOP5 화면과 텔레그램 알림으로 교체한다.

**Architecture:** 검증된 스캐너를 `new_scanner/`에 독립 패키지로 포함하고, 순수한 후보 선정·5일 보관 계층과 외부 I/O 오케스트레이션을 분리한다. GitHub Actions는 원시 시세를 Actions 캐시에만 보관하고 정적 `history.json`만 저장소에 커밋하며, 기존 `index.html`은 이 JSON을 읽어 `lab2`에 표시한다.

**Tech Stack:** Python 3.12, pandas, PyYAML, requests, KIS Open API, Telegram Bot API, HTML/CSS/vanilla JavaScript, GitHub Actions, unittest/pytest

**Spec:** `docs/superpowers/specs/2026-09-27-kim-ilgu-new-scanner-design.md`

## Global Constraints

- 최근 3년 일봉만 사용하고, 기준일 미래 데이터는 어떤 계산에도 사용하지 않는다.
- 후보는 최신 봉에서 새로 전환된 `BOTTOM_ACCUMULATION`의 `IGNITION/BREAKOUT`, `cost_status == "HOLD"`로 제한한다.
- `final_score` 내림차순, 종목코드 오름차순으로 최대 5개를 선택한다.
- 사이트와 텔레그램은 최근 5영업일 결과만 보관하며 같은 날짜·동일 결과를 중복 발송하지 않는다.
- KIS·Telegram 비밀값, 액세스 토큰, 원시 API 응답, OHLCV 캐시는 Git에 커밋하지 않는다.
- 기존 실전 스캔, 베타 실험실 1·3, `db-seed` 브랜치는 변경하지 않는다.
- 새 워크플로는 평일 15:55 KST에 실행하고 기존 Pages 작업과 동일한 concurrency 그룹 `pages`를 사용한다.

## Review Focus

- 휴장일·부분장·마지막 봉이 기준일보다 오래된 경우: 후보를 게시하지 않고 이전 정상 결과를 손상시키지 않아야 한다. Task 3의 stale-session 테스트로 고정한다.
- 6개 이상 동점 후보: 종목코드 오름차순으로 항상 같은 TOP5가 나와야 한다. Task 2의 tie 테스트로 고정한다.
- KIS 부분 실패와 전체 실패: 부분 실패는 메타데이터에 집계하고, 전체 실패·인증 실패는 새 결과/알림을 만들지 않아야 한다. Task 3의 failure 테스트로 고정한다.
- Telegram 전송 성공 후 기록 실패 또는 재실행: 발송 성공 기록과 결과 해시가 일치할 때만 중복을 막고, 실패한 발송은 재시도되어야 한다. Task 2의 notifier 테스트로 고정한다.
- 손상되거나 이전 스키마인 `history.json`: 화면은 다른 탭을 깨뜨리지 않고 오류 안내를 표시하며, 실행기는 명시적으로 실패해야 한다. Task 2와 Task 4의 schema 테스트로 고정한다.

---

### Task 1: 검증된 스캐너 코어 포함

**Files:**
- Create: `new_scanner/src/jusmo_scanner/**`
- Create: `new_scanner/config/scanner.yaml`
- Create: `new_scanner/requirements.txt`
- Create: `new_scanner/tests/core/**`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: 기존 스캐너 브랜치 `feature/event-location-kis-fixes`의 커밋 `ed81fd2`
- Produces: `KisProvider`, `load_config(path)`, `engine.scan_ticker(df, ticker, cfg)`, `ScanResult`

- [ ] **Step 1: 검증된 스캐너 소스·설정·회귀 테스트를 `new_scanner/`에 복사하고 원본 커밋을 `new_scanner/UPSTREAM.md`에 기록한다.**

- [ ] **Step 2: `.gitignore` 회귀 테스트를 작성한다.**

`new_scanner/tests/test_repository_safety.py`에 `.env`, `*.db`, `new_scanner/data/cache/**`, `.kis_token.json`, 결과 외 로그가 Git에서 제외되고 `new_scanner/results/history.json`만 추적 가능함을 검증한다.

- [ ] **Step 3: 안전성 테스트가 실패하는지 확인한다.**

Run: `python -m pytest new_scanner/tests/test_repository_safety.py -q`
Expected: 새 ignore 규칙이 없어 FAIL

- [ ] **Step 4: `.gitignore`에 새 스캐너의 캐시·토큰·DB·로그 제외 규칙을 추가한다.**

- [ ] **Step 5: 코어 회귀 테스트와 안전성 테스트를 실행한다.**

Run: `python -m pytest new_scanner/tests/core new_scanner/tests/test_repository_safety.py -q`
Expected: 모든 테스트 PASS, 라이브 KIS 테스트만 명시적으로 SKIP

- [ ] **Step 6: 커밋한다.**

```bash
git add .gitignore new_scanner
git commit -m "feat: add validated new scanner core"
```

### Task 2: TOP5·5영업일 기록·텔레그램 메시지

**Files:**
- Create: `new_scanner/reporting.py`
- Create: `new_scanner/telegram_digest.py`
- Create: `new_scanner/tests/test_reporting.py`
- Create: `new_scanner/tests/test_telegram_digest.py`
- Create: `new_scanner/results/history.json`

**Interfaces:**
- Consumes: `ScanResult`와 종목 메타데이터 `dict`
- Produces: `select_top_candidates(rows: Iterable[CandidateRow], limit: int = 5) -> list[dict]`
- Produces: `update_history(existing: dict, session: dict, keep: int = 5) -> dict`
- Produces: `validate_history(payload: object) -> dict`
- Produces: `format_top5_message(session: dict) -> str`
- Produces: `send_digest(notifier, session: dict, sent_state: dict) -> dict`

- [ ] **Step 1: 후보 선정 실패 테스트를 작성한다.**

`test_select_top_candidates_filters_and_sorts_deterministically`에서 최신 봉·신규 전환·BOTTOM·HOLD 조건을 하나씩 어기는 행을 제외하고, 6개 동점 입력이 종목코드순 TOP5가 되는지 검증한다.

- [ ] **Step 2: 기록 스키마와 5일 롤링 실패 테스트를 작성한다.**

같은 날짜는 교체하고 날짜 내림차순 5개만 남는지, 잘못된 루트·날짜·후보 필드는 `ValueError`인지 검증한다.

- [ ] **Step 3: 텔레그램 실패·멱등성 테스트를 작성한다.**

후보 있음/없음 메시지, 전송 성공 뒤 결과 해시 저장, 같은 해시 재실행 무전송, 전송 실패 뒤 무기록·재시도를 검증한다. 예외 문자열에 토큰과 요청 URL이 없는지도 확인한다.

- [ ] **Step 4: 새 테스트들이 구현 부재로 실패하는지 확인한다.**

Run: `python -m pytest new_scanner/tests/test_reporting.py new_scanner/tests/test_telegram_digest.py -q`
Expected: 모듈 또는 함수 부재로 FAIL

- [ ] **Step 5: `reporting.py`와 `telegram_digest.py`의 공개 인터페이스를 최소 구현한다.**

결과 날짜 형식은 `YYYYMMDD`, 금액은 원 단위 숫자, 비율은 소수 비율, 점수는 숫자로 JSON에 저장한다. 텔레그램은 표시할 때만 원·퍼센트로 변환한다.

- [ ] **Step 6: 테스트를 다시 실행한다.**

Run: `python -m pytest new_scanner/tests/test_reporting.py new_scanner/tests/test_telegram_digest.py -q`
Expected: PASS

- [ ] **Step 7: 빈 초기 결과를 생성하고 커밋한다.**

`history.json`은 `{"version": 1, "sessions": []}`로 시작한다.

```bash
git add new_scanner/reporting.py new_scanner/telegram_digest.py new_scanner/tests new_scanner/results/history.json
git commit -m "feat: rank and format new scanner top five"
```

### Task 3: 일일 실행 오케스트레이션

**Files:**
- Create: `new_scanner/run_daily.py`
- Create: `new_scanner/tests/test_run_daily.py`
- Modify: `new_scanner/requirements.txt`

**Interfaces:**
- Consumes: Task 1의 provider/engine과 Task 2의 선택·기록·알림 함수
- Produces: `run_daily(*, target_date: date, provider_factory, notifier, history_path: Path, sent_state_path: Path) -> dict`
- Produces: CLI `python new_scanner/run_daily.py [--date YYYY-MM-DD] [--no-telegram]`

- [ ] **Step 1: 인과적 실행과 stale-session 실패 테스트를 작성한다.**

가짜 provider로 240봉 이상 종목, 신규상장, stale 마지막 봉, 거래정지·관리·정리매매, 고점·중간권, INVALIDATED를 구성하고 게시 후보와 메타데이터를 검증한다.

- [ ] **Step 2: 부분 실패·전체 실패·인증 실패 테스트를 작성한다.**

일부 종목 예외는 `failed_tickers`에 집계되며 결과는 생성되고, 모든 종목 실패와 provider 생성 실패는 기존 파일을 바꾸지 않고 비정상 종료하는지 검증한다.

- [ ] **Step 3: 원자적 저장과 전송 순서 테스트를 작성한다.**

유효한 history를 임시 파일에 쓴 뒤 교체하고, history 저장 성공 뒤 Telegram을 보내며, Telegram 성공 뒤 sent state를 기록하는 순서를 검증한다.

- [ ] **Step 4: 새 테스트들이 구현 부재로 실패하는지 확인한다.**

Run: `python -m pytest new_scanner/tests/test_run_daily.py -q`
Expected: 모듈 또는 함수 부재로 FAIL

- [ ] **Step 5: `run_daily`와 CLI를 최소 구현한다.**

기본 기준일은 KST 오늘이며 provider는 최근 3년·현재 유니버스·지속 캐시를 사용한다. 종목별 실패에는 예외 클래스와 안전한 코드만 기록하고 원래 KIS 응답은 기록하지 않는다.

- [ ] **Step 6: 오케스트레이션 테스트와 코어 테스트를 실행한다.**

Run: `python -m pytest new_scanner/tests -q`
Expected: PASS, 라이브 호출 0회

- [ ] **Step 7: 커밋한다.**

```bash
git add new_scanner/run_daily.py new_scanner/requirements.txt new_scanner/tests/test_run_daily.py
git commit -m "feat: run daily new scanner digest"
```

### Task 4: 김일구 New스캐너 웹 화면

**Files:**
- Modify: `index.html`
- Create: `tests/test_new_scanner_page.py`

**Interfaces:**
- Consumes: `new_scanner/results/history.json` version 1
- Produces: 기존 `lab2` 탭 내부의 날짜 선택·TOP5 카드·빈 상태·오류 상태

- [ ] **Step 1: 정적 화면 계약 실패 테스트를 작성한다.**

`unittest`로 메뉴 문구 `🔎 김일구 New스캐너`, 기존 `lab2` ID, JSON fetch 경로, 필수 컨테이너 ID, 실험실 1·3의 기존 문구가 존재하는지 검증한다.

- [ ] **Step 2: 브라우저 데이터 처리 계약 실패 테스트를 작성한다.**

JS 로딩 함수가 version 1만 허용하고, 빈 sessions/빈 candidates/네트워크 오류를 각각 정상 빈 상태와 오류 상태로 렌더링하도록 소스 계약을 검증한다.

- [ ] **Step 3: 테스트가 기존 placeholder 화면 때문에 실패하는지 확인한다.**

Run: `python -m unittest tests.test_new_scanner_page -v`
Expected: FAIL

- [ ] **Step 4: `index.html`의 `lab2`만 수정한다.**

기존 탭 전환 ID는 유지하고, 독립 CSS 클래스와 `loadNewScannerData`, `renderNewScannerDates`, `renderNewScannerCards` 함수를 추가한다. 다른 탭의 전역 상태와 함수명은 재사용하지 않는다.

- [ ] **Step 5: 기존·신규 사이트 테스트를 실행한다.**

Run: `python -m unittest discover -s tests -v`
Expected: PASS

- [ ] **Step 6: 로컬 정적 서버에서 데스크톱과 모바일 화면을 확인한다.**

Run: `python -m http.server 8000`
Expected: `lab2`에 5일 날짜와 TOP5가 표시되고 기존 세 탭이 정상 전환됨

- [ ] **Step 7: 커밋한다.**

```bash
git add index.html tests/test_new_scanner_page.py
git commit -m "feat: show Kim Ilgu new scanner top five"
```

### Task 5: GitHub Actions 자동 실행과 배포 안전성

**Files:**
- Create: `.github/workflows/new_scanner.yml`
- Create: `tests/test_new_scanner_workflow.py`
- Modify: `README.md` if present, otherwise Create: `new_scanner/README.md`

**Interfaces:**
- Consumes: Task 3 CLI, GitHub Secrets 네 개, Actions cache
- Produces: 평일 06:55 UTC 스케줄, 수동 실행, 결과 커밋, Pages 배포

- [ ] **Step 1: 워크플로 계약 실패 테스트를 작성한다.**

YAML에 `cron: '55 6 * * 1-5'`, `workflow_dispatch`, concurrency `pages`, Python 3.12, 네 secret 전달, `new_scanner/data/cache` 캐시, 테스트 선행, `history.json`만 `git add`, Pages 배포가 있는지 검증한다.

- [ ] **Step 2: 비밀정보와 push 범위 실패 테스트를 작성한다.**

워크플로와 추적 파일에 실제 `.env` 값이 없고 `git add .`를 쓰지 않으며, 캐시·sent state가 추적되지 않는지 검증한다.

- [ ] **Step 3: 새 테스트가 워크플로 부재로 실패하는지 확인한다.**

Run: `python -m unittest tests.test_new_scanner_workflow -v`
Expected: FAIL

- [ ] **Step 4: `new_scanner.yml`과 운영 문서를 구현한다.**

Actions 캐시 키는 OS와 설정 파일 해시를 포함하고 restore key를 둔다. 전체 실패 시 기존 `history.json`을 커밋하지 않으며, 결과 변경이 없으면 커밋·배포를 건너뛴다.

- [ ] **Step 5: 전체 테스트를 실행한다.**

Run: `python -m unittest discover -s tests -v`
Expected: PASS

Run: `python -m pytest new_scanner/tests -q`
Expected: PASS, 라이브 호출 0회

- [ ] **Step 6: 추적 파일 비밀정보 검사를 실행한다.**

`.env`의 비밀값과 KIS 토큰 캐시 값을 읽어 `git ls-files` 대상에서 일치 항목 0개인지 확인한다. 출력에는 비밀값을 표시하지 않는다.

- [ ] **Step 7: 커밋한다.**

```bash
git add .github/workflows/new_scanner.yml tests/test_new_scanner_workflow.py new_scanner/README.md
git commit -m "ci: automate Kim Ilgu new scanner"
```

### Task 6: 전체 검증, GitHub 등록, 최초 배포

**Files:**
- Modify: GitHub repository Secrets (외부 설정)
- Modify: GitHub branch/PR and `main` after review

**Interfaces:**
- Consumes: 완성된 기능 브랜치와 사용자 GitHub 로그인 세션
- Produces: 배포된 `https://kaeng3.github.io/Smile/`의 김일구 New스캐너와 Telegram TOP5

- [ ] **Step 1: 기존 Smile 테스트와 새 스캐너 전체 테스트를 깨끗한 상태에서 다시 실행한다.**

Run: `python -m unittest discover -s tests -v`
Expected: PASS

Run: `python -m pytest new_scanner/tests -q`
Expected: PASS

- [ ] **Step 2: 브랜치 diff와 추적 파일을 검토한다.**

기존 실전 스캔·실험실 1·3의 의도치 않은 변경, 대용량 캐시, 비밀값, 생성 로그가 없어야 한다.

- [ ] **Step 3: 사용자 로그인 세션으로 GitHub Secrets 네 개를 등록한다.**

값은 화면 입력란에 직접 넣고 로그·스크린샷·파일에 복사하지 않는다.

- [ ] **Step 4: `feature/kim-ilgu-new-scanner`를 origin에 push하고 변경사항을 검토한다.**

- [ ] **Step 5: 사용자 확인 후 `main`에 반영하고 새 워크플로를 수동 실행한다.**

- [ ] **Step 6: Actions 성공, Pages 화면, TOP5 날짜·값, Telegram 한 건 수신을 확인한다.**

- [ ] **Step 7: 같은 날짜로 수동 재실행해 결과 중복과 Telegram 중복이 없는지 확인한다.**
