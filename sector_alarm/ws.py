"""키움 웹소켓 실시간 (별도 스레드).
  - 1h VI발동: item [""] 로 전 종목 수신 (구독 한도 200과 무관)
  - 0B 체결: 초기/점등 테마 대장주만 동적 구독(max_live) → 3초 폴링 사이를 초 단위로 메움
끊기면 5초 후 자동 재접속. 필요: pip install websockets"""
import asyncio, json, threading, time, collections as C
import kiwoom

URL = "wss://api.kiwoom.com:10000/api/websocket"

def _num(s):
    try: return float(str(s or "0").replace("+", "").replace(",", ""))
    except ValueError: return 0.0

class Realtime(threading.Thread):
    def __init__(self, cfg, log):
        super().__init__(daemon=True)
        self.max_live, self.log = cfg["ws"]["max_live"], log
        self.vi = C.deque(maxlen=800)      # VI 발동 이벤트
        self.live = {}                     # {코드: {rate, price, upper, ts}}
        self.want, self.reg = set(), set() # 구독 원하는/등록된 0B 종목
        self.status, self.reconnect, self._seen = "대기", False, set()

    def run(self):
        asyncio.run(self._main())

    async def _main(self):
        import websockets
        while True:
            try:
                async with websockets.connect(URL, ping_interval=None, max_size=2**22) as ws:
                    await ws.send(json.dumps({"trnm": "LOGIN", "token": kiwoom.token()}))
                    r = json.loads(await ws.recv())
                    if r.get("return_code") != 0: raise RuntimeError(f"LOGIN 실패 {r}")
                    await ws.send(json.dumps({"trnm": "REG", "grp_no": "1", "refresh": "1",
                                              "data": [{"item": [""], "type": ["1h"]}]}))
                    self.reg, self.status, self.reconnect = set(), "연결됨", False
                    self.log("[WS] 접속·VI 구독 요청")
                    while not self.reconnect:
                        try: raw = await asyncio.wait_for(ws.recv(), 1.0)
                        except asyncio.TimeoutError: raw = None
                        if raw: await self._handle(ws, json.loads(raw))
                        await self._sync(ws)
            except Exception as e:
                self.status = "재접속 중"; self.log(f"[WS] 끊김: {e!r} → 5초 후 재접속")
                await asyncio.sleep(5)

    async def _sync(self, ws):
        want = set(list(self.want)[: self.max_live])
        if want == self.reg or not want: return
        await ws.send(json.dumps({"trnm": "REG", "grp_no": "2", "refresh": "0",
                                  "data": [{"item": sorted(want), "type": ["0B"]}]}))
        self.reg = want

    async def _handle(self, ws, r):
        tr = r.get("trnm")
        if tr == "PING": await ws.send(json.dumps(r)); return
        if tr == "REG":
            if r.get("return_code") != 0: self.log(f"[WS] REG 오류 {r.get('return_msg')}")
            return
        if tr != "REAL": return
        now = time.time()
        for d in r.get("data", []):
            v = d.get("values", {})
            if d.get("type") == "1h":
                code = str(v.get("9001") or d.get("item", "")).lstrip("A")[:6]
                key = (code, v.get("1490"), v.get("1223"))
                if key in self._seen: continue          # 같은 발동의 해제 메시지 중복 제거
                self._seen.add(key)
                self.vi.append({"ts": now, "code": code, "name": v.get("302", ""), "rate": _num(v.get("1489")),
                                "up": v.get("9069", "1") == "1", "kind": v.get("1225", ""),
                                "time": (v.get("1223") or "")[:4], "count": v.get("1490", "")})
            elif d.get("type") == "0B":
                code = str(d.get("item", "")).split("_")[0]
                self.live[code] = {"rate": _num(v.get("12")), "price": abs(_num(v.get("10"))),
                                   "upper": v.get("25") == "1", "ts": now}

    def overlay(self, quotes, max_age=10):
        """폴링 결과에 실시간 체결의 최신 등락률/현재가를 덮어씀 (거래대금은 폴링 값 유지)."""
        now = time.time()
        for c, l in list(self.live.items()):
            if c in quotes and now - l["ts"] <= max_age:
                quotes[c].update(rate=l["rate"], price=l["price"], upper=l["upper"])
        return quotes
