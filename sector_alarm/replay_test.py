"""가상 장중 리플레이 테스트 (키움 접속 없음).
  종가 상승종목(risers_sample.json)을 바탕으로 '조용하던 테마 하나가 3분 사이 갑자기 움직이는' 상황을 만들어
  초기 감지(early) → 점등 단계 상승(engine) → 알람 문구까지 한 번에 확인한다.  python replay_test.py"""
import json, os, copy, collections as C
import engine, early
HERE = os.path.dirname(os.path.abspath(__file__))
cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
td = json.load(open(os.path.join(HERE, "themes.json"), encoding="utf-8"))
master = json.load(open(os.path.join(HERE, "stock_master.json"), encoding="utf-8"))["data"]
base = json.load(open(os.path.join(HERE, "risers_sample.json"), encoding="utf-8"))
TARGET = "조선/해운"
codes = [c for c in td["themes"][TARGET]["codes"] if c in master][:8]
def frame(step):
    """step 0~10: 대상 테마 종목들이 점점 오르고 거래대금이 몰림. 나머지는 그대로."""
    q = copy.deepcopy({c: v for c, v in base.items() if c not in codes})
    for i, c in enumerate(codes):
        r = min(0.5 + step * (1.2 + i * 0.25), 29.9)
        q[c] = {"name": master[c][0], "rate": round(r, 2), "price": 10000, "amt": 15 + step * step * (6 + i), "upper": r >= 29.9}
    return q
hist, al, eal = early.History(), engine.Alerter(cfg), early.EarlyAlerter(cfg)
t0 = 1_000_000.0; first_early = first_lv = None
vi = [{"ts": t0 + 380, "code": codes[0], "up": True}, {"ts": t0 + 390, "code": codes[1], "up": True}]
for step in range(0, 11):
    now = t0 + step * 60; q = frame(step); hist.add(q, now)
    sc = engine.theme_scores(td, q, master, min_amt=cfg["alert"]["min_amt"])
    for t in sc: t["level"] = engine.level(t, cfg["alert"])
    lv = {t["theme"]: t["level"] for t in sc}
    sigs = early.detect(td, q, hist, [v for v in vi if v["ts"] <= now], cfg, minutes_open=30 + step, now=now)
    for s in eal.check(sigs, lv, now):
        if s["theme"] == TARGET and first_early is None: first_early = step
        if s["theme"] == TARGET: print(f"[{step}분] " + early.fmt(s))
    for l, t in al.check(sc, now):
        if t["theme"] == TARGET:
            first_lv = first_lv if first_lv is not None else step
            print(f"[{step}분] " + engine.fmt(l, t).split("\n")[0])
    others = [s["theme"] for s in sigs if s["theme"] != TARGET and s["alertable"]]
    if others: print(f"[{step}분] (다른 테마 초기 신호: {others[:5]})")
print(f"\n결과: 초기 신호 {first_early}분, 1단계 이상 점등 {first_lv}분 → {'초기가 더 빠름 ✅' if first_early is not None and (first_lv is None or first_early < first_lv) else '확인 필요'}")
