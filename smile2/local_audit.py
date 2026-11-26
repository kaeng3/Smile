"""Read-only preflight for local regular-session JSON. No network, no uploads."""
import argparse
from collections import Counter
from datetime import date
from pathlib import Path
import json
import re
from .patterns import bars
from .calendar import session_window
from .session_check import expected_sessions, compare_sessions

def audit(root,day,min_bars,check_calendar=True):
    if type(min_bars) is not int or min_bars<5:
        raise ValueError("min_bars must be at least 5")
    root=Path(root)
    if not root.is_dir():
        raise ValueError("Local data directory not found")
    if check_calendar:
        session_window(day)
    count=Counter();coverage=Counter();ready=0;total=0
    for p in sorted(root.glob("*.json")):
        if not re.fullmatch(r"[0-9A-Z]{6}",p.stem):continue
        total+=1
        try:
            if p.is_symlink() or p.stat().st_size>32*1024*1024:
                count["unsupported_file"]+=1;continue
            raw=json.loads(p.read_text(encoding="utf-8-sig"))
            if not isinstance(raw,dict) or raw.get("schema")!=1 or raw.get("source")!="DAUM_KRX_REGULAR":
                count["source_or_schema_unverified"]+=1;continue
            rows=bars(raw["records"])
            if not rows:
                count["empty"]+=1;continue
            coverage[rows[-1]["day"]]+=1
            if rows[-1]["day"]!=day.isoformat():
                count["stale" if rows[-1]["day"]<day.isoformat() else "future_rows"]+=1;continue
            if len(rows)<min_bars:
                count["insufficient_history"]+=1;continue
            # Inspect the most recent required window, not a newly listed stock's
            # entire lifetime. This is an audit only, not a scan guarantee.
            w=rows[-min_bars:]
            if any(x["volume"]<=0 or x["value"]<=0 for x in w):
                count["zero_volume_or_value"]+=1;continue
            if any(not x["low"]*x["volume"]<=x["value"]<=x["high"]*x["volume"] for x in w):
                count["turnover_outside_price_range"]+=1;continue
            if check_calendar:
                diff=compare_sessions(w,expected_sessions(w[0]["day"],w[-1]["day"]))
                if diff["missing"] or diff["unexpected"]:
                    count["session_gap_or_unexpected_day"]+=1;continue
            ready+=1
        except (OSError,ValueError,KeyError,TypeError,OverflowError,AttributeError):
            count["invalid_file_or_bar"]+=1
    return {"schema":1,"as_of":day.isoformat(),"min_bars":min_bars,"files":total,
            "window_passed":ready,"rejected":dict(sorted(count.items())),
            "latest_date_counts":dict(sorted(coverage.items())),
            "calendar_checked":check_calendar,
            "status":"local_preflight_only",
            "note":"Aggregates only. Source label and turnover range checks do not prove provider/session scope. No full-history or strategy validation."}

def main():
    p=argparse.ArgumentParser(description="Local regular-session data readiness audit")
    p.add_argument("--input-dir",type=Path,required=True)
    p.add_argument("--as-of",type=date.fromisoformat,required=True)
    p.add_argument("--min-bars",type=int,required=True)
    p.add_argument("--without-calendar",action="store_true",help="Format checks only; not session verified")
    a=p.parse_args()
    print(json.dumps(audit(a.input_dir,a.as_of,a.min_bars,not a.without_calendar),ensure_ascii=False,indent=2))
if __name__=="__main__":main()
