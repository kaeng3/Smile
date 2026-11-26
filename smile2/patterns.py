"""Independent KRX regular-session candle research. No default trading thresholds."""
from dataclasses import dataclass
from datetime import date
from math import isfinite
from statistics import mean
import argparse
import json
from pathlib import Path
import re

@dataclass(frozen=True)
class Rules:
    body_pct: float
    volume_ratio_min: float
    reduced_volume_max: float
    upper_wick_body_min: float
    box_days: int
    box_width_max_pct: float
    box_touch_tolerance_pct: float
    box_min_touches: int
    near_breakout_pct: float
    ma5_distance_pct: float

    def __post_init__(self):
        if not all(isfinite(v) for v in vars(self).values()):
            raise ValueError("Non-finite rule")
        if (self.body_pct<=0 or self.volume_ratio_min<=0 or not 0<self.reduced_volume_max<1
            or self.upper_wick_body_min<=0 or type(self.box_days) is not int or self.box_days<5
            or self.box_width_max_pct<=0 or self.box_touch_tolerance_pct<0
            or type(self.box_min_touches) is not int or not 2<=self.box_min_touches<=self.box_days
            or self.near_breakout_pct<0 or self.ma5_distance_pct<0):
            raise ValueError("Invalid rules")

def bars(records):
    if not isinstance(records,list):
        raise ValueError("Expected records list")
    out=[]
    for r in records:
        d=date.fromisoformat(r["day"]).isoformat()
        x={k:float(r[k]) for k in ("open","high","low","close","volume","value")}
        if not all(isfinite(v) for v in x.values()):
            raise ValueError("Non-finite bar")
        if not 0<x["low"]<=min(x["open"],x["close"])<=max(x["open"],x["close"])<=x["high"] or min(x["volume"],x["value"])<0:
            raise ValueError("Invalid OHLCV/value")
        out.append({"day":d,**x})
    out.sort(key=lambda r:r["day"])
    if len({r["day"] for r in out})!=len(out):
        raise ValueError("Duplicate trading date")
    return out

def metrics(b,i):
    x=b[i]; prev=b[i-1] if i else None
    body=x["close"]-x["open"]
    ma=mean([r["close"] for r in b[i-4:i+1]]) if i>=4 else None
    return {"day":x["day"],"candle":"bull" if body>0 else "bear" if body<0 else "doji",
            "body_pct":100*body/x["open"],"upper_wick_to_body":(x["high"]-max(x["open"],x["close"]))/abs(body) if body else None,
            "volume_ratio_prev":x["volume"]/prev["volume"] if prev and prev["volume"] else None,
            "actual_value_won":x["value"],"close":x["close"],"low":x["low"],"ma5":ma,
            "low_to_ma5_pct":100*(x["low"]/ma-1) if ma else None}

def box_before(b,i,r):
    if i<r.box_days:
        return None
    window=b[i-r.box_days:i]
    upper=max(max(a["open"],a["close"]) for a in window)
    lower=min(min(a["open"],a["close"]) for a in window)
    width=100*(upper/lower-1)
    touches=sum(100*(upper-max(a["open"],a["close"]))/upper<=r.box_touch_tolerance_pct for a in window)
    if width>r.box_width_max_pct or touches<r.box_min_touches:
        return None
    return {"start":window[0]["day"],"end":window[-1]["day"],"upper":upper,"lower":lower,"width_pct":width,"touches":touches,
            "method":"horizontal_body_range_candidate"}

def first_flower(b,i,r):
    m=metrics(b,i)
    if m["body_pct"]<r.body_pct or m["volume_ratio_prev"] is None or m["volume_ratio_prev"]<r.volume_ratio_min:
        return None
    box=box_before(b,i,r)
    if box is None:
        return None
    upper=box["upper"]
    distance=100*(m["close"]/upper-1)
    if distance < -r.near_breakout_pct:
        return None
    return {"first_day":m["day"],"first":m,"box":box,"distance_pct":distance,
            "breakout":"close_above" if distance>0 else "touching" if distance==0 else "near"}

def strong(b,i,r):
    m=metrics(b,i)
    return m["body_pct"]>=r.body_pct and m["volume_ratio_prev"] is not None and m["volume_ratio_prev"]>=r.volume_ratio_min

