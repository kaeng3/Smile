"""테마 점등 알람 — 장중 실행 본체.  실행: run.bat (또는 python app.py) → http://localhost:8000
시간대별 동작
  08:00~08:39  NXT 프리마켓 등락률로 테마 강도          (장전)
  08:40~08:59  동시호가 예상체결로 테마 강도, 08:55 장전 요약 알람
  09:00~15:30  3초 폴링 + 웹소켓(VI·대장주 실시간) → 점등(1~3단계) 알람 + 초기 점등(⚡) 감지
  그 외        1분마다 종가 기준 갱신
매일 첫 실행 시: 토큰·종목마스터·관심그룹(테마 사전) 새로 받음."""
import sys, json, os, time, datetime, threading, traceback, urllib.request, urllib.parse
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
import kiwoom, engine, early, themes as themes_mod, infostock, news, theme_kb

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")
cfg = json.load(open(CFG_PATH, encoding="utf-8"))
LOG_DIR = os.path.join(HERE, "logs"); os.makedirs(LOG_DIR, exist_ok=True)
SNAP = {"time": "", "status": "시작 중", "phase": "", "themes": [], "alerts": [], "early": [], "vi": [],
        "premarket": [], "built": "", "ws": ""}

def log(msg, kind="app"):
    print(msg)
    with open(os.path.join(LOG_DIR, time.strftime(f"{kind}_%Y%m%d.log")), "a", encoding="utf-8") as f:
        f.write(time.strftime("[%H:%M:%S] ") + msg + "\n")

# ---------- 텔레그램 ----------
def tg(method, **params):
    url = f"https://api.telegram.org/bot{cfg['telegram']['bot_token']}/{method}"
    with urllib.request.urlopen(url, data=urllib.parse.urlencode(params).encode(), timeout=10) as r:
        return json.loads(r.read())

