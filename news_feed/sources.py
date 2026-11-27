"""뉴스 출처 수집기 (RSS·포털) — 섹터 상승/news.py와 동일"""
import re, time, html as H, urllib.request
import hashlib
import unicodedata
from urllib.error import HTTPError, URLError
import socket

MAX_RESPONSE_BYTES=8*1024*1024
RSS_ITEM_LIMIT=200
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))

def is_featured_title(title):
    """Explicit publisher [특징주] label only, including normalized brackets."""
    s=unicodedata.normalize("NFKC", H.unescape(str(title or "")))
    return bool(re.search(r"\[\s*특징주\s*\]",s))

def canonical_article_url(raw):
    try:
        u = urlsplit(str(raw or ""))
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password:
            return ""
        query = sorted((k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
                       if not k.lower().startswith("utm_") and k.lower() not in {"ref", "fbclid", "gclid"})
        return urlunsplit((u.scheme, u.netloc.lower(), u.path, urlencode(query), ""))
    except ValueError:
        return ""

def article_key(raw):
    canonical = canonical_article_url(raw)
    return "u:" + hashlib.sha256(canonical.encode()).hexdigest() if canonical else ""

def publication_time(raw):
    if not raw:
        return None
    raw = _clean(raw)
    try:
        d = parsedate_to_datetime(raw)
    except (ValueError, TypeError, OverflowError):
        try:
            d = datetime.fromisoformat(raw.replace('Z', '+00:00'))
        except (ValueError, TypeError, OverflowError):
            return None
    return d.astimezone(KST).isoformat() if d is not None and d.tzinfo else None

def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0)", "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        raw = response.read(MAX_RESPONSE_BYTES+1)
    if len(raw)>MAX_RESPONSE_BYTES:
        raise ValueError("Feed response exceeds safety limit")
    m = re.search(rb'encoding=["\']([\w-]+)', raw[:200])
    enc = (m.group(1).decode() if m else "utf-8").lower()
    return raw.decode("cp949" if enc in ("euc-kr", "ks_c_5601-1987") else enc, errors="replace")

def fetch_checked(fetcher,name,url):
    """One retry only for transient failures, never bypass access or rate limits."""
    for attempt in (1,2):
        try:
            rows=fetcher(name,url)
            return rows,{"source":name,"status":"ok" if rows else "empty",
                         "count":len(rows),"attempts":attempt,
                         "checked_at":datetime.now(KST).isoformat(),
                         "timestamp_count":sum(bool(r.get("published_at")) for r in rows),
                         "possible_truncation":len(rows)>=RSS_ITEM_LIMIT}
        except Exception as e:
            if isinstance(e,HTTPError):
                transient=e.code in (500,502,503,504) and not (e.headers and e.headers.get("Retry-After"))
            else:
                transient=isinstance(e,TimeoutError) or isinstance(e,URLError) and isinstance(e.reason,TimeoutError)
            if attempt==1 and transient:
                time.sleep(1)
                continue
            info={"source":name,"status":"failed","count":0,"attempts":attempt,
                  "error_type":type(e).__name__,"checked_at":datetime.now(KST).isoformat()}
            if isinstance(e,HTTPError):info["http_status"]=e.code
            return [],info

def _clean(x):
    x = re.sub(r"(?s)<!\[CDATA\[(.*?)\]\]>", r"\1", x or "")
    return H.unescape(re.sub(r"<[^>]+>", "", x)).strip()

def fetch_rss(name, url):
    """RSS/Atom → [{id,title,press,time,url}]"""
    h = _get(url); out = []; observed = datetime.now(KST).isoformat()
    for it in re.findall(r"(?s)<(?:item|entry)\b.*?</(?:item|entry)>", h)[:RSS_ITEM_LIMIT]:
        t = re.search(r"(?s)<title[^>]*>(.*?)</title>", it)
        l = re.search(r"(?s)<link[^>]*>(.*?)</link>", it) or re.search(r'<link[^>]*href="([^"]+)"', it)
        d = re.search(r"(?is)<(?:pubDate|published|dcterms:issued|dc:issued)\b[^>]*>(.*?)</", it)
        if not t or not l: continue
        title, link = _clean(t.group(1)), _clean(l.group(1))
        tm = re.search(r"(\d{2}):(\d{2})", d.group(1)) if d else None
        hhmm = tm.group(0) if tm else ""
        if d and re.search(r"GMT|\+0000|Z$", d.group(1).strip()) and tm:           # UTC → KST
            hhmm = f"{(int(tm.group(1)) + 9) % 24:02d}:{tm.group(2)}"
        press = name.split()[0]
        if "news.google" in url and " - " in title: title, press = title.rsplit(" - ", 1)
        published = publication_time(d.group(1)) if d else None
        if published:
            hhmm = published[11:16]
        out.append({"id": link, "title": title, "press": press, "time": hhmm, "url": link,
                    "published_at": published, "publication_basis":"feed_published_field" if published else None, "source_feed": name, "observed_at": observed})
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
    h = _get(url); observed = datetime.now(KST).isoformat(); pat = r"https://n\.news\.naver\.com/mnews/article/\d+/\d+" if "naver" in url else r"https://v\.daum\.net/v/\d+"
    best = {}
    for m in re.finditer(r'(?s)<a[^>]+href="(' + pat + r')[^"]*"[^>]*>(.*?)</a>', h):
        t = _clean(m.group(2))
        if 10 <= len(t) <= 120 and len(t) > len(best.get(m.group(1), "")): best[m.group(1)] = t
    # Portal list has no trustworthy publication timestamp. Do not invent one.
    return [{"id": u, "title": t, "press": name.split()[0], "time": "", "url": u,
             "published_at": None, "source_feed": name, "observed_at": observed} for u, t in best.items()]

