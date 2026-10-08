"""뉴스 출처 수집기 (RSS·포털) — 섹터 상승/news.py와 동일"""
import re, time, html as H, urllib.request
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

