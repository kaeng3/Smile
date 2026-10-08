# -*- coding: utf-8 -*-
"""
build_theme_bundles.py
500억봉 AI 요약을 테마별로 묶어 theme_bundles.json(테마꾸러미 탭)을 만든다.

- 이벤트: 500억봉 요약 1건(날짜·종목). ai_summary_archive.json(영구) + daily_issues.json(최근 5일, 상세)
- 테마 판정 순서: ① AI 테마 태그 ② 핵심 재료 제목/이유 ③ (①②가 없을 때만) 종목 테마 DB의 세부 테마
  어느 것이든 theme_dictionary.json의 aliases가 들어 있으면 그 표준 테마로 묶는다.
- 사전에 없는 AI 태그는 'unmatched_tags'로 모아 사전 보강에 쓴다.
외부 요청 없음.
"""
import os
import json
import math
import datetime
from collections import Counter

SCANNER_DIR = os.path.dirname(os.path.abspath(__file__))
GIT_DIR = os.path.dirname(SCANNER_DIR)
P = lambda name: os.path.join(GIT_DIR, name)
RECENT_SESSIONS = 5
REIGNITE_GAP_DAYS = 14  # 이만큼 조용하다 다시 나오면 '재점화'


def load(name, default):
    try:
        with open(P(name), 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def norm(s):
    return ''.join(str(s or '').split()).lower()


class ThemeMatcher:
    def __init__(self, dictionary):
        self.themes = dictionary.get('themes', [])
        self.aliases = [(norm(a), t['name']) for t in self.themes for a in t.get('aliases', []) if len(norm(a)) >= 2]

    def match_text(self, text):
        n = norm(text)
        return {name for alias, name in self.aliases if alias and alias in n} if n else set()

    def match_tag(self, tag):
        n = norm(tag)
        if not n:
            return set()
        # 태그가 별칭을 포함하거나(정보보안 ⊃ 보안), 짧은 태그가 별칭 안에 있으면(로봇 ⊂ 로보틱스 X) 매칭
        return {name for alias, name in self.aliases if alias in n or (len(n) >= 2 and n in alias)}


def collect_events(archive, daily_issues):
    detail = {}
    for date, items in daily_issues.items():
        for it in items:
            detail[(date, it['code'])] = it
    events = {}
    for code, entries in archive.items():
        for e in entries:
            events[(e['date'], code)] = {
                'date': e['date'], 'code': code, 'name': e.get('name', ''), 'rate': e.get('rate', 0),
                'trading_value': e.get('trading_value'), 'title': e.get('title'), 'summary': e.get('summary', ''),
                'themes_raw': e.get('themes') or [], 'reason': '',
            }
    for (date, code), it in detail.items():
        main = (it.get('analysis') or {}).get('main_material') or {}
        ev = events.setdefault((date, code), {'date': date, 'code': code})
        ev.update({
            'name': it.get('name', ev.get('name', '')), 'rate': it.get('rate', ev.get('rate', 0)),
            'trading_value': it.get('trading_value') or ev.get('trading_value'),
            'title': main.get('title') or ev.get('title'), 'summary': it.get('summary') or ev.get('summary', ''),
            'themes_raw': main.get('theme') or ev.get('themes_raw') or [], 'reason': main.get('reason') or '',
        })
    return sorted(events.values(), key=lambda e: (e['date'], e['code']))


def classify(ev, matcher, stock_themes):
    found, unmatched = set(), []
    for tag in ev.get('themes_raw', []):
        hit = matcher.match_tag(tag)
        found |= hit
        if not hit:
            unmatched.append(tag)
    title = ev.get('title') or ''
    if title and '확인불가' not in title:
        found |= matcher.match_text(title)
        found |= matcher.match_text(ev.get('reason', ''))
    via = 'ai'
    if not found:
        info = stock_themes.get(ev['code']) or {}
        for sub in info.get('subthemes', [])[:6]:
            found |= matcher.match_tag(sub)
        via = 'stock_db' if found else 'none'
    return sorted(found), unmatched, via


def build():
    dictionary = load('theme_dictionary.json', {'themes': []})
    matcher = ThemeMatcher(dictionary)
    groups = {t['name']: t.get('group', '기타') for t in dictionary.get('themes', [])}
    events = collect_events(load('ai_summary_archive.json', {}), load('daily_issues.json', {}))
    stock_themes = load('stock_detail_themes.json', {})

    sessions = sorted({e['date'] for e in events})
    recent = set(sessions[-RECENT_SESSIONS:])
    bundles, unmatched_counter, unclassified = {}, Counter(), []
    for ev in events:
        themes, unmatched, via = classify(ev, matcher, stock_themes)
        unmatched_counter.update(unmatched)
        slim = {k: ev.get(k) for k in ('date', 'code', 'name', 'rate', 'trading_value', 'title', 'summary')}
        slim['via'] = via
        if not themes:
            unclassified.append(slim)
            continue
        for t in themes:
            bundles.setdefault(t, []).append(slim)

    result = []
    for name, evs in bundles.items():
        evs.sort(key=lambda e: e['date'], reverse=True)
        stocks = {}
        for e in evs:
            s = stocks.setdefault(e['code'], {'code': e['code'], 'name': e['name'], 'count': 0,
                                               'last_date': e['date'], 'max_rate': 0, 'max_tv': 0})
            s['count'] += 1
            s['max_rate'] = max(s['max_rate'], e.get('rate') or 0)
            s['max_tv'] = max(s['max_tv'], e.get('trading_value') or 0)
        dates = sorted({e['date'] for e in evs})
        recent_n = sum(1 for e in evs if e['date'] in recent)
        tv_sum = sum(e.get('trading_value') or 0 for e in evs if e['date'] in recent)
        heat = round(recent_n * 10 + len(evs) * 2 + math.log10(tv_sum / 1e8 + 1) * 5, 1)
        reignited = False
        if len(dates) >= 2 and dates[-1] in recent:
            d1 = datetime.datetime.strptime(dates[-2], '%Y%m%d')
            d2 = datetime.datetime.strptime(dates[-1], '%Y%m%d')
            reignited = (d2 - d1).days >= REIGNITE_GAP_DAYS
        leader = max(stocks.values(), key=lambda s: (s['max_tv'], s['count'], s['max_rate']))
        result.append({
            'theme': name, 'group': groups.get(name, '기타'), 'heat': heat,
            'event_count': len(evs), 'recent_count': recent_n, 'stock_count': len(stocks),
            'first_date': dates[0], 'last_date': dates[-1], 'active_dates': dates[-10:],
            'reignited': reignited, 'leader': leader['name'], 'leader_code': leader['code'],
            'stocks': sorted(stocks.values(), key=lambda s: (-s['count'], -s['max_tv'])),
            'events': evs[:40],
        })
    result.sort(key=lambda b: (-b['heat'], -b['event_count']))

    kst = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=9)
    payload = {
        'generated_at': kst.strftime('%Y-%m-%d %H:%M'),
        'sessions': sessions[-RECENT_SESSIONS:],
        'total_events': len(events),
        'bundles': result,
        'unclassified': sorted(unclassified, key=lambda e: e['date'], reverse=True)[:30],
        'unmatched_tags': unmatched_counter.most_common(40),
    }
    with open(P('theme_bundles.json'), 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=1)
    print(f"[테마꾸러미] 이벤트 {len(events)}건 → 테마 {len(result)}개, 미분류 {len(unclassified)}건")


if __name__ == '__main__':
    build()
