# -*- coding: utf-8 -*-
"""
publish_snapshot.py — 로컬 알람 화면(localhost:8000/data)의 현재 상태를 Smile 대시보드 '상승 테마' 탭으로 올린다.

- 올리는 곳: kaeng3/Smile 저장소 data 브랜치의 sector_alarm/snapshot.json (사이트는 이 파일을 바로 읽음)
- 인포스탁 원문(시황 브리핑 brief, 📌 사유 why, 📚 13년 이력 kb)은 재배포 금지라 빼고 올린다.
- 토큰: 같은 폴더의 github_token.txt 한 줄 (Smile 저장소 Contents 쓰기 권한). 이 파일은 깃에 올라가지 않음.
- 표준 라이브러리만 사용 (Python 3.9 32bit OK)

사용:
  python publish_snapshot.py            한 번 올리기
  python publish_snapshot.py --loop 300 장중(08:00~15:40, 평일) 300초마다 올리고, 장 마감 뒤 마지막 1회 올린 뒤 종료
"""
import os
import sys
import json
import time
import base64
import urllib.request
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
LOCAL_URL = "http://localhost:8000/data"
REPO = "kaeng3/Smile"
BRANCH = "data"
PATH = "sector_alarm/snapshot.json"
API = f"https://api.github.com/repos/{REPO}/contents/{PATH}"


def token():
    p = os.path.join(HERE, "github_token.txt")
    if not os.path.exists(p):
        sys.exit("github_token.txt 가 없습니다. Smile 저장소 쓰기 권한이 있는 GitHub 토큰을 한 줄로 넣어 주세요.")
    return open(p, encoding="utf-8").read().strip()


def sanitize(snap):
    out = {k: v for k, v in snap.items() if k not in ("brief",)}
    themes = []
    for t in snap.get("themes", []):
        t = {k: v for k, v in t.items() if k not in ("why", "kb")}
        themes.append(t)
    out["themes"] = themes
    out["date"] = time.strftime("%Y-%m-%d")
    out["published_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    return out


def gh(method, url, tok, body=None):
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None, headers={
        "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
        "User-Agent": "sector-alarm-publisher", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode() or "{}")


def publish_once(tok):
    with urllib.request.urlopen(LOCAL_URL, timeout=10) as r:
        snap = json.loads(r.read().decode("utf-8"))
    data = json.dumps(sanitize(snap), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    for attempt in range(3):
        try:
            sha = None
            try:
                sha = gh("GET", f"{API}?ref={BRANCH}", tok).get("sha")
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
            body = {"message": f"sector_alarm snapshot {time.strftime('%m-%d %H:%M')}",
                    "content": base64.b64encode(data).decode(), "branch": BRANCH}
            if sha:
                body["sha"] = sha
            gh("PUT", API, tok, body)
            print(f"[{time.strftime('%H:%M:%S')}] 올림: 테마 {len(snap.get('themes', []))}개, 점등 {snap.get('n_lit')}개")
            return True
        except urllib.error.HTTPError as e:
            print(f"[{time.strftime('%H:%M:%S')}] GitHub 응답 {e.code} (재시도 {attempt + 1}/3)")
            time.sleep(5 * (attempt + 1))
    return False


def main():
    tok = token()
    if "--loop" not in sys.argv:
        publish_once(tok)
        return
    every = int(sys.argv[sys.argv.index("--loop") + 1]) if len(sys.argv) > sys.argv.index("--loop") + 1 else 300
    while True:
        hhmm = time.strftime("%H%M")
        weekday = time.localtime().tm_wday < 5
        if weekday and "0800" <= hhmm <= "1540":
            try:
                publish_once(tok)
            except Exception as e:
                print(f"[{time.strftime('%H:%M:%S')}] 실패: {e}")
            time.sleep(every)
        elif weekday and hhmm > "1540":
            try:
                publish_once(tok)  # 마감 상태 마지막 1회
            except Exception as e:
                print(f"마감 업로드 실패: {e}")
            return
        else:
            time.sleep(60)


if __name__ == "__main__":
    main()
