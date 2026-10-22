"""순환매 통계: 시그널리포트 DB(일별 주도 종목)를 HTS 테마로 환산해
   'A 테마가 주도한 날 → 같은 날/다음 날 함께·이어서 주도한 테마' 확률과 lift 계산 → rotation.json
   주도 = 그날 리포트에 +stock_pct% 이상 종목이 min_stocks개 이상.  사용: python rotation.py [DB경로]"""
import json, os, sys, sqlite3, collections as C
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))

def run(db_path):
    rc = CFG["rotation"]
    td = json.load(open(os.path.join(HERE, "themes.json"), encoding="utf-8"))
    hts = {n: set(t["codes"]) for n, t in td["themes"].items() if not t["basket"]}   # HTS 그룹 + 세부 키워드
    inv = C.defaultdict(set)
    for n, cs in hts.items():
        for c in cs: inv[c].add(n)
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    per_day = C.defaultdict(lambda: C.defaultdict(set))
    for d, code in con.execute("""select distinct b.report_date, m.matched_code from stock_mentions m
            join theme_blocks b on b.id=m.theme_block_id
            where b.report_date>=? and m.matched_code is not null and m.pct_change>=?""", (rc["since"], rc["stock_pct"])):
        for t in inv.get(code, ()): per_day[d][t].add(code)
    days = sorted(per_day)
    led = {d: {t for t, cs in per_day[d].items() if len(cs) >= rc["min_stocks"]} for d in days}
    N = len(days); base = C.Counter(t for d in days for t in led[d])
    same, nxt, cnt = C.defaultdict(C.Counter), C.defaultdict(C.Counter), C.Counter()
    for i, d in enumerate(days):
        for a in led[d]:
            cnt[a] += 1
            for b in led[d] - {a}: same[a][b] += 1
            if i + 1 < N:
                for b in led[days[i + 1]]: nxt[a][b] += 1
    def top(counter, a):
        res = []
        for b, k in counter.items():
            sa, sb = hts[a], hts[b]
            if len(sa & sb) / max(min(len(sa), len(sb)), 1) > 0.4: continue   # 이름만 다른 같은 테마 제외
            p = k / cnt[a]; lift = p / (base[b] / N)
            if k >= rc["min_co"] and p >= rc["min_prob"] and lift >= rc["min_lift"]: res.append([b, round(p, 2), round(lift, 1), k])
        return sorted(res, key=lambda x: (x[2] * x[1]), reverse=True)[:4]
    out = {"days": N, "since": days[0] if days else "", "until": days[-1] if days else "", "themes": {}}
    for a in cnt:
        if cnt[a] < rc["min_support"]: continue
        out["themes"][a] = {"days": cnt[a], "base": round(base[a] / N, 2),
                            "persist": round(nxt[a][a] / cnt[a], 2), "same": top(same[a], a),
                            "next": top({b: k for b, k in nxt[a].items() if b != a}, a)}
    json.dump(out, open(os.path.join(HERE, "rotation.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return out

if __name__ == "__main__":
    o = run(sys.argv[1] if len(sys.argv) > 1 else CFG["signal_db"])
    print(f"{o['since']} ~ {o['until']} 거래일 {o['days']}일, 테마 {len(o['themes'])}개")
    for a, v in sorted(o["themes"].items(), key=lambda x: -x[1]["days"])[:25]:
        print(f"\n■ {a} (주도 {v['days']}일, 다음날 지속 {v['persist']:.0%})")
        if v["same"]: print("   같은날:", ", ".join(f"{b} {p:.0%}(x{l})" for b, p, l, k in v["same"]))
        if v["next"]: print("   다음날:", ", ".join(f"{b} {p:.0%}(x{l})" for b, p, l, k in v["next"]))
