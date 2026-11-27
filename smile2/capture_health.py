"""Latest collection health, explicitly not report-window coverage."""
from .news_engine import parse_time,seen_time

def capture_health(stats,now):
    if not isinstance(stats,dict) or not isinstance(stats.get("source_health"),list):
        return {"status":"unknown","scope":"latest_capture_only","sources":[]}
    stamp=parse_time(stats.get("capture_completed_at")) or seen_time(stats.get("updated"))
    if stamp is None or stamp>now:
        return {"status":"unknown","scope":"latest_capture_only","sources":[]}
    sources=[]
    for s in stats["source_health"]:
        if not isinstance(s,dict) or not isinstance(s.get("source"),str) or s.get("status") not in ("ok","empty","failed"):
            continue
        sources.append({k:s[k] for k in ("source","status","count","attempts","checked_at","timestamp_count","possible_truncation","http_status","error_type") if k in s})
    if not sources:return {"status":"unknown","scope":"latest_capture_only","sources":[]}
    ok=sum(s["status"]=="ok" for s in sources)
    status="stale" if (now-stamp).total_seconds()>5400 else "partial" if ok<len(sources) else "success"
    out={"status":status,"scope":"latest_capture_only","checked_at":stamp.isoformat(),"ok":ok,"total":len(sources),"sources":sources,
         "note":"A successful fetch does not establish complete publication coverage."}
    for k in ("raw_unique_valid_urls","raw_unique_not_retained","score_filtered_unique_urls"):
        if type(stats.get(k)) is int and stats[k]>=0:out[k]=stats[k]
    return out
