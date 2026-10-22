"""테마 사전 빌더 — 2층 구조.
  큰 불(hts): HTS 관심그룹(번호 붙은 그룹 병합) + 키워드 분류표로 빠진 종목 자동 배정
  작은 불(kw): 키워드 분류표(data/keywords.csv) 세부 키워드 + 알파스퀘어(data/alphasquare.md)로 미분류 종목 보완
  바스켓: K-250·트럼프 같은 큰 바구니 → 대시보드엔 보이되 알람 제외
  독립 키워드: 어느 HTS 그룹과도 겹침이 낮은 키워드(#MLCC 등) → 자체 알람
출력 themes.json = {"built", "themes": {이름: {codes, kind, basket, independent, added, parent}}, "kw_of": {코드: [키워드]}}"""
import json, re, os, csv, time, collections as C
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))

def base_name(name):
    if name in CFG["merge_manual"]: return CFG["merge_manual"][name]
    return re.sub(r"(\s*-\s*\d+|\(\d+\)|\d+)$", "", name).strip() or name

def hts_groups(groups):
    out = {}
    for name, codes in groups.items():
        if name in CFG["exclude_groups"] or not codes or set(name) <= {"*"}: continue
        t = out.setdefault(base_name(name), [])
        for c in codes:
            if c not in t: t.append(c)
    return out

def keyword_themes():
    kc = CFG["keyword"]; kw = C.defaultdict(list); has_kw = set()
    for r in csv.DictReader(open(os.path.join(HERE, "data", "keywords.csv"), encoding="utf-8")):
        code = r["종목코드"].strip().zfill(6)
        for k in r["키워드"].split("|"):
            k = k.strip().lstrip("#").strip()
            if not k or any(p in k for p in kc["exclude_patterns"]): continue
            if code not in kw[k]: kw[k].append(code); has_kw.add(code)
    # 알파스퀘어: 키워드표에 없는 종목만 보완
    cur = None
    for line in open(os.path.join(HERE, "data", "alphasquare.md"), encoding="utf-8"):
        if line.startswith("### "): cur = re.sub(r"\s*\(\d+\)$", "", line[4:].strip())
        elif cur and (m := re.match(r"- .+ \((\w{6})\)", line.strip())) and m.group(1) not in has_kw:
            if m.group(1) not in kw[cur]: kw[cur].append(m.group(1))
    return {k: v for k, v in kw.items() if len(v) >= kc["min_stocks"]}

def build(groups):
    kc = CFG["keyword"]; basket = set(CFG["basket_groups"])
    hts = hts_groups(groups); kw = keyword_themes()
    core = {t: set(cs) for t, cs in hts.items() if t not in basket}
    def best(codes):
        s = set(codes); b = max(core, key=lambda t: len(s & core[t]))
        return b, len(s & core[b]) / len(s)
    kw_best = {k: best(cs) for k, cs in kw.items()}
    # 빠진 종목(바스켓 외 HTS 그룹에 없는 종목) → 키워드가 강하게 겹치는 HTS 그룹에 배정
    covered = set().union(*core.values()); added = C.defaultdict(list)
    for k, cs in kw.items():
        g, ov = kw_best[k]
        if ov < kc["assign_overlap"] or k in kc["basket"]: continue
        for c in cs:
            if c not in covered and c not in added[g]: added[g].append(c)
    themes = {}
    for t, cs in hts.items():
        themes[t] = {"codes": cs + added.get(t, []), "kind": "hts", "basket": t in basket,
                     "added": added.get(t, []), "independent": False, "parent": None}
    for k, cs in kw.items():
        g, ov = kw_best[k]
        same = any(k.replace(" ", "") in t or t in k for t in hts)   # #로봇↔로봇, #2차전지↔2차전지
        themes["#" + k] = {"codes": cs, "kind": "kw", "basket": k in kc["basket"], "added": [],
                           "independent": ov < kc["independent_overlap"] and not same, "parent": g}
    # 3번째 층: 인포스탁 공식 테마(데일리 특징테마 표에 2회+ 등장한 종목) → '◆테마명'
    ip = os.path.join(HERE, "data", "infostock.sqlite3")
    if os.path.exists(ip):
        import sqlite3
        con = sqlite3.connect(f"file:{ip}?mode=ro", uri=True)
        ism = C.defaultdict(list)
        for th, code, n in con.execute("select theme, code, count(*) from theme_members group by theme, code having count(*) >= 2"):
            ism[th].append(code)
        for th, cs in ism.items():
            if len(cs) < 3: continue
            g, ov = best(cs)
            bk = bool(re.search(r"지주사|대표주|우선주|밸류업|저PBR|신규상장|스팩", th))
            themes["◆" + th] = {"codes": cs, "kind": "is", "basket": bk, "added": [], "independent": ov < kc["independent_overlap"], "parent": g}
    kw_of = C.defaultdict(list)
    for k, cs in kw.items():
        if k in kc["basket"]: continue
        for c in cs: kw_of[c].append(k)
    return {"built": time.strftime("%Y-%m-%d %H:%M"), "themes": themes, "kw_of": kw_of}

def save(d):
    json.dump(d, open(os.path.join(HERE, "themes.json"), "w", encoding="utf-8"), ensure_ascii=False)

if __name__ == "__main__":
    d = build(json.load(open(os.path.join(HERE, "groups_snapshot.json"), encoding="utf-8")))
    save(d); th = d["themes"]
    hts = {k: v for k, v in th.items() if v["kind"] == "hts"}; kw = {k: v for k, v in th.items() if v["kind"] == "kw"}
    allc = {c for v in th.values() for c in v["codes"]}
    print(f"큰 불(HTS) {len(hts)}개 (바스켓 {sum(v['basket'] for v in hts.values())}) / 작은 불(키워드) {len(kw)}개 "
          f"(독립 {sum(v['independent'] for v in kw.values())}) / 전체 {len(allc)}종목")
    print("인포스탁 테마:", sum(1 for v in th.values() if v["kind"] == "is"), "개 (독립", sum(1 for v in th.values() if v["kind"] == "is" and v["independent"]), ")")
    print("자동 배정:", {k: len(v["added"]) for k, v in hts.items() if v["added"]})
    print("독립 키워드:", [k for k, v in kw.items() if v["independent"] and not v["basket"]])
