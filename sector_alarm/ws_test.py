"""웹소켓 0B 구독 한도 테스트: 테마 종목 전체를 100개씩 grp_no 나눠 등록하고 응답코드 확인.
필요: pip install websockets"""
import asyncio, json, os, websockets, kiwoom
HERE = os.path.dirname(os.path.abspath(__file__))
URL = "wss://api.kiwoom.com:10000/api/websocket"

async def main():
    codes = sorted({c for v in json.load(open(os.path.join(HERE, "themes.json"), encoding="utf-8")).values() for c in v})
    async with websockets.connect(URL, ping_interval=None) as ws:
        await ws.send(json.dumps({"trnm": "LOGIN", "token": kiwoom.token()}))
        print("LOGIN:", await ws.recv())
        ok = 0
        for i in range(0, len(codes), 100):
            chunk, grp = codes[i:i+100], str(i // 100 + 1)
            await ws.send(json.dumps({"trnm": "REG", "grp_no": grp, "refresh": "1",
                                      "data": [{"item": chunk, "type": ["0B"]}]}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("trnm") == "PING": await ws.send(json.dumps(r)); continue
                if r.get("trnm") == "REG": break
            print(f"grp {grp:>2} ({len(chunk)}종목): code={r.get('return_code')} {r.get('return_msg')}")
            if r.get("return_code") != 0: break
            ok += len(chunk)
        print(f"\n등록 성공 {ok}/{len(codes)}종목")
        # 장중이면 10초간 수신 건수 확인
        n, loop = 0, asyncio.get_event_loop()
        end = loop.time() + 10
        while (left := end - loop.time()) > 0:
            try: r = json.loads(await asyncio.wait_for(ws.recv(), left))
            except asyncio.TimeoutError: break
            if r.get("trnm") == "PING": await ws.send(json.dumps(r))
            elif r.get("trnm") == "REAL": n += len(r.get("data", []))
        print(f"10초간 실시간 체결 수신 {n}건 (장 마감 중이면 0이 정상)")

asyncio.run(main())
