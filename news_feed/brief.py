"""인포스탁 무료 자료(전일자까지)로 '시황 정리' 생성 → news_feed/brief.json {날짜: {...}} 최근 7거래일.
섹터 상승/infostock.py의 파서를 옮겨온 것. 3시간에 한 번만 조회, 서버가 막으면 다음 실행에 재시도."""
import json, os, re, time, datetime, html as H, urllib.request
D = os.path.dirname(os.path.abspath(__file__))
API = "https://api.infostock.co.kr:9081/web/flash/list"
KST = datetime.timezone(datetime.timedelta(hours=9))

def fetch(menu, s, e):
    req = urllib.request.Request(API, method="POST", data=json.dumps({"menuType": menu, "count": 50, "startDate": s, "endDate": e}).encode(),
        headers={"Content-Type": "application/json", "Origin": "https://infostock.co.kr", "Referer": "https://infostock.co.kr/", "User-Agent": "Mozilla/5.0"})
    return (json.loads(urllib.request.urlopen(req, timeout=20).read().decode()).get("data") or {}).get("items") or []

def txt(h):
    h = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", "", h or "")
    h = re.sub(r"(?i)<br\s*/?>", "\n", h); h = re.sub(r"(?s)<[^>]+>", "", h)
    return re.sub(r"[ \t\r\xa0]+", " ", H.unescape(h)).strip()

def stocks_in(detail):
    m = None
    for m in re.finditer(r"(?:소식에|소식 속|소식 등에|이에 금일|이에|속에|가운데)\s*(?:금일\s*)?([^▷\n]{2,300}?)\s*등", detail): pass
    if not m: return []
    return [n.strip(" .·") for n in m.group(1).split(",") if 1 < len(n.strip()) <= 20 and not re.search(r"테마|관련주|업종", n)]

RT = [("무상증자", r"무상증자"), ("유상증자", r"유상증자|전환사채"), ("자사주", r"자사주|자기주식"), ("수주·계약", r"공급계약|수주|계약 체결|납품"),
      ("임상·허가", r"임상|FDA|허가|승인"), ("실적", r"실적|흑자|영업이익|매출"), ("M&A", r"인수|합병|최대주주|경영권|매각"),
      ("특허·기술", r"특허|기술이전"), ("정치", r"정치|인맥|대선|후보"), ("테마", r"테마.*(상승|강세)|관련주.*(상승|강세)|그룹주|수혜 기대")]
def rtype(r): return next((n for n, p in RT if re.search(p, r)), "기타")

def parse_day(items):
    out = {"kospi": "", "kosdaq": "", "bullets": [], "themes": [], "surge": []}
    for it in items:
        nt, h = it.get("newsType1") or "", it.get("content") or ""
        if nt in ("MARKET_FLASH_KOSPI_SUMMARY", "MARKET_FLASH_KOSDAQ_SUMMARY"):
            ls = [l.strip() for l in txt(h).split("\n") if l.strip() and not l.strip().startswith(("-", "제목"))]
            out["kospi" if "KOSPI" in nt else "kosdaq"] = ls[0] if ls else ""
        elif nt == "MARKET_FLASH_THEME_FEATURED":
            m = re.search(r"(?is)<b>\s*테마시황\s*</b>\s*</td>\s*<td[^>]*>(.*?)</td>", h)
            if m: out["bullets"] = [b.strip() for b in txt(m.group(1)).split("▷") if b.strip()][:8]
            for m in re.finditer(r"(?is)<td[^>]*rowspan=['\"]?2['\"]?[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*(?:</tr>)?\s*<tr[^>]*>\s*<td[^>]*>(.*?)</td>", h):
                th, rs, dt = txt(m.group(1)), txt(m.group(2)), txt(m.group(3))
                if th and rs: out["themes"].append({"theme": th, "reason": rs, "dir": "down" if "하락" in rs[-12:] else "up", "stocks": stocks_in(dt)[:6]})
        elif nt == "MARKET_FLASH_STOCK_JUMP":
            for ch in re.split(r"(?i)<tr", h)[1:]:
                tds = re.findall(r"(?is)<td[^>]*>(.*?)(?=<td|</tr|$)", ch)
                if len(tds) < 3: continue
                f = txt(tds[0]); c = re.search(r"\(([0-9A-Z]{6})\)", f)
                if not c: continue
                r = re.search(r"[+↑]?\s*([\d.]+)%", f); dy = re.search(r"\d+", txt(tds[1])); rs = txt(tds[2]).replace("\n", " ")
                out["surge"].append({"name": f.split("(")[0].strip(), "code": c.group(1), "rate": float(r.group(1)) if r else 30.0,
                                     "days": int(dy.group()) if dy else 1, "reason": rs, "rtype": rtype(rs)})
    out["surge"] = sorted(out["surge"], key=lambda s: -s["rate"])[:20]
    return out

def update(force=False):
    p = os.path.join(D, "brief.json")
    B = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"fetched": 0, "days": {}}
    if not force and time.time() - B.get("fetched", 0) < 3 * 3600: return B
    now = datetime.datetime.now(KST); yday = (now - datetime.timedelta(days=1)).strftime("%Y%m%d")
    start = (now - datetime.timedelta(days=10)).strftime("%Y%m%d")
    try: items = fetch("MENU_TODAY_SUMMARY", start, yday)
    except Exception as e:
        print("[brief] 인포스탁 조회 실패:", repr(e)); return B
    by = {}
    for it in items:
        if it.get("sendDate", "") <= yday: by.setdefault(it["sendDate"], []).append(it)
    for d, its in by.items(): B["days"][d] = parse_day(its)
    B["days"] = dict(sorted(B["days"].items())[-7:]); B["fetched"] = time.time()
    json.dump(B, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"[brief] 시황 정리 {len(by)}일 갱신 (최근 {max(B['days']) if B['days'] else '-'})")
    return B

if __name__ == "__main__":
    update(force=True)
