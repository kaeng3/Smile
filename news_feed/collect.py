"""뉴스 키워드 수집 (GitHub Actions 30분마다, 24시간).
RSS·포털 기사를 모아 키워드 사전(keywords.json)·종목명(stocks.json)으로 점수를 매기고
점수 store_min_score 이상만 news.json에 누적(최근 keep_days일). keyword_stats.json = 날짜별 키워드·테마 빈도.
키워드 사전은 PC '섹터 상승' 프로젝트의 keywords.py 결과를 복사해 갱신한다."""
import json, os, sys, time, datetime, collections as C
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tok, sources
D = os.path.dirname(os.path.abspath(__file__))
KST = datetime.timezone(datetime.timedelta(hours=9))
def load(n, d=None):
    p = os.path.join(D, n)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else d

def main():
    F, KW, ST = load("feeds.json"), load("keywords.json"), load("stocks.json")
    old = {a["k"]: a for a in load("news.json", [])}
    now = datetime.datetime.now(KST); items, ok, bad = [], 0, []
    for name, url in F["portals"].items():
        try: items += sources.fetch_portal(name, url); ok += 1
        except Exception: bad.append(name)
    for name, url in F["rss"].items():
        try: items += sources.fetch_rss(name, url); ok += 1
        except Exception: bad.append(name)
    new = 0
    for it in items:
        k = sources.norm(it["title"])
        if not k or k in old: continue
        title = it["title"]
        cands = tok.candidates(title) | {w for w in tok.tokens(title) if w}
        hits = [(w, KW[w]) for w in cands if w in KW]
        bis = [w for w, _ in hits if " " in w]
        hits = [(w, v) for w, v in hits if " " in w or not any(w in b.split() for b in bis)]
        eff = lambda w, v: v["w"] * (1 if " " in w or (v["themes"] and v["themes"][0][1] >= F["min_spec"]) else 0.3)
        hits.sort(key=lambda x: -eff(*x))
        stocks = [[n, c] for n, c in ST.items() if n in title][:3]
        ev = [e for e in F["event_words"] if e in title]
        score = sum(eff(w, v) for w, v in hits[:2]) + (6 if stocks else 0) + (5 if ev and (stocks or hits) else 0)
        if not hits or score < F["store_min_score"]: continue
        th = C.Counter()
        for _, v in hits[:3]:
            for t, s in v["themes"][:2]: th[t] += s
        old[k] = {"k": k, "seen": now.strftime("%Y-%m-%d %H:%M"), "time": it["time"], "press": it["press"],
                  "title": title, "url": it["url"], "score": round(score, 1), "kws": [w for w, _ in hits[:4]],
                  "ev": ev[:2], "stocks": stocks, "themes": [t for t, _ in th.most_common(3)]}
        new += 1
    cut = (now - datetime.timedelta(days=F["keep_days"] + 2)).strftime("%Y-%m-%d")
    arts = sorted((a for a in old.values() if a["seen"] >= cut), key=lambda a: a["seen"], reverse=True)
    json.dump(arts, open(os.path.join(D, "news.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    stats = C.defaultdict(lambda: {"kw": C.Counter(), "th": C.Counter(), "n": 0})
    for a in arts:
        s = stats[a["seen"][:10]]; s["n"] += 1; s["kw"].update(a["kws"]); s["th"].update(a["themes"])
    out = {d: {"n": s["n"], "kw": s["kw"].most_common(40), "th": s["th"].most_common(20)} for d, s in stats.items()}
    json.dump({"updated": now.strftime("%Y-%m-%d %H:%M"), "sources_ok": ok, "sources_bad": bad, "days": out},
              open(os.path.join(D, "keyword_stats.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"출처 {ok}개 성공/{len(bad)}개 실패, 기사 {len(items)}건 중 신규 저장 {new}건, 보관 {len(arts)}건")

if __name__ == "__main__":
    main()