def tg_ready():
    t = cfg["telegram"]
    if not t.get("bot_token"): return False
    if not t.get("chat_id"):
        ups = tg("getUpdates").get("result", [])
        if not ups: log("[텔레그램] 봇에게 아무 메시지나 먼저 보내주세요"); return False
        t["chat_id"] = str(ups[-1]["message"]["chat"]["id"])
        json.dump(cfg, open(CFG_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        log(f"[텔레그램] chat_id 저장: {t['chat_id']}")
    return True

def notify(text, kind="alerts", send=True):
    log(text + "\n", kind)
    if not send: return
    try:
        if tg_ready(): tg("sendMessage", chat_id=cfg["telegram"]["chat_id"], text=text)
    except Exception as e: log(f"[텔레그램 오류] {e}")

# ---------- 보조 ----------
def refresh_themes():
    try:
        g = kiwoom.watch_groups()
        json.dump(g, open(os.path.join(HERE, "groups_snapshot.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        d = themes_mod.build(g); themes_mod.save(d); log(f"[테마] 관심그룹 재조회 → 사전 갱신 {d['built']}")
        return d
    except Exception as e:
        log(f"[테마] 갱신 실패, 기존 사전 사용: {e!r}")
        return json.load(open(os.path.join(HERE, "themes.json"), encoding="utf-8"))

INFO = {"reasons": {}, "brief_date": None, "busy": False, "bf_next": time.time() + 2 * 3600}

def infostock_refresh():
    """어제까지의 인포스탁 자료 갱신(백그라운드) → 사유 캐시·대시보드 브리핑 갱신."""
    if INFO["busy"] or not cfg.get("infostock", {}).get("enable"): return
    def work():
        INFO["busy"] = True
        try:
            infostock.collect((datetime.date.today() - datetime.timedelta(days=10)).strftime("%Y%m%d"),
                              datetime.date.today().strftime("%Y%m%d"), log=lambda m: log(m))
            INFO["reasons"] = infostock.reasons(cfg["infostock"]["reason_days"])
            SNAP["brief"] = infostock.snapshot_for_dashboard()
        except infostock.Blocked: log("[인포스탁] 서버 차단 → 오늘은 기존 자료 사용")
        except Exception as e: log(f"[인포스탁] 갱신 실패: {e!r}")
        finally: INFO["busy"] = False
    threading.Thread(target=work, daemon=True).start()

LAST_Q = {}
def news_loop():
    """뉴스 키워드 알람 (별도 스레드, 1분 간격)."""
    nc = cfg.get("news", {})
    if not nc.get("enable"): return
    try: w = news.Watcher(cfg)
    except Exception as e: log(f"[뉴스] 시작 실패(키워드 사전 없음?): {e!r}"); return
    first = True
    while True:
        hhmm = time.strftime("%H%M")
        if nc["from"] <= hhmm <= nc["to"]:
            try:
                hits = w.poll()
                if first: first = False; hits = []            # 시작 직후 이미 올라와 있던 기사는 알람 생략
                rate = lambda c: LAST_Q[c]["rate"] if c in LAST_Q else None
                for sc, it, kws, stocks in hits:
                    msg = news.fmt(sc, it, kws, stocks, rate)
                    SNAP.setdefault("news", []).insert(0, {"time": it["time"], "title": it["title"], "url": it["url"], "press": it["press"],
                        "score": sc, "kws": [k for k, _ in kws], "stocks": [n for n, _ in stocks],
                        "themes": list(dict.fromkeys(t for _, v in kws for t, _ in v["themes"][:2]))[:3]})
                    notify(msg, "news", send=nc["notify"] and w.allow())
                del SNAP.get("news", [])[80:]
            except Exception as e: log(f"[뉴스] 수집 오류: {e!r}")
        time.sleep(nc["interval_sec"])

def maybe_backfill(hhmm):
    """장 마감 후(17:00~07:00) 1시간에 1년치씩 인포스탁 과거자료 수집. 차단되면 6시간 쉼."""
    if not cfg.get("infostock", {}).get("enable") or INFO["busy"]: return
    if not (hhmm >= "1700" or hhmm < "0700") or time.time() < INFO.get("bf_next", 0) or INFO.get("bf_done"): return
    def work():
        INFO["busy"] = True; INFO["bf_next"] = time.time() + 3600
        try:
            left = infostock.backfill_step(log=lambda m: log(m))
            if left == 0: INFO["bf_done"] = True; log("[인포스탁] 과거자료 수집 완료")
            INFO["reasons"] = infostock.reasons(cfg["infostock"]["reason_days"])
        except infostock.Blocked: INFO["bf_next"] = time.time() + 6 * 3600; log("[인포스탁] 서버 차단 → 6시간 후 재시도")
        except Exception as e: log(f"[인포스탁] 과거자료 수집 오류: {e!r}")
        finally: INFO["busy"] = False
    threading.Thread(target=work, daemon=True).start()

def maybe_send_brief(hhmm):
    ic = cfg.get("infostock", {})
    if not ic.get("enable") or hhmm < ic["brief_hhmm"] or INFO["busy"]: return
    flag = os.path.join(LOG_DIR, "brief_sent.txt")
    sent = open(flag, encoding="utf-8").read().strip() if os.path.exists(flag) else ""
    today = time.strftime("%Y%m%d")
    if sent == today: return
    date, text = infostock.brief()
    if not text: return
    open(flag, "w", encoding="utf-8").write(today)
    notify(text, "alerts", send=ic["brief_notify"])

KB = {"themes": {}, "map": {}}
def load_kb(rebuild=False):
    """테마 백과(static/kb) 읽기. rebuild=True면 인포스탁 DB로 다시 생성(월요일 아침, 백그라운드)."""
    try:
        if rebuild: theme_kb.build(); log("[백과] 테마 백과 재생성")
        p = os.path.join(HERE, "static", "kb")
        KB["themes"] = json.load(open(os.path.join(p, "theme_kb.json"), encoding="utf-8"))
        KB["map"] = json.load(open(os.path.join(p, "map.json"), encoding="utf-8"))
    except Exception as e: log(f"[백과] 읽기 실패: {e!r}")

def kb_of(t):
    """테마 → 인포스탁 테마 백과 항목 (◆테마는 그대로, 내 테마는 매핑 1순위)."""
    name = t["theme"]
    key = name[1:] if name.startswith("◆") else next((u for u, _ in KB["map"].get(name, []) if u in KB["themes"]), None)
    return (key, KB["themes"].get(key)) if key else (None, None)

def kb_line(t):
    key, k = kb_of(t)
    if not k: return ""
    lead = ", ".join(x[0] for x in k["leaders"][:3])
    fol = " · ".join(x[0] for x in k["follow"][:2])
    return (f"📚 {key}: 13년 주도 {k['n']}일(최근1년 {k['recent']}) · 평균 {k['streak']}일 지속"
            + (f" · 역대 대장 {lead}" if lead else "") + (f" · 다음날 후속 {fol}" if fol else ""))

def why_of(t):
    """테마 상위 종목 중 최근 인포스탁 사유가 있는 가장 최신 것."""
    best = None
    for m in t.get("stocks", t.get("movers", []))[:6]:
        r = INFO["reasons"].get(m["code"])
        if r and (best is None or r["date"] > best[1]["date"]): best = (m["name"], r)
    if not best: return ""
    n, r = best
    return f"📌 사유({r['date'][4:6]}/{r['date'][6:]} {n}): {r['reason'][:80]}"

def load_rotation():
    p = os.path.join(HERE, "rotation.json")
    return json.load(open(p, encoding="utf-8"))["themes"] if os.path.exists(p) else {}

def phase_of(hhmm):
    p = cfg["premarket"]
    if p["nxt_from"] <= hhmm < p["exp_from"]: return "nxt"
    if p["exp_from"] <= hhmm < "0900": return "exp"
    if "0900" <= hhmm <= "1530": return "live"
    return "closed"

def slim(scores, rot):
    out = [t for t in scores if t["kind"] == "hts" or t["n5"] >= 1 or t["level"]][:160]
    for t in out:
        if t["level"]: t["why"] = why_of(t); t["kb"] = kb_line(t)
        r = rot.get(t["theme"])
        if r and t["level"]: t["rot"] = {"same": r["same"][:3], "next": r["next"][:3], "persist": r["persist"]}
    return out

def watch_codes(scores, sigs, n_each=5):
    """웹소켓 0B로 실시간 볼 종목: 초기 신호 테마 + 점등 테마의 상위 종목."""
    want = []
    for s in sigs[:15]: want += [m["code"] for m in s["movers"][:n_each]]
    for t in scores:
        if t["level"] and t.get("alertable"): want += [m["code"] for m in t["stocks"][:n_each]]
    seen, out = set(), []
    for c in want:
        if c not in seen: seen.add(c); out.append(c)
    return out

# ---------- 수집 루프 ----------
def loop(rt):
    a = cfg["alert"]; day = None; last_phase = None
    master = td = None; alerter = early_al = hist = None; rot = load_rotation(); pre_sent = False
    while True:
        hhmm = time.strftime("%H%M"); today = time.strftime("%Y%m%d"); ph = phase_of(hhmm)
        try:
            if day != today:
                kiwoom._token = None; rt and setattr(rt, "reconnect", True)
                master = kiwoom.stock_master(); td = refresh_themes(); rot = load_rotation()
                alerter, early_al, hist = engine.Alerter(cfg), early.EarlyAlerter(cfg), early.History()
                day, pre_sent = today, False
                SNAP.update(alerts=[], early=[], premarket=[], built=td["built"])
                if not SNAP.get("brief"):
                    try: INFO["reasons"] = infostock.reasons(cfg["infostock"]["reason_days"]); SNAP["brief"] = infostock.snapshot_for_dashboard()
                    except Exception as e: log(f"[인포스탁] 로컬 DB 읽기 실패: {e!r}")
                infostock_refresh()
                threading.Thread(target=load_kb, args=(datetime.date.today().weekday() == 0 or not KB["themes"],), daemon=True).start()
            if ph != last_phase:
                log(f"[구간] {last_phase} → {ph}"); hist.clear(); last_phase = ph
            maybe_send_brief(hhmm); maybe_backfill(hhmm)
            if time.time() - INFO.get("loaded", 0) > 600 and not INFO["busy"]:   # 10분마다 사유·브리핑 다시 읽기
                try: INFO["reasons"] = infostock.reasons(cfg["infostock"]["reason_days"]); SNAP["brief"] = infostock.snapshot_for_dashboard()
                except Exception as e: log(f"[인포스탁] 읽기 실패: {e!r}")
                INFO["loaded"] = time.time()
            # 1) 시세
            if ph == "nxt":   q = kiwoom.risers(min_amt_cnd="0", stex="2")
            elif ph == "exp": q = kiwoom.expected_risers()
            else:             q = kiwoom.risers()
            if rt and ph == "live": rt.overlay(q)
            LAST_Q.clear(); LAST_Q.update(q)
            min_amt = cfg["premarket"]["min_amt"] if ph in ("nxt", "exp") else a["min_amt"]
            scores = engine.theme_scores(td, q, master, min_amt=min_amt)
            for t in scores: t["level"] = engine.level(t, a) if ph == "live" or ph == "closed" else 0; t["alertable"] = engine.alertable(t)
            sigs = []
            # 2) 장중: 초기 감지 + 점등 알람
            if ph == "live":
                hist.add(q)
                mins = (int(hhmm[:2]) - 9) * 60 + int(hhmm[2:])
                vi = list(rt.vi) if rt else []
                if hhmm >= cfg["early"]["start_hhmm"]:
                    sigs = early.detect(td, q, hist, vi, cfg, mins)
                    levels = {t["theme"]: t["level"] for t in scores}
                    for s in early_al.check(sigs, levels):
                        SNAP["early"].insert(0, {"time": time.strftime("%H:%M"), **{k: s[k] for k in ("theme", "why", "inflow", "ratio", "vi")},
                                                 "lead": s["movers"][0]["name"], "rate": s["movers"][0]["rate"]})
                        w = why_of(s); kl = kb_line(s); notify(early.fmt(s) + ("\n  " + w if w else "") + ("\n  " + kl if kl else ""), "early", send=cfg["early"]["notify"])
                    del SNAP["early"][60:]
                if hhmm >= a["start_hhmm"]:
                    fired = alerter.check(scores)
                    for lv, t in fired:
                        SNAP["alerts"].insert(0, {"time": time.strftime("%H:%M"), "theme": t["theme"], "level": lv,
                                                  "chips": t["chips"], "lead": t["stocks"][0]["name"], "rate": t["stocks"][0]["rate"]})
                    del SNAP["alerts"][50:]
                    if fired: notify("\n\n".join(engine.fmt(lv, t) + "".join("\n" + x for x in (why_of(t), kb_line(t)) if x) for lv, t in fired))
                if rt: rt.want = set(watch_codes(scores, sigs)); 
                inth = {c: n for n, t in td["themes"].items() if t["kind"] == "hts" and not t["basket"] for c in t["codes"]}
                SNAP["vi"] = [dict(v, theme=inth.get(v["code"], "")) for v in reversed(vi) if v["up"]][:40]
            # 3) 장전 요약
            if ph in ("nxt", "exp"):
                pre = [t for t in scores if t["alertable"] and t["n5"] >= 2][:8]
                SNAP["premarket"] = [{"theme": t["theme"], "n5": t["n5"], "avg5": t["avg5"],
                                      "lead": ", ".join(m["name"] for m in t["stocks"][:3])} for t in pre]
                if hhmm >= cfg["premarket"]["summary_hhmm"] and not pre_sent and pre:
                    pre_sent = True
                    notify("🌅 장전 강세 테마 (예상체결 기준)\n" + "\n".join(
                        f"{i+1}. {p['theme']}  +5%↑ {p['n5']}종목 · 평균 +{p['avg5']}%\n   {p['lead']}" for i, p in enumerate(SNAP["premarket"][:5])),
                        "alerts", send=cfg["premarket"]["notify"])
            label = {"nxt": "프리마켓(NXT)", "exp": "동시호가 예상체결", "live": "장중", "closed": "장외 · 종가 기준"}[ph]
            SNAP.update(time=time.strftime("%H:%M:%S"), status=label, phase=ph, themes=slim(scores, rot), n_risers=len(q),
                        n_lit=sum(1 for t in scores if t["level"] and t["alertable"]),
                        early_now=[{k: s[k] for k in ("theme", "why", "n_rise", "inflow", "ratio", "vi", "movers", "win_min")} for s in sigs[:12]],
                        ws=(rt.status + f" · 실시간 {len(rt.reg)}종목") if rt else "꺼짐")
        except Exception:
            log(traceback.format_exc()); kiwoom._token = None; SNAP["status"] = "오류 · 재시도 중"
        time.sleep(cfg.get("poll_sec", 3) if ph in ("live", "nxt", "exp") else 60)

# ---------- 대시보드 ----------
class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **k): super().__init__(*a, directory=os.path.join(HERE, "static"), **k)
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path.startswith("/data"):
            body = json.dumps(SNAP, ensure_ascii=False).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
        else: super().do_GET()

if __name__ == "__main__":
    try: sys.stdout.reconfigure(encoding="utf-8"); sys.stderr.reconfigure(encoding="utf-8")
    except Exception: pass
    rt = None
    if cfg["ws"]["enable"]:
        try:
            import websockets  # noqa
            import ws as ws_mod; rt = ws_mod.Realtime(cfg, log); rt.start()
        except ImportError: log("[WS] websockets 미설치 → pip install websockets (실시간 기능 꺼짐)")
    threading.Thread(target=loop, args=(rt,), daemon=True).start()
    threading.Thread(target=news_loop, daemon=True).start()
    port = cfg.get("port", 8000)
    log(f"대시보드: http://localhost:{port}   (종료: 창 닫기)")
    if cfg["telegram"].get("bot_token"): tg_ready()
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
