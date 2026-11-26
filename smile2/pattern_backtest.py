"""Local-only, next-open forward-return study. No execution or trading advice."""
import argparse
from collections import defaultdict,Counter
from datetime import date
from statistics import mean,median
from pathlib import Path
import json
import re
from .patterns import Rules,bars,scan
from .extended_patterns import Extensions
from .session_check import require_sessions

def evaluate(records,r,start,end,horizons,extensions=None,verify_calendar=True):
    if start>end or not horizons or len(set(horizons))!=len(horizons) or any(type(h) is not int or not 1<=h<=60 for h in horizons):
        raise ValueError("Invalid evaluation dates/horizons")
    b=bars(records)
    # Strictly cap data at study end, including outcome labels.
    b=[x for x in b if x["day"]<=end.isoformat()]
    if verify_calendar and b:
        require_sessions(b)
    if any(x["volume"]<=0 or x["value"]<=0 or not x["low"]*x["volume"]<=x["value"]<=x["high"]*x["volume"] for x in b):
        raise ValueError("Invalid turnover or zero-volume session")
    samples=[];seen=set()
    for i,x in enumerate(b):
        if x["day"]<start.isoformat():continue
        # The detector sees exactly the information available at this close.
        for p in scan(b[:i+1],r,extensions):
            # Keep first occurrence of each episode/state, rather than counting
            # every day that an unchanged support signal persists.
            key=(p["strategy"],p["first_day"],p["state"])
            if key in seen:continue
            seen.add(key)
            outcome={}
            for h in horizons:
                if i+h>=len(b):
                    outcome[h]=None;continue
                entry=b[i+1]["open"];exit=b[i+h]["close"]
                outcome[h]=100*(exit/entry-1)
            samples.append({"day":x["day"],"strategy":p["strategy"],"state":p["state"],"returns":outcome})
    return samples

def summarize(samples,horizons):
    groups=defaultdict(list)
    for s in samples:groups[(s["strategy"],s["state"])].append(s)
    result=[]
    for (strategy,state),ss in sorted(groups.items()):
        outcomes={}
        for h in horizons:
            vals=[s["returns"][h] for s in ss if s["returns"][h] is not None]
            n=len(vals)
            outcomes[str(h)]={"n":n,"unavailable":len(ss)-n,"mean_pct":round(mean(vals),4) if n else None,
                              "median_pct":round(median(vals),4) if n else None,
                              "positive_pct":round(100*sum(v>0 for v in vals)/n,2) if n else None}
        result.append({"strategy":strategy,"state":state,"signals":len(ss),"horizons":outcomes})
    return result

def run(root,r,start,end,horizons,extensions=None):
    root=Path(root)
    if not root.is_dir():raise ValueError("Local directory missing")
    from .calendar import session_window
    session_window(start);session_window(end)
    out=[];errors=Counter();valid=0
    for p in sorted(root.glob("*.json")):
        if not re.fullmatch(r"[0-9A-Z]{6}",p.stem):continue
        try:
            if p.is_symlink() or p.stat().st_size>32*1024*1024:raise ValueError("unsupported file")
            d=json.loads(p.read_text(encoding="utf-8-sig"))
            if d.get("schema")!=1 or d.get("source")!="DAUM_KRX_REGULAR":raise ValueError("source")
            out.extend(evaluate(d["records"],r,start,end,horizons,extensions))
            valid+=1
        except (ValueError,KeyError,TypeError,OSError,OverflowError,AttributeError) as e:
            errors[type(e).__name__]+=1
    return {"schema":1,"status":"local_research_only","start":start.isoformat(),"end":end.isoformat(),
            "calendar":"XKRX","valid_files":valid,"rejected":dict(errors),"rules":vars(r),
            "extensions":vars(extensions) if extensions else None,"groups":summarize(out,horizons),
            "note":"Conditional gross forward returns, next session open to horizon close. No costs, slippage, corporate action adjustment, portfolio constraints, benchmark, or survivorship correction. Overlapping samples are dependent. Not a strategy profitability claim."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--rules",type=Path,required=True)
    p.add_argument("--extensions",type=Path)
    p.add_argument("--start",type=date.fromisoformat,required=True)
    p.add_argument("--end",type=date.fromisoformat,required=True)
    p.add_argument("--horizons",type=int,nargs="+",required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    r=Rules(**json.loads(a.rules.read_text(encoding="utf-8")))
    e=Extensions(**json.loads(a.extensions.read_text(encoding="utf-8"))) if a.extensions else None
    result=run(a.input_dir,r,a.start,a.end,a.horizons,e)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("x",encoding="utf-8") as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({"valid_files":result["valid_files"],"groups":len(result["groups"]),"rejected":result["rejected"]}))
if __name__=="__main__":main()
