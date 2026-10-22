"""인포스탁 무료 자료 수집·파싱 (전일자까지만 — 무료 회원 범위).
  수집: 증시요약(1~10) / 데일리 특징 테마 / 전일 테마별 등락률  → data/infostock.sqlite3
  파싱: 시황(코스피·코스닥 마감) / 테마시황 요약 / 특징 테마(테마·사유·관련종목) / 상한가·급등(종목·사유·재료유형) / 테마 등락률 순위
사용:  python infostock.py backfill   (2013.03~어제, 최초 1회 10~20분)
       python infostock.py update     (최근 10일, app.py가 매일 아침 자동 실행)
       python infostock.py brief      (어제 브리핑 미리보기)"""
import json, os, re, sys, time, sqlite3, datetime, html as H, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "data", "infostock.sqlite3")
API = "https://api.infostock.co.kr:9081/web/flash/list"
MENUS = {"MENU_TODAY_SUMMARY": 4, "MENU_DAILY_FEATURED_THEME": 30, "MENU_THEME_FLUCTUATIONS": 30}  # 메뉴: 조회 창(일)
SCHEMA = """
create table if not exists posts(id text primary key, menu text, news_type text, send_date text, send_time text, title text, html text, parsed int default 0);
create table if not exists market_brief(date text, kind text, headline text, body text, primary key(date, kind));
create table if not exists theme_events(date text, source text, theme text, direction text, reason text, detail text, stocks text, codes text);
create table if not exists surge(date text, code text, name text, price int, rate real, days int, reason text, rtype text, primary key(date, code));
create table if not exists theme_rank2(date text, side text, rank int, theme text, theme_id text, rate real, primary key(date, side, rank));
create table if not exists theme_members(date text, theme_id text, theme text, theme_rate real, code text, name text, close int, rate real, volume int, primary key(date, theme_id, code));
create index if not exists ix_te_date on theme_events(date);
create table if not exists meta(k text primary key, v text);
"""

def db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    c = sqlite3.connect(DB, timeout=30)
    if os.name != "nt": c.execute("pragma journal_mode=MEMORY")   # 공유 폴더 테스트 환경용
    c.executescript(SCHEMA); return c

