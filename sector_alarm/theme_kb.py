"""테마 백과: 인포스탁 13년치(data/infostock.sqlite3) → static/kb/*.json (대시보드·알람용)
  theme_kb.json : 테마별 주도 이력(13년 주도일·첫/마지막·평균 지속일·역대 대장주·월별 계절성·다음날 후속 테마·최근 사유·구성종목)
  stock_kb.json : 종목별 급등 횟수·재료 유형·최근 사유·소속 인포스탁 테마
  macro.json    : 거시 요인(금리·환율·전쟁 등) 언급일의 코스피 당일/다음날 반응과 그날 강세 테마
  map.json      : 내 테마(HTS·키워드) ↔ 인포스탁 테마 매핑
사용: python theme_kb.py [인포스탁 DB]  (app.py가 매주 월요일 아침 자동 재생성)"""
import json, os, re, sys, math, sqlite3, datetime, collections as C
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "static", "kb")

def nz(s): return re.sub(r"\s+", "", s or "")

def build(db=None):
    db = db or os.path.join(HERE, "data", "infostock.sqlite3")
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    master = json.load(open(os.path.join(HERE, "stock_master.json"), encoding="utf-8"))["data"]
    name2code = {v[0].replace(" ", ""): k for k, v in master.items()}
    days = [d for (d,) in c.execute("select distinct date from market_brief where kind='KOSPI' order by date")]
    di = {d: i for i, d in enumerate(days)}
    # ---- 인포스탁 공식 테마(이름·구성종목) ----
    official, members = {}, C.defaultdict(C.Counter)
    for tid, th, code in c.execute("select theme_id, theme, code from theme_members"):
        official[nz(th)] = th; members[th][code] += 1
    for th, tid in c.execute("select distinct theme, theme_id from theme_rank2"): official.setdefault(nz(th), th)
    def resolve(name):
        """사유 표의 테마명 → 공식 테마명 목록 ('정유/ LPG/ 해운 등' 같은 복합명 분해)"""
        n = nz(name)
        if n in official: return [official[n]]
        parts = [p for p in re.split(r"/\s+|,\s*|\s+및\s+|\s+등$", name.replace(" 등", "")) if p.strip()]
        out = [official.get(nz(p), p.strip()) for p in parts]
        return out or [name]
    # ---- 테마 주도 이력 ----
    led = C.defaultdict(set); reasons = C.defaultdict(list); leaders = C.defaultdict(C.Counter)
    for d, th, rs, codes in c.execute("select date, theme, reason, codes from theme_events where direction='up' order by date"):
        cs = [x for x in json.loads(codes or "[]") if x]
        for t in resolve(th):
            led[t].add(d)
            if (d, rs) not in reasons[t][-3:]: reasons[t].append((d, rs))
            for i, code in enumerate(cs[:6]): leaders[t][code] += 3 if i == 0 else (2 if i < 3 else 1)
    by_day = C.defaultdict(set)
    for t, ds in led.items():
        for d in ds: by_day[d].add(t)
    N = len(days) or 1
    month_days = C.Counter(d[4:6] for d in days)
    themes = {}
    for t, ds in led.items():
        if len(ds) < 3: continue
        idx = sorted(di[d] for d in ds if d in di)
        streaks, run = [], 1
        for a, b in zip(idx, idx[1:]):
            if b == a + 1: run += 1
            else: streaks.append(run); run = 1
        if idx: streaks.append(run)
        nxt = C.Counter()
        for i in idx:
            if i + 1 < len(days): nxt.update(by_day.get(days[i + 1], set()) - {t})
        base = {u: len(v) / N for u, v in led.items()}
        follow = []
        for u, k in nxt.items():
            p = k / len(idx); lift = p / base[u] if base.get(u) else 0
            if k >= 4 and lift >= 2: follow.append([u, round(p, 2), round(lift, 1)])
        follow.sort(key=lambda x: -x[1] * x[2])
        mon = C.Counter(d[4:6] for d in ds)
        season = {m: round((mon[m] / month_days[m]) / (len(ds) / N), 2) for m in mon if month_days[m]}
        lead = [[master.get(code, ("?",))[0], code, n] for code, n in leaders[t].most_common(6)]
        mem = [[master.get(code, ("?",))[0], code] for code, _ in members.get(t, C.Counter()).most_common(20)]
        themes[t] = {"n": len(ds), "first": min(ds), "last": max(ds), "recent": sum(1 for d in ds if d >= days[max(0, len(days) - 250)]),
                     "streak": round(sum(streaks) / len(streaks), 1) if streaks else 1, "max_streak": max(streaks or [1]),
                     "leaders": lead, "members": mem, "season": season, "follow": follow[:5],
                     "reasons": [[d, r] for d, r in reasons[t][-6:]][::-1], "official": nz(t) in official}
    # ---- 종목 프로필 ----
    sk = {}
    th_of = C.defaultdict(list)
    for t, m in members.items():
        for code in m: th_of[code].append(t)
    for code, name, n, last in c.execute("select code, max(name), count(*), max(date) from surge group by code"):
        rt = C.Counter(r for (r,) in c.execute("select rtype from surge where code=?", (code,)))
        rs = c.execute("select date, rate, reason from surge where code=? order by date desc limit 4", (code,)).fetchall()
        sk[code] = {"name": master.get(code, (name,))[0], "old": name if master.get(code, (name,))[0] != name else "", "n": n, "last": last, "rtype": rt.most_common(3), "reasons": rs, "themes": th_of.get(code, [])[:6]}
    for code, ts in th_of.items():
        if code not in sk: sk[code] = {"name": master.get(code, ("?",))[0], "n": 0, "last": "", "rtype": [], "reasons": [], "themes": ts[:6]}
    # ---- 내 테마 ↔ 인포스탁 테마 ----
    td = json.load(open(os.path.join(HERE, "themes.json"), encoding="utf-8"))
    off_sets = {t: set(m) for t, m in members.items() if len(m) >= 3}
    mp = {}
    for name, t in td["themes"].items():
        s = set(t["codes"])
        if not s: continue
        # 코사인 유사도 × 13년 주도 이력 가중 (작은 테마가 통째로 포함돼 1순위가 되는 것 방지)
        sc = sorted((((len(s & o) / math.sqrt(len(s) * len(o))) * (1 + math.log1p(themes.get(u, {}).get("n", 0)) / 4), u)
                     for u, o in off_sets.items() if len(s & o) >= 2), reverse=True)[:3]
        mp[name] = [[u, round(x, 2)] for x, u in sc if x >= 0.25]
    # ---- 거시 요인 ----
    F = {"외국인 순매도": r"외국인.{0,6}순매도", "외국인 순매수": r"외국인.{0,6}순매수", "연준/FOMC": r"연준|FOMC|Fed|파월",
         "금리": r"금리|국채|채권", "환율/달러": r"환율|달러|원화", "전쟁/지정학": r"전쟁|공습|미사일|중동|이스라엘|이란|우크라|러시아|후티|지정학|북한|北",
         "유가": r"유가|원유|WTI", "관세/무역": r"관세|무역|수출규제", "중국": r"중국|中|위안", "물가/CPI": r"물가|CPI|인플레",
         "반도체 업황": r"반도체", "실적": r"실적"}
    rows = []
    for d, h in c.execute("select date, headline from market_brief where kind='KOSPI' order by date"):
        m = re.search(r"KOSPI\s*[\d,.]+\s*\(([+-]?[\d.]+)%\)\s*(.*)", h or "")
        if m: rows.append((d, float(m.group(1)), m.group(2)))
    macro = {"days": len(rows), "since": rows[0][0] if rows else "", "base_up": round(sum(r > 0 for _, r, _ in rows) / max(len(rows), 1) * 100), "factors": {}}
    for f, pat in F.items():
        hit = []
        for i, (d, r, t) in enumerate(rows):
            part = next((p for p in t.split(",") if re.search(pat, p)), None)
            if part is not None: hit.append((i, d, r, "-" if "(-)" in part else ("+" if "(+)" in part else "")))
        if not hit: continue
        nx = [rows[i + 1][1] for i, *_ in hit if i + 1 < len(rows)]
        neg_days = [d for _, d, _, s in hit if s == "-"]
        th = C.Counter()
        for d in neg_days:
            for (t,) in c.execute("select theme from theme_events where date=? and direction='up' and source='summary'", (d,)): th[t] += 1
        macro["factors"][f] = {"pat": pat, "n": len(hit), "neg": len(neg_days), "pos": sum(1 for *_, s in hit if s == "+"),
            "same": round(sum(r for _, _, r, _ in hit) / len(hit), 2), "next": round(sum(nx) / max(len(nx), 1), 2),
            "next_up": round(sum(x > 0 for x in nx) / max(len(nx), 1) * 100), "themes_on_bad": th.most_common(6),
            "recent": [[d, r] for _, d, r, _ in hit[-5:]][::-1]}
    os.makedirs(OUT, exist_ok=True)
    for fn, obj in (("theme_kb.json", themes), ("stock_kb.json", sk), ("map.json", mp), ("macro.json", macro)):
        json.dump(obj, open(os.path.join(OUT, fn), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    return themes, sk, mp, macro

if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    th, sk, mp, ma = build(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"테마 {len(th)}개(공식 {sum(v['official'] for v in th.values())}) / 종목 {len(sk)}개 / 매핑 {sum(1 for v in mp.values() if v)}개 / 거시 {len(ma['factors'])}요인")
