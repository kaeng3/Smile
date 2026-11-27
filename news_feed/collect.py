"""뉴스 키워드 수집 (GitHub Actions 30분마다, 24시간).
RSS·포털 기사를 모아 키워드 사전(keywords.json)·종목명(stocks.json)으로 점수를 매기고
점수 store_min_score 이상만 news.json에 누적(최근 keep_days일). keyword_stats.json = 날짜별 키워드·테마 빈도.
키워드 사전은 PC '섹터 상승' 프로젝트의 keywords.py 결과를 복사해 갱신한다."""
import json, os, sys, time, datetime, collections as C
import argparse
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import re, tok, sources, brief
D = os.path.dirname(os.path.abspath(__file__))
KST = datetime.timezone(datetime.timedelta(hours=9))
def load(n, d=None):
    p = os.path.join(D, n)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else d

def session(hhmm):
    return "장전" if hhmm < "09:00" else ("장중" if hhmm < "15:30" else "장후")

def categorize(title, themes, F):
    """분야: 매크로 단어 우선(제목), 없으면 연관 테마 → 섹터."""
    for cat, words in F["categories"].items():
        if any(w in title for w in words): return cat
    for t in themes:
        for sec, pat in F["theme_sector"]:
            if re.search(pat, t): return sec
    return "기타"

def find_stocks(title, ST):
    """종목명 매칭: 앞 글자가 한글·영문·숫자면 제외(추진시스템≠진시스템), 더 긴 이름에 포함된 짧은 이름 제거(HD현대마린솔루션 > HD현대)."""
    hit = []
    for n, c in ST.items():
        i = title.find(n)
        while i >= 0:
            if i == 0 or not re.match(r"[가-힣A-Za-z0-9]", title[i - 1]): hit.append((n, c)); break
            i = title.find(n, i + 1)
    hit = [(n, c) for n, c in hit if not any(n != m and n in m for m, _ in hit)]
    return [[n, c] for n, c in sorted(hit, key=lambda x: -len(x[0]))][:3]

