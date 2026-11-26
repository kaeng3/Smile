"""Local research watchlist state, preserving explicit observations."""
import argparse
from datetime import date
from math import isfinite
import json
from pathlib import Path

def positive(v):
    return type(v) in (int,float) and isfinite(v) and v>0

def levels(pattern,old):
    # Preserve anchor references for the episode; a rolling box must not
    # silently move the original support. A rising-channel projection is
    # retained as the original level, not extended into later sessions.
    if old.get("reference_levels"):
        return old["reference_levels"]
    box=pattern.get("box") or {}
    first=pattern.get("first") or {}
    values={"first_close":first.get("close"),"initial_box_upper":box.get("upper"),
            "initial_box_lower":box.get("lower")}
    return {k:v for k,v in values.items() if positive(v)}

def assess(item,obs,day,verified):
    if not verified or not isinstance(obs,dict) or obs.get("day")!=day or not positive(obs.get("close")):
        return None
    refs=item.get("reference_levels",{})
    c=obs["close"]
    states={k:("below" if c<v else "held") for k,v in refs.items() if positive(v)}
    # An anchor close below the upper line is only a caution. No automatic
    # invalidation or buy/sell signal is inferred from reference crossings.
    key="initial_box_lower" if item["strategy"]=="고가놀이" else "first_close"
    primary=states.get(key)
    return {"day":day,"close":c,"reference_status":states,
            "assessment":"기준 지지선 종가 이탈 주의" if primary=="below" else "기준 지지선 종가 유지" if primary=="held" else "기준 지지선 미확인",
            "basis":"fixed_initial_reference_not_dynamic_stop"}

def merge(previous,snapshot):
    day=date.fromisoformat(snapshot["as_of"])
    if previous and day<=date.fromisoformat(previous["as_of"]):
        raise ValueError("Require a strictly later snapshot")
    if snapshot.get("status")!="research_candidates":
        raise ValueError("Not a research snapshot")
    items=dict(previous.get("items",{})) if previous else {}
    seen=set()
    verified=snapshot.get("calendar_verified") is True and snapshot.get("source")=="DAUM_KRX_REGULAR"
    observations=snapshot.get("observations",{})
    if not isinstance(observations,dict):
        raise ValueError("Invalid observation map")
    bad={r.get("code") for r in snapshot.get("errors",[])}
    for stock in snapshot["candidates"]:
        for p in stock["patterns"]:
            key="|".join([stock["code"],p["strategy"],p["first_day"]])
            old=items.get(key,{})
            history=list(old.get("history",[]))
            item={"code":stock["code"],"strategy":p["strategy"],"first_day":p["first_day"],
                  "state":p["state"],"last_detected":day.isoformat(),"reference_levels":levels(p,old)}
            observed=assess(item,observations.get(stock["code"]),day.isoformat(),verified and stock["code"] not in bad)
            history.append({"day":day.isoformat(),"state":p["state"],"close":p.get("today",{}).get("close"),
                            "observation":observed})
            items[key]={**item,"history":history,"latest_observation":observed}
            seen.add(key)
    for key,item in list(items.items()):
        if key in seen:
            continue
        observed=assess(item,observations.get(item["code"]),day.isoformat(),verified and item["code"] not in bad)
        state="자료 오류·미확인" if item["code"] in bad else "미검출·재검토"
        if observed:
            state="미검출·"+observed["assessment"]
        elif item["code"] not in bad and "observations" in snapshot and item["code"] not in observations:
            state="당일 자료 미확인"
        history=list(item["history"])
        history.append({"day":day.isoformat(),"state":state,"observation":observed})
        items[key]={**item,"state":state,"history":history,"latest_observation":observed}
    return {"schema":1,"as_of":day.isoformat(),"items":items,
            "note":"Missing detection is not invalidation. Fixed reference crossings are cautions, not trading signals. Local research only."}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--snapshot",type=Path,required=True)
    p.add_argument("--state",type=Path,required=True)
    a=p.parse_args()
    previous=json.loads(a.state.read_text(encoding="utf-8")) if a.state.exists() else {}
    result=merge(previous,json.loads(a.snapshot.read_text(encoding="utf-8")))
    a.state.parent.mkdir(parents=True,exist_ok=True)
    tmp=a.state.with_suffix(".tmp")
    tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(a.state)
    print(json.dumps({"tracked":len(result["items"]),"as_of":result["as_of"]}))
if __name__=="__main__":
    main()
