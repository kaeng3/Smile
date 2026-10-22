"""키움 REST 최소 클라이언트 (표준 라이브러리만 사용). 키는 *_appkey.txt / *_secretkey.txt 에서 읽음."""
import json, glob, time, urllib.request, os

BASE = "https://api.kiwoom.com"
HERE = os.path.dirname(os.path.abspath(__file__))

def _read(pattern):
    return open(glob.glob(os.path.join(HERE, pattern))[0], encoding="utf-8").read().strip()

_token = None
def token():
    global _token
    if _token is None:
        body = {"grant_type": "client_credentials", "appkey": _read("*_appkey.txt"), "secretkey": _read("*_secretkey.txt")}
        r = _http("/oauth2/token", body, {})
        if not r.get("token"):
            raise RuntimeError(f"토큰 발급 실패: {r.get('return_code')} {r.get('return_msg')}")
        _token = r["token"]
    return _token

def _http(path, body, headers):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json;charset=UTF-8", **headers})
    with urllib.request.urlopen(req, timeout=10) as res:
        data = json.loads(res.read().decode("utf-8"))
        data["_cont"] = (res.headers.get("cont-yn"), res.headers.get("next-key"))
        return data

def call(api_id, path, body=None):
    """연속조회(cont-yn=Y)까지 모두 받아 응답 리스트 반환. 호출 간 0.2초 간격."""
    out, cont, nxt = [], "N", ""
    while True:
        h = {"api-id": api_id, "authorization": f"Bearer {token()}", "cont-yn": cont, "next-key": nxt}
        r = _http(path, body or {}, h); out.append(r); time.sleep(0.2)
        cont, nxt = r["_cont"]
        if cont != "Y": return out

def watch_groups():
    """{그룹명: [종목코드,...]} — 0130 관심종목 폴더 그대로."""
    groups = {}
    for r in call("ka01300", "/api/dostk/watchlist"):
        for g in r.get("nofi") or []:
            codes = []
            for rr in call("ka01301", "/api/dostk/watchlist", {"arn_grp_id": g["gcod"]}):
                codes += [x["cod2"] for x in rr.get("nofj") or []]
            groups[g["name"]] = codes
    return groups

if __name__ == "__main__":
    g = watch_groups()
    for name, codes in g.items():
        print(f"{name:20s} {len(codes):4d}종목  예: {codes[:3]}")
    uniq = {c for cs in g.values() for c in cs}
    print(f"\n그룹 {len(g)}개 / 전체 {sum(map(len, g.values()))}종목 / 중복제거 {len(uniq)}종목")
    json.dump(g, open(os.path.join(HERE, "groups_snapshot.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# ---- 시세 (폴링 방식: WS 구독 한도 200종목이라 전종목은 랭킹 TR로) ----
def _num(s):
    s = (s or "0").replace("+", "").replace(",", "")
    try: return float(s)
    except ValueError: return 0.0

def stock_master():
    """{코드: (종목명, 상장주식수)} — 하루 1회, stock_master.json 캐시."""
    import datetime
    path = os.path.join(HERE, "stock_master.json")
    today = datetime.date.today().isoformat()
    if os.path.exists(path):
        m = json.load(open(path, encoding="utf-8"))
        if m.get("_date") == today: return m["data"]
    data = {}
    for mk in ("0", "10"):
        for r in call("ka10099", "/api/dostk/stkinfo", {"mrkt_tp": mk}):
            for x in r.get("list") or []:
                data[x["code"]] = (x["name"], int(_num(x.get("listCount"))))
    json.dump({"_date": today, "data": data}, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return data

def _rank_pages(api_id, path, body, list_key, row_fn):
    """랭킹 TR 공통 페이저: row_fn(row)가 None을 돌려주면(0% 이하 등) 중단."""
    out, cont, nxt = {}, "N", ""
    while True:
        h = {"api-id": api_id, "authorization": f"Bearer {token()}", "cont-yn": cont, "next-key": nxt}
        r = _http(path, body, h); time.sleep(0.2)
        rows = r.get(list_key) or []
        for x in rows:
            v = row_fn(x)
            if v is None: return out
            out[x["stk_cd"].split("_")[0]] = v
        cont, nxt = r["_cont"]
        if cont != "Y" or not rows: return out

def risers(min_amt_cnd="10", stex="3"):
    """상승 종목 전체 {코드: {name, rate, price, amt(억), upper}}. ka10027 상승률순.
    stex: 1=KRX 2=NXT(프리마켓 08:00~08:50) 3=통합. min_amt_cnd 10=거래대금 1억 이상."""
    body = {"mrkt_tp": "000", "sort_tp": "1", "trde_qty_cnd": "0000", "stk_cnd": "16", "crd_cnd": "0",
            "updown_incls": "1", "pric_cnd": "0", "trde_prica_cnd": min_amt_cnd, "stex_tp": stex}
    def row(x):
        rate = _num(x["flu_rt"])
        if rate <= 0: return None
        price = abs(_num(x["cur_prc"]))
        return {"name": x["stk_nm"], "rate": rate, "price": price,
                "amt": price * _num(x["now_trde_qty"]) / 1e8, "upper": x.get("pred_pre_sig") == "1"}
    return _rank_pages("ka10027", "/api/dostk/rkinfo", body, "pred_pre_flu_rt_upper", row)

def expected_risers():
    """동시호가 예상체결 상승 종목 (08:30~09:00). amt = 예상체결가 × 예상체결량."""
    body = {"mrkt_tp": "000", "sort_tp": "1", "trde_qty_cnd": "1", "stk_cnd": "16", "crd_cnd": "0",
            "pric_cnd": "0", "stex_tp": "1"}
    def row(x):
        rate = _num(x["flu_rt"])
        if rate <= 0: return None
        price = abs(_num(x["exp_cntr_pric"]))
        return {"name": x["stk_nm"], "rate": rate, "price": price,
                "amt": price * _num(x["exp_cntr_qty"]) / 1e8, "upper": x.get("pred_pre_sig") == "1"}
    return _rank_pages("ka10029", "/api/dostk/rkinfo", body, "exp_cntr_flu_rt_upper", row)
