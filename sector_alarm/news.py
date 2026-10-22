"""뉴스 키워드 알람: 네이버 금융 '실시간 속보'를 1분마다 읽어 키워드 사전(data/news_keywords.json)·종목명과 매칭.
점수 = 키워드 가중치 합(상위 2개) + 종목명 언급 보너스 → min_score 이상이면 알람.  테스트: python news.py"""
import json, os, re, sys, time, html as H, urllib.request, collections as C
import keywords
HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://finance.naver.com/news/news_list.naver?mode=LSS2D&section_id=101&section_id2=258&page={}"

def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0)", "Accept": "*/*"})
    raw = urllib.request.urlopen(req, timeout=timeout).read()
    m = re.search(rb'encoding=["\']([\w-]+)', raw[:200])
    enc = (m.group(1).decode() if m else "utf-8").lower()
    return raw.decode("cp949" if enc in ("euc-kr", "ks_c_5601-1987") else enc, errors="replace")

def _clean(x):
    x = re.sub(r"(?s)<!\[CDATA\[(.*?)\]\]>", r"\1", x or "")
    return H.unescape(re.sub(r"<[^>]+>", "", x)).strip()

def fetch_rss(name, url):
    """RSS/Atom → [{id,title,press,time,url}]"""
    h = _get(url); out = []
    for it in re.findall(r"(?s)<(?:item|entry)\b.*?</(?:item|entry)>", h)[:40]:
        t = re.search(r"(?s)<title[^>]*>(.*?)</title>", it)
        l = re.search(r"(?s)<link[^>]*>(.*?)</link>", it) or re.search(r'<link[^>]*href="([^"]+)"', it)
        d = re.search(r"(?s)<(?:pubDate|dc:date|updated|published)>(.*?)</", it)
        if not t or not l: continue
        title, link = _clean(t.group(1)), _clean(l.group(1))
        tm = re.search(r"(\d{2}):(\d{2})", d.group(1)) if d else None
        hhmm = tm.group(0) if tm else ""
        if d and re.search(r"GMT|\+0000|Z$", d.group(1).strip()) and tm:           # UTC → KST
            hhmm = f"{(int(tm.group(1)) + 9) % 24:02d}:{tm.group(2)}"
        press = name.split()[0]
        if "news.google" in url and " - " in title: title, press = title.rsplit(" - ", 1)
        out.append({"id": link, "title": title, "press": press, "time": hhmm, "url": link})
    return out

def norm(t):
    return re.sub(r"[^가-힣A-Za-z0-9]", "", re.sub(r"\[[^\]]*\]", "", t))[:28]

def fetch_naver(pages=2):
    out = []
    for p in range(1, pages + 1):
        req = urllib.request.Request(URL.format(p), headers={"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com/"})
        raw = urllib.request.urlopen(req, timeout=10).read()
        h = raw.decode("cp949", errors="replace")
        for m in re.finditer(r'(?s)<dd class="articleSubject">\s*<a href="([^"]+)"[^>]*>(.*?)</a>.*?<span class="press">(.*?)</span>.*?<span class="wdate">(.*?)</span>', h):
            url, title, press, wdate = m.groups()
            aid = re.search(r"article_id=(\d+)", url); oid = re.search(r"office_id=(\d+)", url)
            nid = f"{oid.group(1) if oid else ''}_{aid.group(1) if aid else url}"
            link = f"https://n.news.naver.com/mnews/article/{oid.group(1)}/{aid.group(1)}" if aid and oid else "https://finance.naver.com" + H.unescape(url)
            out.append({"id": nid, "title": H.unescape(re.sub(r"<[^>]+>", "", title)).strip(), "press": press.strip(),
                        "time": wdate.strip()[-5:], "url": link})
        time.sleep(0.5)
    return out

def fetch_portal(name, url):
    """네이버 속보/다음 경제 HTML: 기사 링크별로 가장 긴 링크 텍스트를 제목으로."""
    h = _get(url); pat = r"https://n\.news\.naver\.com/mnews/article/\d+/\d+" if "naver" in url else r"https://v\.daum\.net/v/\d+"
    best = {}
    for m in re.finditer(r'(?s)<a[^>]+href="(' + pat + r')[^"]*"[^>]*>(.*?)</a>', h):
        t = _clean(m.group(2))
        if 10 <= len(t) <= 120 and len(t) > len(best.get(m.group(1), "")): best[m.group(1)] = t
    return [{"id": u, "title": t, "press": name.split()[0], "time": time.strftime("%H:%M"), "url": u} for u, t in best.items()]

BAD = {}   # 실패한 RSS: {이름: 다음 재시도 시각}
def fetch(nc):
    items = []
    if nc.get("naver", True):
        try: items += fetch_naver(nc["pages"])
        except Exception: pass
    for name, url in nc.get("portals", {}).items():
        if BAD.get(name, 0) > time.time(): continue
        try: items += fetch_portal(name, url)
        except Exception: BAD[name] = time.time() + 1800
    for name, url in nc.get("rss", {}).items():
        if BAD.get(name, 0) > time.time(): continue
        try: items += fetch_rss(name, url)
        except Exception: BAD[name] = time.time() + 1800        # 실패하면 30분 쉼
    return items

class Watcher:
    def __init__(self, cfg):
        self.c = cfg["news"]
        self.kw = json.load(open(os.path.join(HERE, "data", "news_keywords.json"), encoding="utf-8"))
        self.bi = {k: k.split() for k in self.kw if " " in k}
        m = json.load(open(os.path.join(HERE, "stock_master.json"), encoding="utf-8"))["data"]
        self.names = {v[0]: c for c, v in m.items() if len(v[0]) >= 3}       # 2글자 종목명은 오탐이 많아 제외
        self.seen, self.sent = set(), C.deque()

    def match(self, title):
        """단어 단위 매칭. 특정 테마에 쏠리지 않는 일반 단어(spec<min_spec)는 점수 30%만 반영."""
        cands = keywords.candidates(title) | {w for w in keywords.tokens(title) if w}
        hits = sorted(((k, self.kw[k]) for k in cands if k in self.kw), key=lambda x: -x[1]["w"])
        bis = [k for k, _ in hits if " " in k]
        hits = [(k, v) for k, v in hits if " " in k or not any(k in b.split() for b in bis)]
        def eff(k, v): return v["w"] * (1 if " " in k or (v["themes"] and v["themes"][0][1] >= self.c.get("min_spec", 0.3)) else 0.3)
        hits.sort(key=lambda x: -eff(*x))
        stocks = [(n, c) for n, c in self.names.items() if n in title][:3]
        ev = [e for e in self.c.get("event_words", []) if e in title]
        score = sum(eff(k, v) for k, v in hits[:2]) + (6 if stocks else 0) + (5 if ev and (stocks or hits) else 0)
        return score, hits[:3], stocks

    def poll(self):
        """새 기사 중 알람 대상 [(score, item, hits, stocks)]. 같은 기사(제목 앞부분 동일)는 한 번만."""
        out = []
        for it in fetch(self.c):
            key = norm(it["title"])
            if it["id"] in self.seen or key in self.seen: continue
            self.seen.add(it["id"]); self.seen.add(key)
            sc, hits, stocks = self.match(it["title"])
            if hits and sc >= self.c["min_score"]: out.append((round(sc, 1), it, hits, stocks))
        if len(self.seen) > 5000: self.seen = set(list(self.seen)[-2000:])
        return out

    def allow(self):
        now = time.time()
        while self.sent and now - self.sent[0] > 600: self.sent.popleft()
        if len(self.sent) >= self.c["max_per_10min"]: return False
        self.sent.append(now); return True

def fmt(sc, it, hits, stocks, rate_of=None):
    th = C.Counter()
    for _, v in hits:
        for t, s in v["themes"][:2]: th[t] += s
    rel = " · ".join(t for t, _ in th.most_common(2))
    st = ", ".join(f"{n}{'' if not rate_of or rate_of(c) is None else f' {rate_of(c):+.1f}%'}" for n, c in stocks)
    kws = " ".join("#" + k.replace(" ", "_") for k, _ in hits)
    lines = [f"🗞 {it['title']}", f"  {it['press']} {it['time']} · {kws} (점수 {sc})"]
    if rel: lines.append(f"  → 연관 테마: {rel}")
    if st: lines.append(f"  → 종목: {st}")
    lines.append(f"  {it['url']}")
    return "\n".join(lines)

if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
    w = Watcher(cfg); nc = cfg["news"]; items = []
    try: x = fetch_naver(nc["pages"]); items += x; print(f"OK  네이버 실시간속보 {len(x)}건")
    except Exception as e: print(f"ERR 네이버 {e!r}")
    for name, url in nc["rss"].items():
        try: x = fetch_rss(name, url); items += x; print(f"{'OK ' if x else 'EMP'} {name} {len(x)}건  예: {x[0]['time'] + ' ' + x[0]['title'][:40] if x else ''}")
        except Exception as e: print(f"ERR {name} {str(e)[:80]}")
    print(f"\n수집 {len(items)}건\n")
    for it in items:
        sc, hits, stocks = w.match(it["title"])
        mark = "★" if hits and sc >= cfg["news"]["min_score"] else " "
        print(f"{mark} {sc:5.1f} {it['time']} {it['title'][:60]}  {[k for k,_ in hits]} {[n for n,_ in stocks]}")
