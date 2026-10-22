"""장전 기능에 쓰는 TR이 실제로 응답하는지 점검 → logs/check_api.txt"""
import os, time, traceback, kiwoom
out = []
for name, fn in [("NXT 등락률(ka10027 stex=2)", lambda: kiwoom.risers(min_amt_cnd="0", stex="2")),
                 ("예상체결(ka10029)", kiwoom.expected_risers),
                 ("통합 등락률(ka10027)", kiwoom.risers)]:
    try:
        t = time.time(); r = fn(); ex = list(r.items())[:2]
        out.append(f"OK  {name}: {len(r)}종목 {time.time()-t:.1f}s 예:{ex}")
    except Exception: out.append(f"ERR {name}: {traceback.format_exc()[-400:]}")
open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "check_api.txt"), "w", encoding="utf-8").write("\n".join(out))