def main(output_dir=None, update_brief=True):
    F, KW, ST = load("feeds.json"), load("keywords.json"), load("stocks.json")
    outdir = Path(output_dir) if output_dir is not None else Path(D)
    outdir.mkdir(parents=True,exist_ok=True)
    prior=outdir/"news.json"
    old = {a["k"]: a for a in json.loads(prior.read_text(encoding="utf-8"))} if prior.exists() else {}
    url_index = {sources.article_key(a.get("url")): k for k, a in old.items() if sources.article_key(a.get("url"))}
    now = datetime.datetime.now(KST); items, ok, bad, health = [], 0, [], []
    for kind, fetcher in (("portals", sources.fetch_portal), ("rss", sources.fetch_rss)):
        for name, url in F[kind].items():
            result,info=sources.fetch_checked(fetcher,name,url)
            items+=result
            health.append(info)
            if result:ok+=1
            else:bad.append(name)
    new = 0
    rejected=set(); encountered=set()
    for it in items:
        k = sources.article_key(it.get("url"))
        if not k or not sources.norm(it["title"]): continue
        encountered.add(k)
        if k in url_index:
            stored = old[url_index[k]]
            # Record later publisher markers without rewriting the original title.
            if sources.is_featured_title(it["title"]) and not sources.is_featured_title(stored.get("title")) and not stored.get("featured_title"):
                stamp=it.get("observed_at")
                if sources.publication_time(stamp):
                    stored["featured_title"]=it["title"]
                    stored["featured_observed_at"]=stamp
                    stored["featured_press"]=it.get("press") or stored.get("press")
            if it.get("published_at") and not stored.get("published_at"):
                stored["published_at"] = it["published_at"]
                stored["source_feed"] = it.get("source_feed")
                # Record when this metadata became available (not original collection).
                stored["publication_verified_at"] = it.get("observed_at")
            continue
        observed = datetime.datetime.fromisoformat(it.get("observed_at") or datetime.datetime.now(KST).isoformat())
        title = it["title"]
        cands = tok.candidates(title) | {w for w in tok.tokens(title) if w}
        hits = [(w, KW[w]) for w in cands if w in KW]
        bis = [w for w, _ in hits if " " in w]
        hits = [(w, v) for w, v in hits if " " in w or not any(w in b.split() for b in bis)]
        eff = lambda w, v: v["w"] * (1 if " " in w or (v["themes"] and v["themes"][0][1] >= F["min_spec"]) else 0.3)
        hits.sort(key=lambda x: -eff(*x))
        stocks = find_stocks(title, ST)
        ev = [e for e in F["event_words"] if e in title]
        score = sum(eff(w, v) for w, v in hits[:2]) + (6 if stocks else 0) + (5 if ev and (stocks or hits) else 0)
        macro = any(w in title for ws in F["categories"].values() for w in ws)
        # Preserve explicit publisher-labeled stock news even below the score floor.
        # Do not boost its score or assert it caused a price move.
        if not (((hits or (stocks and ev)) and score >= F["store_min_score"]) or macro or sources.is_featured_title(title)):
            rejected.add(k)
            continue
        if macro: score = max(score, F["macro_score"])
        th = C.Counter()
        for _, v in hits[:3]:
            for t, s in v["themes"][:2]: th[t] += s
        old[k] = {"k": k, "seen": observed.strftime("%Y-%m-%d %H:%M"), "observed_at": observed.isoformat(), "time": it["time"], "press": it["press"],
                  "title": title, "url": it["url"], "score": round(score, 1), "kws": [w for w, _ in hits[:4]],
                  "published_at": it.get("published_at"), "source_feed": it.get("source_feed"),
                  "ev": ev[:2], "stocks": stocks, "themes": [t for t, _ in th.most_common(3)]}
        old[k]["cat"] = categorize(title, old[k]["themes"], F); old[k]["sess"] = session(observed.strftime("%H:%M"))
        url_index[k] = k
        new += 1
    for a in old.values(): a["stocks"] = find_stocks(a["title"], ST)
    cut = (now - datetime.timedelta(days=F["keep_days"] + 2)).strftime("%Y-%m-%d")
    arts = sorted((a for a in old.values() if a["seen"] >= cut), key=lambda a: a["seen"], reverse=True)
    write_json(outdir/"news.json", arts)
    stats = C.defaultdict(lambda: {"kw": C.Counter(), "th": C.Counter(), "n": 0})
    for a in arts:
        s = stats[a["seen"][:10]]; s["n"] += 1; s["kw"].update(a["kws"]); s["th"].update(a["themes"])
    out = {d: {"n": s["n"], "kw": s["kw"].most_common(40), "th": s["th"].most_common(20)} for d, s in stats.items()}
    write_json(outdir/"keyword_stats.json", {"updated": datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "sources_ok": ok, "sources_bad": bad, "days": out,
              "source_health":health,"raw_articles":len(items),
              "publication_timestamp_count":sum(bool(a.get("published_at")) for a in arts),
              "capture_started_at":now.isoformat(),"capture_completed_at":datetime.datetime.now(KST).isoformat(),
              "raw_unique_valid_urls":len(encountered),"raw_unique_not_retained":len(encountered-set(url_index)),
              "score_filtered_unique_urls":len(rejected-set(url_index)),
              "featured_raw_count":sum(sources.is_featured_title(a.get("title")) for a in items),
              "featured_retained_count":sum(sources.is_featured_title(a.get("title")) or sources.is_featured_title(a.get("featured_title")) for a in arts)})
    if update_brief:
        try: brief.update()
        except Exception as e: print("[brief] 오류:", repr(e))
    print(f"출처 {ok}개 성공/{len(bad)}개 실패, 기사 {len(items)}건 중 신규 저장 {new}건, 보관 {len(arts)}건")

def write_json(path, data):
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(data,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    temp.replace(path)

if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--output-dir",type=Path,help="Isolated capture folder; configuration stays in news_feed")
    p.add_argument("--no-brief",action="store_true")
    a=p.parse_args()
    if a.output_dir and not a.no_brief:
        p.error("Isolated capture requires --no-brief")
    main(a.output_dir,not a.no_brief)
