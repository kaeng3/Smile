"""Selected scanner observations, not a whole-market ranking or causal analysis."""
from datetime import date,timedelta
from urllib.parse import urlsplit
from math import isfinite
import re
from .news_engine import canonical_url

def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and isfinite(v)

def scanner_links(row,day):
    """Legacy scanner article references; collection/verification time unknown."""
    result=[];seen=set()
    for a in row.get("articles",[]) or []:
        if not isinstance(a,dict):
            continue
        u=canonical_url(a.get("link"))
        press=str(a.get("press") or "")
        if not u or u in seen or "infostock" in (u+" "+press).lower() or "인포스탁" in press:
            continue
        # Do not publish links carrying apparent access credentials.
        from urllib.parse import parse_qsl
        if any(k.lower() in {"key","api_key","token","access_token","auth","signature","sig","session"} for k,v in parse_qsl(urlsplit(u).query)):
            continue
        try:
            d=date.fromisoformat(str(a.get("date") or a.get("datetime") or "")[:10])
        except ValueError:
            continue
        title=str(a.get("title") or "").strip()
        if not title or not day-timedelta(days=3)<=d<=day:
            continue
        seen.add(u)
        result.append({"url":u,"title":title,"date":d.isoformat(),"press":press,
                       "relation":"legacy_scanner_reference_observation_time_unknown"})
    return sorted(result,key=lambda a:a["date"],reverse=True)[:8]

def market_brief(data,day,report):
    key=day.strftime("%Y%m%d")
    rows=data.get(key) if isinstance(data,dict) else None
    if not isinstance(rows,list):
        return {"status":"unavailable","day":day.isoformat(),"stocks":[],"scope":"selected_scanner_rows"}
    links={}
    for e in report.get("events",[])+report.get("unknown_events_preview",[]):
        for a in e.get("articles",[]):
            for name,code in a.get("stocks",[]):
                u=canonical_url(a.get("url"))
                if not u:
                    continue
                links.setdefault(code,{})[u]={"url":u,"title":a["title"],"published_at":a.get("published_at"),
                                               "relation":"same_session_title_mention_not_causation"}
    selected=[];seen=set();invalid=0
    for r in rows:
        if not isinstance(r,dict):
            invalid+=1;continue
        code=str(r.get("code",""));rate=r.get("rate");value=r.get("trading_value")
        if not re.fullmatch(r"[0-9A-Z]{6}",code) or code in seen or not finite(rate) or not finite(value) or value<0:
            invalid+=1;continue
        seen.add(code)
        selected.append({"code":code,"name":str(r.get("name") or code),"rate_pct":rate,"estimated_trading_value_won":value,"trading_value_basis":"close_times_volume",
                         "evidence":list(links.get(code,{}).values())[:5], "scanner_references":scanner_links(r,day)})
    selected.sort(key=lambda r:(-r["rate_pct"],r["code"]))
    return {"status":"available" if selected else "empty","day":day.isoformat(),"stocks":selected,
            "scope":"selected_scanner_rows","invalid_rows":invalid,
            "note":"Existing dated scanner selection, not whole market. Legacy scanner trading value is close times volume, not actual executed turnover. News mentions are not causes. Scanner observation time is not recorded in this dataset."}
