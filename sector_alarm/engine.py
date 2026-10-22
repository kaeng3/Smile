"""테마 강도 계산 + 알람 판정. 입력/출력 모두 dict — 키움 없이 테스트 가능.
판정은 '거래대금 min_amt억 이상' 종목만 센다(잡주 급등으로 테마가 켜지는 것 방지)."""
import time, collections as C

def theme_scores(td, quotes, master, min_amt=20, top_n=10):
    """td = themes.json 전체, quotes = kiwoom.risers(). 반환: 점수순 테마 리스트."""
    kw_of, res = td["kw_of"], []
    for name, t in td["themes"].items():
        ms = [dict(code=c, **quotes[c]) for c in t["codes"] if c in quotes]
        if not ms: continue
        ms.sort(key=lambda m: m["amt"], reverse=True)
        top = ms[:top_n]
        for m in top:
            m["cap"] = round(m["price"] * master.get(m["code"], ("", 0))[1] / 1e8)
            m["kw"] = kw_of.get(m["code"], [])[:4]
            m["added"] = m["code"] in t["added"]
        big = [m for m in top if m["amt"] >= min_amt]
        movers = [m for m in big if m["rate"] >= 5]
        hot = sorted(top, key=lambda m: m["rate"], reverse=True)[:5]
        chips = C.Counter(k for m in movers for k in m["kw"]) if t["kind"] == "hts" else C.Counter()
        res.append({
            "theme": name, "kind": t["kind"], "basket": t["basket"], "independent": t["independent"],
            "parent": t["parent"], "n_total": len(t["codes"]), "n_up": len(ms),
            "n5": len(movers), "n_upper": sum(m["upper"] for m in big),
            "leader": max([m["rate"] for m in big] or [0]),
            "avg5": round(sum(m["rate"] for m in hot) / len(hot), 2),
            "amt": round(sum(m["amt"] for m in top)),
            "chips": [k for k, n in chips.most_common(3) if n >= 2],
            "stocks": sorted(top, key=lambda m: (m["upper"], m["rate"]), reverse=True)})
    for t in res:
        t["score"] = round(t["n_upper"] * 3 + t["n5"] * 1.5 + t["leader"] / 10 + min(t["amt"], 5000) / 2500, 2)
    return sorted(res, key=lambda t: t["score"], reverse=True)

def level(t, a):
    """0~3단계. 최소 2종목 이상이 함께 움직여야 테마로 인정."""
    if t["amt"] < a["theme_min_amt"] or t["n5"] < 2: return 0
    if t["n5"] >= 5 or (t["n_upper"] >= 2 and t["n5"] >= 3): return 3
    if t["n5"] >= 3 and (t["n_upper"] >= 1 or t["leader"] >= a["leader_rate"]): return 2
    if t["leader"] >= 10: return 1
    return 0

def alertable(t):
    """알람 대상: 바스켓 아닌 HTS 그룹 + HTS로 못 잡는 독립 키워드."""
    return not t["basket"] and (t["kind"] == "hts" or t["independent"])

class Alerter:
    """단계가 오를 때만 알림. 0단계로 식은 뒤 cooldown이 지나면 다시 알림 가능(재점화)."""
    def __init__(self, cfg): self.a, self.state = cfg["alert"], {}
    def check(self, scores, now=None):
        now, out = now or time.time(), []
        for t in scores:
            if not alertable(t): continue
            lv = t.get("level", level(t, self.a))
            prev_lv, prev_t = self.state.get(t["theme"], (0, 0))
            if lv > prev_lv:
                out.append((lv, t)); self.state[t["theme"]] = (lv, now)
            elif lv == 0 and prev_lv and now - prev_t > self.a["cooldown_min"] * 60:
                self.state[t["theme"]] = (0, now)
        return out

def fmt(lv, t):
    head = f"{'🔴' * lv} {t['theme']} [{lv}단계]"
    if t["chips"]: head += "  주도: " + " · ".join("#" + c for c in t["chips"])
    sub = f"+5%↑ {t['n5']}종목 · 상한가 {t['n_upper']} · 상위 평균 +{t['avg5']}% · {t['amt']:,}억"
    lines = [f"  {m['name']} +{m['rate']:.1f}%{'(상)' if m['upper'] else ''} {m['amt']:.0f}억" for m in t["stocks"][:4]]
    return "\n".join([head, sub] + lines)
