# -*- coding: utf-8 -*-
"""
event_archive.py — 500억봉 AI 분석 이벤트를 월별 JSONL(event_archive/events-YYYY-MM.jsonl)에 영구 보관.
한 줄 = 이벤트 하나(날짜+종목). 지우지 않고, 같은 날짜·종목은 새 내용으로 교체한다.
(archive_store.py가 이 폴더를 archive 브랜치에 이력과 함께 올린다)
"""
import os
import json
import datetime

GIT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FOLDER = os.path.join(GIT_DIR, 'event_archive')
MAX_ARTICLES = 15


def _path(date_str):
    return os.path.join(FOLDER, f'events-{date_str[:4]}-{date_str[4:6]}.jsonl')


def _read(path):
    rows = {}
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    e = json.loads(line)
                    rows[(e['date'], e['code'])] = e
    return rows


def load_all():
    events = []
    if os.path.isdir(FOLDER):
        for name in sorted(os.listdir(FOLDER)):
            if name.startswith('events-') and name.endswith('.jsonl'):
                events += _read(os.path.join(FOLDER, name)).values()
    return sorted(events, key=lambda e: (e['date'], e['code']))


def from_issue(date_str, issue):
    """daily_issues.json 항목 → 보관용 이벤트(분석 전문 + 근거 기사 제목/링크)."""
    return {
        'date': date_str, 'code': issue['code'], 'name': issue.get('name', ''),
        'rate': issue.get('rate'), 'trading_value': issue.get('trading_value'),
        'news_source': issue.get('news_source'), 'summary': issue.get('summary', ''),
        'analysis': issue.get('analysis'),
        'articles': [{k: a.get(k) for k in ('datetime', 'title', 'press', 'link')}
                     for a in (issue.get('articles') or [])][-MAX_ARTICLES:],
        'detail': 'full',
    }


def from_summary(date_str, code, entry):
    """예전 ai_summary_archive.json 항목(요약만) → 이벤트. 분석 전문이 없으므로 detail='summary'."""
    return {
        'date': date_str, 'code': code, 'name': entry.get('name', ''), 'rate': entry.get('rate'),
        'trading_value': entry.get('trading_value'), 'news_source': None, 'summary': entry.get('summary', ''),
        'analysis': {'main_material': {'title': entry.get('title'), 'event_type': entry.get('event_type'),
                                       'theme': entry.get('themes') or []},
                     'confidence': entry.get('confidence')},
        'articles': [], 'detail': 'summary',
    }


def upsert(events):
    """events를 월별 파일에 반영. 요약뿐인 이벤트는 이미 상세 기록이 있으면 덮지 않는다. 바뀐 건수 반환."""
    os.makedirs(FOLDER, exist_ok=True)
    now = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)).strftime('%Y-%m-%d %H:%M')
    by_file = {}
    for e in events:
        by_file.setdefault(_path(e['date']), []).append(e)
    changed = 0
    for path, evs in by_file.items():
        rows = _read(path)
        for e in evs:
            key = (e['date'], e['code'])
            old = rows.get(key)
            if old and old.get('detail') == 'full' and e.get('detail') != 'full':
                continue
            cmp_old = {k: v for k, v in (old or {}).items() if k != 'recorded_at'}
            if cmp_old == e:
                continue
            rows[key] = dict(e, recorded_at=now)
            changed += 1
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            for key in sorted(rows):
                f.write(json.dumps(rows[key], ensure_ascii=False) + '\n')
        os.replace(tmp, path)
    return changed


def record(all_issues, summary_archive=None):
    """daily_issues 전체(최근 5일, 상세) + 예전 요약 이력(있으면)을 보관소에 반영."""
    events = [from_issue(d, it) for d, items in all_issues.items() for it in items]
    for code, entries in (summary_archive or {}).items():
        events += [from_summary(e['date'], code, e) for e in entries if e.get('date')]
    n = upsert(events)
    print(f'[이벤트보관] {n}건 갱신 (보관 폴더: event_archive/)')
    return n