# ---------------- 수집 ----------------
def fetch(menu, start, end):
    body = json.dumps({"menuType": menu, "count": 50, "startDate": start, "endDate": end}).encode()
    req = urllib.request.Request(API, data=body, method="POST", headers={
        "Content-Type": "application/json", "Origin": "https://infostock.co.kr",
        "Referer": "https://infostock.co.kr/", "User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        j = json.loads(r.read().decode("utf-8"))
    return (j.get("data") or {}).get("items") or []

class Blocked(Exception): pass

def collect(start, end, log=print, pause=3.0):
    """start~end(YYYYMMDD, end는 어제 이하로 강제) 수집. 이미 있는 글은 건너뜀."""
    yday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y%m%d")
    end = min(end, yday); c = db(); n_new = 0
    for menu, step in MENUS.items():
        d = datetime.datetime.strptime(start, "%Y%m%d").date(); e = datetime.datetime.strptime(end, "%Y%m%d").date()
        while d <= e:
            w_end = min(d + datetime.timedelta(days=step - 1), e)
            items = []
            for attempt in range(3):
                try: items = fetch(menu, d.strftime("%Y%m%d"), w_end.strftime("%Y%m%d")); break
                except urllib.error.HTTPError as ex:
                    if ex.code in (403, 429):                       # 서버가 막으면 즉시 중단 (나중에 이어받기)
                        c.commit(); log(f"[인포스탁] 서버 차단({ex.code}) → 수집 중단. {d}부터 나중에 이어받음")
                        raise Blocked(d.strftime("%Y%m%d"))
                    log(f"[인포스탁] {menu} {d} 재시도 {attempt+1}: {ex!r}"); time.sleep(5)
                except Exception as ex:
                    log(f"[인포스탁] {menu} {d} 재시도 {attempt+1}: {ex!r}"); time.sleep(5)
            if len(items) >= 50: log(f"[인포스탁] 경고: {menu} {d}~{w_end} 50건 초과 가능")
            for it in items:
                if it.get("sendDate", "") > yday: continue          # 무료 범위(전일자까지)만
                cur = c.execute("insert or ignore into posts(id,menu,news_type,send_date,send_time,title,html) values(?,?,?,?,?,?,?)",
                                (it["id"], menu, it.get("newsType1") or it.get("newsType"), it.get("sendDate"),
                                 it.get("sendTime"), (it.get("title") or "").strip(), it.get("content") or ""))
                n_new += cur.rowcount
            c.commit(); d = w_end + datetime.timedelta(days=1); time.sleep(pause)
        log(f"[인포스탁] {menu} {start}~{end} 수집 완료")
    n_parsed = parse_pending(c)
    log(f"[인포스탁] 신규 글 {n_new}건, 파싱 {n_parsed}건")
    return n_new

def next_backfill_year():
    """아직 덜 받은 가장 이른 연도 (올해 제외). 다 받았으면 None."""
    today = datetime.date.today()
    have = dict(db().execute("select substr(send_date,1,4), count(distinct send_date) from posts "
                             "where menu='MENU_TODAY_SUMMARY' group by 1").fetchall())
    for y in range(2013, today.year):
        if have.get(str(y), 0) < (200 if y == 2013 else 230): return y
    return None

def backfill_step(log=print):
    """1년치만 천천히 수집 (app.py가 장 마감 후 1시간마다 호출). 남은 연도 수 반환."""
    y = next_backfill_year()
    if y is None: return 0
    log(f"[인포스탁] 과거자료 {y}년 수집 시작 (천천히)")
    collect("20130301" if y == 2013 else f"{y}0101", f"{y}1231", log=log)
    left = next_backfill_year()
    return 0 if left is None else datetime.date.today().year - left

# ---------------- 파싱 ----------------
def txt(h):
    h = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", "", h or "")
    h = re.sub(r"(?i)<br\s*/?>", "\n", h); h = re.sub(r"(?s)<[^>]+>", "", h)
    return re.sub(r"[ \t\r\xa0]+", " ", H.unescape(h)).strip()

NAME2CODE = None
def name2code():
    global NAME2CODE
    if NAME2CODE is None:
        NAME2CODE = {}
        p = os.path.join(HERE, "stock_master.json")
        if os.path.exists(p):
            for code, (nm, _) in json.load(open(p, encoding="utf-8"))["data"].items(): NAME2CODE[nm.replace(" ", "")] = code
    return NAME2CODE

def stocks_in(detail):
    """'이 같은 소식에 A, B, C 등 …' 문장에서 종목명 추출."""
    m = None
    for m in re.finditer(r"(?:소식에|소식 속|소식 등에|이에 금일|이에|속에|가운데)\s*(?:금일\s*)?([^▷\n]{2,300}?)\s*등", detail): pass
    if not m: return []
    names = [n.strip(" .·") for n in re.split(r",|、", m.group(1))]
    return [n for n in names if 1 < len(n) <= 20 and not re.search(r"테마|관련주|업종|섹터", n)]

def direction(reason):
    r = reason[-15:]
    return "down" if "하락" in r else ("mixed" if "엇갈" in r or "혼조" in r else "up")

def parse_theme_table(h):
    """특징 테마(섹터) 표 → [(테마, 사유, 상세)] + 테마시황 요약."""
    h = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", "", h)
    summary = ""
    m = re.search(r"(?is)<b>\s*테마시황\s*</b>\s*</td>\s*<td[^>]*>(.*?)</td>", h)
    if m: summary = txt(m.group(1))
    rows = []
    for m in re.finditer(r"(?is)<td[^>]*rowspan=['\"]?2['\"]?[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*(?:</tr>)?\s*<tr[^>]*>\s*<td[^>]*>(.*?)</td>", h):
        theme, reason, detail = txt(m.group(1)), txt(m.group(2)), txt(m.group(3))
        if theme and reason: rows.append((theme, reason, detail))
    return summary, rows

RTYPES = [("무상증자", r"무상증자"), ("유상증자", r"유상증자|전환사채|CB 발행"), ("자사주", r"자사주|자기주식"),
          ("수주·계약", r"공급계약|수주|계약 체결|납품"), ("임상·허가", r"임상|FDA|허가|승인|품목"),
          ("실적", r"실적|흑자|영업이익|매출"), ("M&A·지배구조", r"인수|합병|M&A|최대주주|경영권|매각"),
          ("특허·기술", r"특허|기술이전|개발 성공"), ("정치·인맥", r"정치|인맥|대선|후보|총선|지지율"),
          ("테마 동반", r"테마.*(상승|강세)|관련주.*(상승|강세)|그룹주|수혜 기대")]
def rtype(reason):
    for name, pat in RTYPES:
        if re.search(pat, reason): return name
    return "기타"

def parse_surge(h):
    out = []
    for chunk in re.split(r"(?i)<tr", h)[1:]:
        tds = re.findall(r"(?is)<td[^>]*>(.*?)(?=<td|</tr|$)", chunk)
        if len(tds) < 3: continue
        first = txt(tds[0]); code = re.search(r"\(([0-9A-Z]{6})\)", first)
        if not code: continue
        name = first.split("(")[0].strip().replace("\n", "")
        price = re.search(r"([\d,]+)원", first); rate = re.search(r"[+↑]?\s*([\d.]+)%", first)
        days = re.search(r"\d+", txt(tds[1])); reason = txt(tds[2]).replace("\n", " ")
        out.append((code.group(1), name, int(price.group(1).replace(",", "")) if price else None,
                    float(rate.group(1)) if rate else 30.0, int(days.group()) if days else None, reason))
    return out

def parse_market(h):
    t = txt(h); lines = [l.strip() for l in t.split("\n") if l.strip() and not l.strip().startswith("-")
                         and not l.strip().startswith("제목") and "인포스탁" not in l]
    head = lines[0] if lines else ""; body = "\n".join(lines[1:6])
    return head, body

def parse_rank(h):
    out = []
    for seg in re.split(r"(?i)<table class=s_table", h)[1:]:
        side = "down" if "하락률" in seg[:600] else "up"
        for m in re.finditer(r"(?is)<tr[^>]*>\s*<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>\s*([+\-]?[\d.]+)%", seg):
            tid = re.search(r"ThemeDB/(?:ThemeAllAllowed/)?(\d+)", m.group(2))
            out.append((side, int(m.group(1)), txt(m.group(2)), tid.group(1) if tid else "", float(m.group(3))))
    return out

def parse_daily(h):
    """데일리 특징 테마: 테마시황 요약 + 테마별(사유, 상세) + 인포스탁 세부테마 표(테마ID·등락률·상위 10종목)."""
    t = txt(h); parts = re.split(r"\n?- (.{1,60}?) -\n", "\n" + t)
    summary, rows = "", []
    for i in range(1, len(parts) - 1, 2):
        title, body = parts[i].strip(), parts[i + 1]
        body = body.split("테마명등락률종목명")[0].strip()
        if title == "테마시황": summary = body; continue
        lines = [l for l in body.split("\n") if l.strip()]
        if lines: rows.append((title, lines[0].strip(), "\n".join(lines[1:])))
    members = []
    for tb in re.findall(r"(?is)<table[^>]*dataframe.*?</table>", h):
        tm = re.search(r"(?is)ThemeDB/(\d+)[^>]*>(.*?)</a>\s*</td>\s*<td[^>]*>\s*([+\-]?[\d.]+)%", tb)
        if not tm: continue
        tid, tname, trate = tm.group(1), txt(tm.group(2)), float(tm.group(3))
        for r in re.finditer(r"(?is)stockitem\?code=(\w{6})[^>]*>(.*?)</a>\s*</td>\s*<td>([\d,]+)</td>\s*<td[^>]*>\s*([+\-]?[\d.]+)%\s*</td>\s*<td>([\d,]+)</td>", tb):
            members.append((tid, tname, trate, r.group(1), txt(r.group(2)), int(r.group(3).replace(",", "")), float(r.group(4)), int(r.group(5).replace(",", ""))))
    return summary, rows, members

def parse_pending(c=None):
    c = c or db(); n2c = name2code(); n = 0
    for pid, menu, nt, date, title, h in c.execute("select id,menu,news_type,send_date,title,html from posts where parsed=0").fetchall():
        try:
            if nt in ("MARKET_FLASH_KOSPI_SUMMARY", "MARKET_FLASH_KOSDAQ_SUMMARY") or re.search(r"\((1|2)\) - 코", title):
                head, body = parse_market(h); kind = "KOSPI" if ("KOSPI" in (nt or "") or "(1)" in title) else "KOSDAQ"
                c.execute("insert or replace into market_brief values(?,?,?,?)", (date, kind, head, body))
            elif nt == "MARKET_FLASH_THEME_FEATURED" or "(3)" in title or menu == "MENU_DAILY_FEATURED_THEME":
                src = "daily" if menu == "MENU_DAILY_FEATURED_THEME" else "summary"
                if src == "daily":
                    summary, rows, members = parse_daily(h)
                    for m in members: c.execute("insert or replace into theme_members values(?,?,?,?,?,?,?,?,?)", (date,) + m)
                else:
                    summary, rows = parse_theme_table(h)
                if summary: c.execute("insert or replace into market_brief values(?,?,?,?)", (date, "THEME_" + src, "", summary))
                c.execute("delete from theme_events where date=? and source=?", (date, src))
                for theme, reason, detail in rows:
                    names = stocks_in(detail); codes = [n2c.get(x.replace(" ", ""), "") for x in names]
                    c.execute("insert into theme_events values(?,?,?,?,?,?,?,?)", (date, src, theme, direction(reason), reason, detail,
                              json.dumps(names, ensure_ascii=False), json.dumps(codes)))
            elif nt == "MARKET_FLASH_STOCK_JUMP" or "(6)" in title:
                for code, name, price, rate, days, reason in parse_surge(h):
                    c.execute("insert or replace into surge values(?,?,?,?,?,?,?,?)", (date, code, name, price, rate, days, reason, rtype(reason)))
            elif menu == "MENU_THEME_FLUCTUATIONS":
                m = re.search(r"(\d{1,2})월\s*(\d{1,2})일", title)
                if m:
                    y = int(date[:4]) - (1 if int(m.group(1)) == 12 and date[4:6] == "01" else 0)
                    d0 = f"{y}{int(m.group(1)):02d}{int(m.group(2)):02d}"
                    for side, rk, th, tid, rt in parse_rank(h): c.execute("insert or replace into theme_rank2 values(?,?,?,?,?,?)", (d0, side, rk, th, tid, rt))
            c.execute("update posts set parsed=1 where id=?", (pid,)); n += 1
        except Exception as e:
            c.execute("update posts set parsed=-1 where id=?", (pid,))
            print("[인포스탁] 파싱 실패", date, title, repr(e))
    c.commit(); return n

# ---------------- 활용 ----------------
def last_date(c):
    r = c.execute("select max(date) from market_brief").fetchone(); return r[0] if r else None

def brief(date=None, max_len=3800):
    """가장 최근 거래일(=어제) 시황 브리핑 텍스트."""
    c = db(); date = date or last_date(c)
    if not date: return None, None
    mb = {k: (h, b) for k, h, b in c.execute("select kind,headline,body from market_brief where date=?", (date,))}
    ev = c.execute("select theme,reason,stocks,direction from theme_events where date=? and source=(case when exists(select 1 from theme_events where date=? and source='daily') then 'daily' else 'summary' end)", (date, date)).fetchall()
    sg = c.execute("select name,rate,days,reason,rtype from surge where date=? order by rate desc", (date,)).fetchall()
    d = f"{date[4:6]}/{date[6:]}"
    L = [f"📰 {d} 시황 정리 (인포스탁)"]
    for k in ("KOSPI", "KOSDAQ"):
        if k in mb and mb[k][0]: L.append("• " + mb[k][0])
    th = (mb.get("THEME_daily") or mb.get("THEME_summary") or ("", ""))[1]
    if th:
        L.append("\n🧭 테마시황")
        for b in [x.strip() for x in th.split("▷") if x.strip()][:7]: L.append("▷ " + b[:160])
    if ev:
        L.append("\n🔥 특징 테마")
        for theme, reason, stocks, dr in ev[:8]:
            s = ", ".join(json.loads(stocks)[:4])
            L.append(f"{'▲' if dr=='up' else '▼' if dr=='down' else '◆'} {theme} — {reason}" + (f"\n   {s}" if s else ""))
    if sg:
        L.append("\n🚀 상한가·급등")
        for name, rate, days, reason, rt in sg[:10]:
            L.append(f"{name} +{rate:.1f}%{f' ({days}일)' if days and days > 1 else ''} [{rt}] {reason[:70]}")
    text = "\n".join(L)
    return date, (text[:max_len] + "\n…") if len(text) > max_len else text

def reasons(days=7):
    """최근 days일 종목별 사유 {code: {date, reason, rtype, theme}} — 알람 '왜 오르나' 첨부용."""
    c = db(); since = (datetime.date.today() - datetime.timedelta(days=days)).strftime("%Y%m%d"); out = {}
    for date, code, reason, rt in c.execute("select date,code,reason,rtype from surge where date>=? order by date", (since,)):
        out[code] = {"date": date, "reason": reason, "rtype": rt}
    for date, theme, reason, codes in c.execute("select date,theme,reason,codes from theme_events where date>=? and direction='up' order by date", (since,)):
        for cd in json.loads(codes or "[]"):
            if cd and (cd not in out or out[cd]["date"] <= date):
                out[cd] = {"date": date, "reason": f"{theme}: {reason}", "rtype": "테마"}
    return out

def snapshot_for_dashboard():
    c = db(); date = last_date(c)
    if not date: return {}
    mb = {k: (h, b) for k, h, b in c.execute("select kind,headline,body from market_brief where date=?", (date,))}
    ev = c.execute("select theme,reason,stocks,direction from theme_events where date=? and source in ('daily','summary') group by theme", (date,)).fetchall()
    sg = c.execute("select name,code,rate,days,reason,rtype from surge where date=? order by rate desc limit 15", (date,)).fetchall()
    th = (mb.get("THEME_daily") or mb.get("THEME_summary") or ("", ""))[1]
    return {"date": date, "kospi": mb.get("KOSPI", ("", ""))[0], "kosdaq": mb.get("KOSDAQ", ("", ""))[0],
            "bullets": [x.strip() for x in th.split("▷") if x.strip()][:8],
            "themes": [{"theme": a, "reason": b, "stocks": json.loads(s)[:5], "dir": d} for a, b, s, d in ev],
            "surge": [{"name": a, "code": b, "rate": r, "days": d, "reason": e, "rtype": t} for a, b, r, d, e, t in sg]}

if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    except Exception: pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else "update"
    today = datetime.date.today()
    if cmd == "backfill":
        # 실제로 받은 거래일 수로 연도별 완료 여부 판단 (차단·중단 후에도 정확히 이어받기)
        c = db(); have = dict(c.execute("select substr(send_date,1,4), count(distinct send_date) from posts "
                                         "where menu='MENU_TODAY_SUMMARY' group by 1").fetchall())
        todo = [y for y in range(2013, today.year + 1)
                if have.get(str(y), 0) < (200 if y == 2013 else (230 if y < today.year else 0)) or y == today.year]
        print(f"백필 대상 연도: {todo} (중간에 끊겨도 다시 실행하면 이어받음)", flush=True)
        for y in todo:
            try: collect(f"{y}0101" if y > 2013 else "20130301", f"{y}1231", log=lambda m: print(m, flush=True))
            except Blocked:
                print(f"서버가 요청을 막았습니다. 몇 시간 뒤 infostock_backfill.bat을 다시 실행하면 {y}년부터 이어받습니다.", flush=True); break
            print(f"== {y}년 완료 ==", flush=True); time.sleep(30)
    elif cmd == "update":
        collect((today - datetime.timedelta(days=10)).strftime("%Y%m%d"), today.strftime("%Y%m%d"))
    elif cmd == "reparse":
        c = db(); c.execute("update posts set parsed=0"); c.commit(); print(parse_pending(c))
    elif cmd == "brief":
        print(brief()[1])
