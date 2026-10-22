"""1회 스캔: 지금 시점 테마 순위 출력 (장 마감 후엔 종가 기준). 결과는 scan_result.json"""
import json, os, time, kiwoom, engine
HERE = os.path.dirname(os.path.abspath(__file__))
td = json.load(open(os.path.join(HERE, "themes.json"), encoding="utf-8"))
cfg = json.load(open(os.path.join(HERE, "config.json"), encoding="utf-8"))
t0 = time.time(); master = kiwoom.stock_master(); q = kiwoom.risers()
json.dump(q, open(os.path.join(HERE, "risers_last.json"), "w", encoding="utf-8"), ensure_ascii=False)
print(f"상승종목 {len(q)}개 ({time.time()-t0:.1f}s)\n")
scores = engine.theme_scores(td, q, master, min_amt=cfg["alert"]["min_amt"])
for t in scores:
    t["level"] = engine.level(t, cfg["alert"])
    if t["level"] and engine.alertable(t): print(engine.fmt(t["level"], t), "\n")
json.dump(scores, open(os.path.join(HERE, "scan_result.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
