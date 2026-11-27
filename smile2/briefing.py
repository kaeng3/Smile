"""Deterministic, as-of-safe briefing candidates; not investment conclusions."""
import argparse
from collections import Counter
from datetime import date, datetime, time
import json
from pathlib import Path
from .news_engine import KST, build, parse_time, seen_time

def bounds(day, previous, edition, post_cutoff=time(15,30), session=None):
    if previous >= day:
        raise ValueError("Previous trading date must precede report date")
    opened=datetime.combine(day,time(9),KST)
    closed=datetime.combine(day,time(15,30),KST)
    previous_closed=datetime.combine(previous,time(15,30),KST)
    if session is not None:
        if session.get("day")!=day.isoformat() or session.get("previous")!=previous.isoformat() or session.get("calendar")!="XKRX":
            raise ValueError("Calendar and requested trading dates disagree")
        opened,closed,previous_closed=(parse_time(session[k]) for k in ("open","close","previous_close"))
        if not all((opened,closed,previous_closed)) or not (previous_closed<opened<closed) or opened.date()!=day or closed.date()!=day or previous_closed.date()!=previous:
            raise ValueError("Invalid exchange session times")
    if edition == "pre":
        return datetime.combine(previous,time(15,30),KST),datetime.combine(day,time(7),KST)
    if edition == "post":
        end=datetime.combine(day,post_cutoff,KST)
        if end<datetime.combine(day,time(15,30),KST):
            raise ValueError("Post cutoff must be at or after nominal 15:30")
        return datetime.combine(day,time(8),KST),end
    raise ValueError("Unknown edition")

def briefing(rows, day, previous, edition, post_cutoff=time(15,30), limit=50, session=None):
    if limit is not None and limit < 1:
        raise ValueError("limit must be positive")
    start,end=bounds(day,previous,edition,post_cutoff,session)
    known,unknown=[],[]
    future=late=0
    for r in rows:
        if not isinstance(r,dict):
            continue
        seen=parse_time(r.get("observed_at")) or seen_time(r.get("seen"))
        pub=parse_time(r.get("published_at"))
        if seen is None:
            continue # no proof it was available at cutoff
        if seen>=end:
            late+=1
            continue
        verified=parse_time(r.get("publication_verified_at"))
        if verified and verified>=end:
            pub=None
            r={**r,"published_at":None}
        if pub and pub>seen:
            future+=1
            continue
        if pub and start<=pub<end:
            known.append(r)
        elif pub is None and start<=seen<end:
            unknown.append(r)
    primary=build(known)
    fallback=build(unknown)
    def rank(e):
        # Existing keyword score is only a heuristic, not measured impact.
        return (-e["keyword_score"],-e["source_count"],e["id"])
    selected=sorted(primary["events"],key=rank)[:limit]
    uncertain=sorted(fallback["events"],key=rank)[:limit]
    return {"schema":1,"edition":edition,"report_date":day.isoformat(),
            "previous_trading_date":previous.isoformat(),"start":start.isoformat(),
            "cutoff_exclusive":end.isoformat(),"status":"candidate_only",
            "calendar_basis":"XKRX" if session else "unverified_nominal_hours","window_policy":"smile3_fixed_kst_v1",
            "published_articles":len(known),"unknown_articles":len(unknown),
            "excluded_late_or_after_cutoff":late,"excluded_inconsistent_timestamp":future,
            "published_events":primary["event_count"],"unknown_events":fallback["event_count"],
            "categories":dict(Counter(e["category"] for e in primary["events"])),
            "events":selected,"unknown_events_preview":uncertain,
            "note":"Title-based candidates. Unknown publication times remain separate. No verified price causation or event occurrence times."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--day",type=date.fromisoformat,required=True)
    p.add_argument("--previous",type=date.fromisoformat,required=True)
    p.add_argument("--edition",choices=["pre","post"],required=True)
    p.add_argument("--post-cutoff",type=time.fromisoformat,default=time(15,30))
    p.add_argument("--calendar",action="store_true",help="Require XKRX calendar validation")
    a=p.parse_args()
    rows=json.loads(a.input.read_text(encoding="utf-8"))
    if not isinstance(rows,list):
        p.error("Expected list of articles")
    if a.calendar:
        from .calendar import session_window
        session=session_window(a.day)
    else:
        session=None
    result=briefing(rows,a.day,a.previous,a.edition,a.post_cutoff,session=session)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    tmp=a.output.with_suffix(".tmp")
    tmp.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    tmp.replace(a.output)
    print(json.dumps({k:v for k,v in result.items() if k not in ("events","unknown_events_preview")},ensure_ascii=False))
if __name__=="__main__":
    main()
