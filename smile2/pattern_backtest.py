"""Local-only, next-open forward-return study. No execution or trading advice."""
import argparse
from collections import defaultdict,Counter
from datetime import date
from math import isfinite
from dataclasses import dataclass
from statistics import mean,median
from pathlib import Path
import json
import re
from .patterns import Rules,bars,scan_at
from .extended_patterns import Extensions
from .session_check import require_sessions

@dataclass(frozen=True)
class Costs:
    buy_bps:float
    sell_bps:float
    buy_slippage_bps:float
    sell_slippage_bps:float
    def __post_init__(self):
        if any(type(v) not in (int,float) or not isfinite(v) or not 0<=v<10000 for v in vars(self).values()):
            raise ValueError("Cost assumptions must be finite nonnegative basis points below 10000")
    def net(self,gross_pct):
        ratio=1+gross_pct/100
        return 100*(ratio*(1-self.sell_slippage_bps/10000)*(1-self.sell_bps/10000)
                    /((1+self.buy_slippage_bps/10000)*(1+self.buy_bps/10000))-1)

def evaluate(records,r,start,end,horizons,extensions=None,verify_calendar=True,split=None,costs=None):
    if start>end or not horizons or len(set(horizons))!=len(horizons) or any(type(h) is not int or not 1<=h<=60 for h in horizons):
        raise ValueError("Invalid evaluation dates/horizons")
    if split is not None and not start<split<=end:
        raise ValueError("Validation start must follow research start and not exceed end")
    b=bars(records)
    # Strictly cap data at study end, including outcome labels.
    b=[x for x in b if x["day"]<=end.isoformat()]
    if not b or not any(x["day"]>=start.isoformat() for x in b):
        raise ValueError("No bars in study period")
    if verify_calendar:
        require_sessions(b)
    if any(x["volume"]<=0 or x["value"]<=0 or not x["low"]*x["volume"]<=x["value"]<=x["high"]*x["volume"] for x in b):
        raise ValueError("Invalid turnover or zero-volume session")
    samples=[];seen=set()
    for i,x in enumerate(b):
        # Inspect pre-period signals as well, so a previously detected episode
        # is not counted as a new signal solely because the study has started.
        # scan_at accesses only the current index and preceding bars.
        # Normalize and sort once instead of revalidating every prefix.
        for p in scan_at(b,i,r,extensions):
            # Keep first occurrence of each episode/state, rather than counting
            # every day that an unchanged support signal persists.
            key=(p["strategy"],p["first_day"],p["state"])
            if key in seen:continue
            seen.add(key)
            if x["day"]<start.isoformat():continue
            phase="validation" if split and x["day"]>=split.isoformat() else "development" if split else "unsplit"
            outcome={}
            for h in horizons:
                if i+h>=len(b) or (split and phase=="development" and b[i+h]["day"]>=split.isoformat()):
                    outcome[h]=None;continue
                entry=b[i+1]["open"];exit=b[i+h]["close"]
                outcome[h]=100*(exit/entry-1)
            sample={"day":x["day"],"strategy":p["strategy"],"state":p["state"],"returns":outcome,"phase":phase}
            if costs is not None:
                sample["net_returns"]={h:costs.net(v) if v is not None else None for h,v in outcome.items()}
            samples.append(sample)
    return samples

def summarize(samples,horizons):
    groups=defaultdict(list)
    for s in samples:groups[(s.get("phase","unsplit"),s["strategy"],s["state"])].append(s)
    result=[]
    for (phase,strategy,state),ss in sorted(groups.items()):
        outcomes={}
        for h in horizons:
            vals=[s["returns"][h] for s in ss if s["returns"][h] is not None]
            n=len(vals)
            outcomes[str(h)]={"n":n,"unavailable":len(ss)-n,"mean_pct":round(mean(vals),4) if n else None,
                              "median_pct":round(median(vals),4) if n else None,
                              "positive_pct":round(100*sum(v>0 for v in vals)/n,2) if n else None}
            if all("net_returns" in s for s in ss):
                net=[s["net_returns"][h] for s in ss if s["net_returns"][h] is not None]
                outcomes[str(h)].update({"net_mean_pct":round(mean(net),4) if net else None,
                    "net_median_pct":round(median(net),4) if net else None,
                    "net_positive_pct":round(100*sum(v>0 for v in net)/len(net),2) if net else None})
        result.append({"phase":phase,"strategy":strategy,"state":state,"signals":len(ss),"horizons":outcomes})
    return result

def run(root,r,start,end,horizons,extensions=None,split=None,costs=None):
    root=Path(root)
    if not root.is_dir():raise ValueError("Local directory missing")
    from .calendar import session_window
    session_window(start);session_window(end)
    if split is not None:
        if not start<split<=end:raise ValueError("Invalid validation start")
        session_window(split)
    out=[];errors=Counter();valid=0
    for p in sorted(root.glob("*.json")):
        if not re.fullmatch(r"[0-9A-Z]{6}",p.stem):continue
        try:
            if p.is_symlink() or p.stat().st_size>32*1024*1024:raise ValueError("unsupported file")
            d=json.loads(p.read_text(encoding="utf-8-sig"))
            if d.get("schema")!=1 or d.get("source")!="DAUM_KRX_REGULAR":raise ValueError("source")
            out.extend(evaluate(d["records"],r,start,end,horizons,extensions,split=split,costs=costs))
            valid+=1
        except (ValueError,KeyError,TypeError,OSError,OverflowError,AttributeError) as e:
            errors[type(e).__name__]+=1
    return {"schema":1,"status":"local_research_only","start":start.isoformat(),"end":end.isoformat(),
            "calendar":"XKRX","valid_files":valid,"rejected":dict(errors),"rules":vars(r),
            "extensions":vars(extensions) if extensions else None,"groups":summarize(out,horizons),
            "validation_start":split.isoformat() if split else None,"cost_assumptions_bps":vars(costs) if costs else None,
            "note":"Conditional forward returns, next session open to horizon close. Net estimates only when explicit cost assumptions supplied. Development outcomes crossing validation start are censored. No corporate action adjustment, fill guarantee, portfolio constraints, benchmark, or survivorship correction. Overlapping samples are dependent. Not a strategy profitability claim."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--rules",type=Path,required=True)
    p.add_argument("--extensions",type=Path)
    p.add_argument("--start",type=date.fromisoformat,required=True)
    p.add_argument("--end",type=date.fromisoformat,required=True)
    p.add_argument("--horizons",type=int,nargs="+",required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--validation-start",type=date.fromisoformat)
    p.add_argument("--costs",type=Path,help="Explicit JSON of buy/sell fee and slippage assumptions in basis points")
    a=p.parse_args()
    r=Rules(**json.loads(a.rules.read_text(encoding="utf-8")))
    e=Extensions(**json.loads(a.extensions.read_text(encoding="utf-8"))) if a.extensions else None
    costs=Costs(**json.loads(a.costs.read_text(encoding="utf-8"))) if a.costs else None
    result=run(a.input_dir,r,a.start,a.end,a.horizons,e,a.validation_start,costs)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("x",encoding="utf-8") as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({"valid_files":result["valid_files"],"groups":len(result["groups"]),"rejected":result["rejected"]}))
if __name__=="__main__":main()
