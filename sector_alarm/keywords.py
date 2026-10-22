"""뉴스 키워드 사전 빌더: 시그널리포트(2022~, 뉴스제목+급등종목) + 인포스탁(2013~, 급등·테마 사유)
→ data/news_keywords.json  {키워드: {w, days, recent, avg, themes, stocks}}
사용: python keywords.py [시그널리포트 DB 경로]"""
import json, os, re, sys, math, sqlite3, datetime, collections as C
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
STOP = set("""특징주 단독 속보 종합 관련 관련주 기대 기대감 상승 급등 강세 주가 소식 이유 투자 확대 계획 지난 올해 내년 국내 글로벌 시장
기업 국내외 추진 진행 발표 공개 예정 가능성 최대 최고 대비 전망 영향 이후 위해 통해 대한 따른 만에 이상 개월 사업 산업 업계 확보 성공 체결
증가 기록 신규 본격 돌파 목표가 리포트 브리핑 클릭 e종목 오늘 마감 장중 코스피 코스닥 상한가 하한가 증권 주식 종목 회사 대표 사장 회장
선정 지속 주목 부각 성장 핵심 규모 기반 차세대 추가 진입 진출 공략 최초 역대 사상 논의 개선 상향 하향 소식에 기대감에 영업익 매출 실적
수혜 수혜주 테마 테마주 부상 효과 가속 본격화 계약 공급 개발 기술 협력 세계 미국 중국 한국 일본 정부 우리 신고가 연속 거래 마켓 머니
vs VS 이틀 부문 브랜드 등에 등 속 속에 금일 전일 이날 일부 대표주 중소형 상위 하락 하락률 상승률 상승세 강세를 약세 엇갈림 우려 주당 고객사 부각되며 호조 테스트 생산 수요 공장 부품 소재 대통령 상장 첫날 상한 모멘텀 데뷔 일부 결정 개시 파트너 주도 솔루션 토탈 투자자 개인 외국인 기관 순매수 매수 매도 시총 목표 의견 유지 커버리지 분석 보고서 증권사 프리뷰 인터뷰 칼럼 사설 포토 영상""".split())
PART = re.compile(r"(으로|에서|까지|부터|에게|하고|이며|으며|에는|에도|과의|와의|으로의|들의|들이|들은|에|의|를|을|가|이|은|는|로|와|과|도|만)$")

NOUN_GA = r"(유가|주가|원가|물가|단가|평가|시가|지가|대가|증가|국가|작가|전문가|투자가|이자|고객이|미사이)$"   # 조사처럼 보이는 명사 끝

def tokens(title):
    t = re.sub(r"\\?\[[^\]]*\]|\([^)]*\)|<[^>]*>|['\"“”‘’…·,!?]", " ", title)
    out = []
    for w in re.findall(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9&\-.+]*", t):
        if len(w) > 2 and re.search(r"[가-힣]$", w) and not re.search(NOUN_GA, w): w = PART.sub("", w)
        if len(w) < 2 or w in STOP or re.fullmatch(r"[\d.,%]+[가-힣]{0,2}", w): out.append(None); continue
        out.append(w)
    return out

def candidates(title):
    tk = tokens(title); s = {w for w in tk if w}
    for a, b in zip(tk, tk[1:]):
        if a and b: s.add(a + " " + b)
    return s

