"""초기 점등 감지 — '이미 오른 상태'가 아니라 '막 움직이기 시작한 변화'를 본다.
  ① 가속도: window_sec(3분) 동안 +min_rise%p 이상 오른 종목이 min_stocks개 이상
  ② 돈의 유입: 같은 3분간 거래대금 증가분이 그 테마 오늘 분당 평균의 inflow_x배 이상
  ③ 확산: 대장주 1종목이 급가속(+5%p) + 동종 2종목 이상 따라붙음(+1.5%p & 거래대금 유입)
  ④ VI: vi_window_sec(5분) 안에 같은 테마 상승 VI vi_min건 이상
판정: (①and②) or ③ or (④ and 상승 2종목+)"""
import time, collections as C

class History:
    """3초마다의 {코드: (등락률, 거래대금억)} 스냅샷을 최근 6분만 보관."""
    def __init__(self, keep_sec=360): self.keep, self.snaps = keep_sec, C.deque()
    def add(self, quotes, now=None):
        now = now or time.time()
        self.snaps.append((now, {c: (q["rate"], q["amt"]) for c, q in quotes.items()}))
        while self.snaps and now - self.snaps[0][0] > self.keep: self.snaps.popleft()
    def ago(self, sec, now=None):
        """sec초 전에 가장 가까운(그보다 오래된) 스냅샷. 데이터가 부족하면 None."""
        now = now or time.time(); best = None
        for ts, s in self.snaps:
            if now - ts >= sec: best = (ts, s)
            else: break
        if best is None and self.snaps and now - self.snaps[0][0] >= sec * 0.6: best = self.snaps[0]
        return best
    def clear(self): self.snaps.clear()

def detect(td, quotes, hist, vi_events, cfg, minutes_open, now=None):
    e = cfg["early"]; now = now or time.time()
    old = hist.ago(e["window_sec"], now)
    if not old: return []
    win_min = max((now - old[0]) / 60, 0.5); prev = old[1]
    recent_vi = C.Counter(v["code"] for v in vi_events if now - v["ts"] <= e["vi_window_sec"] and v["up"])
    out = []
    for name, t in td["themes"].items():
        if t["basket"]: continue
        rows, inflow, amt_all, vi = [], 0.0, 0.0, 0
        for c in t["codes"]:
            q = quotes.get(c)
            vi += recent_vi.get(c, 0)
            if not q: continue
            amt_all += q["amt"]
            r0, a0 = prev.get(c, (0.0, None))
            dr = q["rate"] - r0; da = max(q["amt"] - a0, 0) if a0 is not None else 0.0
            inflow += da
            rows.append({"code": c, "name": q["name"], "rate": q["rate"], "d_rate": round(dr, 2),
                         "d_amt": round(da, 1), "amt": q["amt"]})
        if not rows: continue
        risers = [r for r in rows if r["d_rate"] >= e["min_rise"] and r["amt"] >= e["min_amt"]]
        base = amt_all / max(minutes_open, 5)                    # 오늘 분당 평균 거래대금
        ratio = (inflow / win_min) / base if base > 0 else 0
        lead = [r for r in rows if r["d_rate"] >= e["spread_leader_rise"] and r["amt"] >= e["min_amt"]]
        follow = [r for r in rows if r not in lead[:1] and r["d_rate"] >= e["spread_follow_rise"] and r["d_amt"] > 0]
        why = []
        if len(risers) >= e["min_stocks"] and ratio >= e["inflow_x"] and inflow >= e["min_inflow"]:
            why.append(f"{len(risers)}종목 동반 가속")
        if lead and len(follow) >= e["spread_followers"]:
            why.append(f"{lead[0]['name']} 급가속 → {len(follow)}종목 확산")
        if vi >= e["vi_min"] and len(risers) >= 2:
            why.append(f"VI {vi}건")
        if not why: continue
        movers = sorted(rows, key=lambda r: r["d_rate"], reverse=True)[:5]
        out.append({"theme": name, "kind": t["kind"], "independent": t["independent"],
                    "alertable": t["kind"] == "hts" or t["independent"],
                    "why": why, "n_rise": len(risers), "inflow": round(inflow), "ratio": round(ratio, 1),
                    "vi": vi, "win_min": round(win_min, 1), "movers": movers,
                    "score": round(len(risers) + min(ratio, 20) / 2 + vi * 2 + (3 if lead else 0), 1)})
    return sorted(out, key=lambda x: x["score"], reverse=True)

class EarlyAlerter:
    def __init__(self, cfg): self.cd, self.last = cfg["early"]["cooldown_min"] * 60, {}
    def check(self, sigs, levels, now=None):
        """이미 2단계 이상 점등된 테마는 '초기'가 아니므로 제외. 테마당 cooldown 1회."""
        now = now or time.time(); out = []
        for s in sigs:
            if not s["alertable"] or levels.get(s["theme"], 0) >= 2: continue
            if now - self.last.get(s["theme"], 0) < self.cd: continue
            self.last[s["theme"]] = now; out.append(s)
        return out

def fmt(s):
    mv = " / ".join(f"{m['name']} +{m['rate']:.1f}%(↑{m['d_rate']:.1f})" for m in s["movers"][:3])
    return (f"⚡ 초기 · {s['theme']}  " + " · ".join(s["why"]) +
            f"\n  {s['win_min']}분간 유입 {s['inflow']:,}억 (평소 {s['ratio']}배)\n  {mv}")
