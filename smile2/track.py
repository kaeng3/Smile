"""Local research watchlist state, preserving explicit observations."""
import argparse
from datetime import date
import json
from pathlib import Path

def merge(previous,snapshot):
    day=date.fromisoformat(snapshot["as_of"])
    if previous and day<=date.fromisoformat(previous["as_of"]):
        raise ValueError("Require a strictly later snapshot")
    if snapshot.get("status")!="research_candidates":
        raise ValueError("Not a research snapshot")
    items=dict(previous.get("items",{})) if previous else {}
    seen=set()
    bad={r.get("code") for r in snapshot.get("errors",[])}
    for stock in snapshot["candidates"]:
        for p in stock["patterns"]:
            key="|".join([stock["code"],p["strategy"],p["first_day"]])
            old=items.get(key,{})
            history=list(old.get("history",[]))
            history.append({"day":day.isoformat(),"state":p["state"],"close":p.get("today",{}).get("close")})
            items[key]={"code":stock["code"],"strategy":p["strategy"],"first_day":p["first_day"],
                        "state":p["state"],"last_detected":day.isoformat(),"history":history}
            seen.add(key)
    for key,item in list(items.items()):
        if key in seen:
            continue
        state="자료 오류·미확인" if item["code"] in bad else "미검출·재검토"
        history=list(item["history"])
        history.append({"day":day.isoformat(),"state":state})
        items[key]={**item,"state":state,"history":history}
    return {"schema":1,"as_of":day.isoformat(),"items":items,
            "note":"Missing detection is not invalidation. Local research only."}
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