def build(sig_db, info_db=None):
    td = json.load(open(os.path.join(HERE, "themes.json"), encoding="utf-8"))
    inv = C.defaultdict(set)
    for n, t in td["themes"].items():
        if not t["basket"] and t["kind"] == "hts": [inv[c].add(n) for c in t["codes"]]
    master = json.load(open(os.path.join(HERE, "stock_master.json"), encoding="utf-8"))["data"]
    names = {v[0] for v in master.values()}                    # 종목명은 키워드에서 제외(뉴스에서 따로 매칭)
    days, pcts, th, st, titles = (C.defaultdict(set), C.defaultdict(list), C.defaultdict(C.Counter),
                                  C.defaultdict(C.Counter), C.defaultdict(set))
    def feed(date, text, stocks):           # stocks: [(name, code, pct)]
        mx = min(max([p or 0 for _, _, p in stocks] or [0]), 30)   # 신규상장 +300% 등 상한 30
        for k in candidates(text):
            if any(w in names or w.endswith("증권") or "-" in w and w.split("-")[-1] in ("키움", "하나", "KB") for w in k.split()): continue
            titles[k].add(text[:40])
            if date in days[k]: continue
            days[k].add(date); pcts[k].append(mx)
            for nm, cd, p in stocks:
                st[k][(nm, cd)] += 1
                for t in inv.get(cd, ()): th[k][t] += 1
    # 1) 시그널리포트: 뉴스 제목 ↔ 같은 블록 종목
    con = sqlite3.connect(f"file:{sig_db}?mode=ro", uri=True)
    blk = C.defaultdict(list)
    for bid, nm, cd, p in con.execute("select theme_block_id, stock_name_raw, matched_code, pct_change from stock_mentions"):
        blk[bid].append((nm, cd or "", p))
    for d, title, bid in con.execute("select b.report_date, n.title, b.id from news_items n join theme_blocks b on b.id=n.theme_block_id"):
        feed(d.replace("-", ""), title, blk.get(bid, []))
    # 2) 인포스탁: 급등 사유 / 테마 사유 (있으면)
    ip = info_db or os.path.join(HERE, "data", "infostock.sqlite3")
    if os.path.exists(ip):
        ic = sqlite3.connect(f"file:{ip}?mode=ro", uri=True)
        for d, nm, cd, r, reason in ic.execute("select date,name,code,rate,reason from surge"): feed(d, reason, [(nm, cd, r)])
        for d, reason, names, codes in ic.execute("select date,reason,stocks,codes from theme_events where direction='up'"):
            feed(d, reason, [(n, c, 10) for n, c in zip(json.loads(names), json.loads(codes))])
    cut = (datetime.date.today() - datetime.timedelta(days=365)).strftime("%Y%m%d")
    out = {}
    for k, ds in days.items():
        n = len(ds); bi = " " in k; nt = len(titles[k])
        if n < (4 if bi else 6) or nt < (4 if bi else 6): continue
        n = min(n, nt)
        tot = sum(th[k].values()) or 1; top = th[k].most_common(3)
        spec = top[0][1] / tot if top else 0                     # 특정 테마 쏠림 정도
        avg = sum(pcts[k]) / len(pcts[k])
        recent = sum(1 for d in ds if d >= cut)
        w = math.log1p(n) * (0.5 + spec) * min(avg, 30) / 10 * (1.3 if bi else 1) * (1 + min(recent, 20) / 20)
        out[k] = {"w": round(w, 2), "days": n, "recent": recent, "avg": round(avg, 1),
                  "themes": [[t, round(c / tot, 2)] for t, c in top],
                  "stocks": [[nm, cd, c] for (nm, cd), c in st[k].most_common(5)]}
    seen = {}
    for k in sorted(out, key=lambda k: -out[k]["w"]):
        sig = frozenset(list(titles[k])[:50]) if " " in k else None
        if sig is not None:
            if sig in seen: out.pop(k); continue
            seen[sig] = k
    # (단어 키워드는 지우지 않음: 뉴스 매칭 시 2단어 키워드가 걸리면 그 안의 단어는 중복 제외됨)
    keep = dict(sorted(out.items(), key=lambda x: -x[1]["w"])[:CFG.get("news", {}).get("max_keywords", 800)])
    json.dump(keep, open(os.path.join(HERE, "data", "news_keywords.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    return keep

if __name__ == "__main__":
    kw = build(sys.argv[1] if len(sys.argv) > 1 else CFG["signal_db"])
    print(len(kw), "개 키워드")
    for k, v in list(kw.items())[:60]: print(f"{k:16s} w{v['w']:5.1f} {v['days']:3d}일(최근{v['recent']}) 평균+{v['avg']}% {v['themes'][:2]}")