def scan(records,r,extensions=None):
    b=bars(records)
    if len(b)<2:
        return []
    i=len(b)-1
    m=metrics(b,i)
    results=[]
    # Completed candidates are not emitted again as first flowers.
    previous=first_flower(b,i-1,r)
    if previous and m["candle"]=="bull":
        results.append({"strategy":"이일홍","state":"완성 후보","today":m,**previous})
    else:
        first=first_flower(b,i,r)
        if first:
            results.append({"strategy":"이일홍","state":"첫 꽃 후보","today":m,**first})
    if m["candle"]=="bear" and m["volume_ratio_prev"] is not None and m["volume_ratio_prev"]<=r.reduced_volume_max:
        for offset in (1,2):
            j=i-offset
            if j<1 or not strong(b,j,r):
                continue
            if offset==2:
                mid=metrics(b,j+1)
                if mid["candle"]!="bull" or mid["upper_wick_to_body"]<r.upper_wick_body_min:
                    continue
            box=box_before(b,j,r)
            first_close=b[j]["close"]
            supports={"first_close_held":m["close"]>=first_close,
                      "first_close_touched":m["low"]<=first_close<=m["close"],
                      "box_upper_held":m["close"]>=box["upper"] if box else None,
                      "ma5_near":abs(m["low_to_ma5_pct"])<=r.ma5_distance_pct if m["ma5"] else None}
            results.append({"strategy":"양봉-윗꼬리양봉-거감음봉" if offset==2 else "양봉-거감음봉",
                            "state":"지지 확인 후보" if supports["first_close_held"] else "지지 이탈 주의",
                            "first_day":b[j]["day"],"first":metrics(b,j),"box":box,"today":m,"supports":supports})
    # Track consecutive bearish correction immediately after a confirmed breakout.
    end=i-1 if m["candle"]=="bull" else i
    j=end
    while j>=0 and b[j]["close"]<b[j]["open"]:
        j-=1
    if j>=1 and end>j:
        first=first_flower(b,j,r)
        if first and first["breakout"]=="close_above":
            top=max(b[k]["open"] for k in range(j+1,end+1))
            held=m["close"]>=first["box"]["upper"]
            state=("지지 이탈 주의" if not held else "회복 확인" if m["candle"]=="bull" and m["close"]>=top
                   else "회복 진행" if m["candle"]=="bull" else "회복 대기")
            results.append({"strategy":"박스 돌파 후 조정·회복","pattern":"양"+"음"*(end-j)+("양" if m["candle"]=="bull" else ""),
                            "state":state,"correction_body_top":top,"today":m,**first})
    if extensions is not None:
        from .extended_patterns import scan_extended,trend_box,older_resistance
        extended=scan_extended(b,r,extensions)
        # Rising-channel hypothesis supersedes the horizontal label for its anchor.
        rising=[x for x in extended if x["strategy"]=="이일홍 상승형"]
        if rising:
            results=[x for x in results if x["strategy"]!="이일홍"]
        for x in results:
            if x["strategy"]=="이일홍":
                j=next(k for k,a in enumerate(b) if a["day"]==x["first_day"])
                x["older_resistance"]=older_resistance(b,j,r.box_days,extensions.older_days)
        results.extend(extended)
    return results

def load_and_scan(path,r,expected_day,verify_calendar=False,extensions=None):
    d=json.loads(path.read_text(encoding="utf-8"))
    if d.get("source")!="DAUM_KRX_REGULAR" or d.get("schema")!=1:
        raise ValueError("Expected schema 1 DAUM_KRX_REGULAR")
    code=path.stem
    if not re.fullmatch(r"[0-9A-Z]{6}",code):
        raise ValueError("Invalid filename stock code")
    b=bars(d["records"])
    if not b or b[-1]["day"]!=expected_day:
        raise ValueError("Stale or unexpected last session")
    if verify_calendar:
        from .session_check import require_sessions
        require_sessions(b)
    return {"code":code,"as_of":expected_day,"patterns":scan(b,r,extensions),"bars":b[-40:]}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--rules",type=Path,required=True)
    p.add_argument("--as-of",type=lambda s:date.fromisoformat(s).isoformat(),required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--verify-calendar",action="store_true")
    p.add_argument("--extensions",type=Path,help="Explicit optional research hypotheses JSON")
    a=p.parse_args()
    r=Rules(**json.loads(a.rules.read_text(encoding="utf-8")))
    extensions=None
    if a.extensions:
        from .extended_patterns import Extensions
        extensions=Extensions(**json.loads(a.extensions.read_text(encoding="utf-8")))
    if a.verify_calendar:
        from .calendar import session_window
        session_window(date.fromisoformat(a.as_of))
    results,errors=[],[]
    for path in sorted(a.input_dir.glob("*.json")):
        if not re.fullmatch(r"[0-9A-Z]{6}",path.stem):
            continue
        try:
            s=load_and_scan(path,r,a.as_of,a.verify_calendar,extensions)
            if s["patterns"]:
                results.append(s)
        except (ValueError,KeyError,TypeError,OSError) as e:
            errors.append({"code":path.stem,"reason":str(e)})
    output={"schema":1,"as_of":a.as_of,"status":"research_candidates","calendar_verified":a.verify_calendar,"rules":vars(r),"extensions":vars(extensions) if extensions else None,"candidates":results,"errors":errors}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    temp=a.output.with_suffix(".tmp")
    temp.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    temp.replace(a.output)
    print(json.dumps({"candidates":len(results),"errors":len(errors)},ensure_ascii=False))
if __name__=="__main__":
    main()
