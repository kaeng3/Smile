"""Build a standalone public-metadata research preview; never include history archives."""
import argparse
from datetime import date, datetime, time
from hashlib import sha256
import re
import json
from pathlib import Path
import shutil
import tempfile
from .news_engine import build, KST, parse_time
from .briefing import briefing
from .quality import review
from .official_feeds import collect
from .media_probe import collect_media
from .market_brief import market_brief
from .taxonomy import group,audit,VERSION
from .featured_news import featured_editions
from .capture_health import capture_health
from .material_stage import annotate_sections
from .editorial_evidence import annotate_sections as annotate_evidence
from .followup_news import followup

ASSETS=("index.html","search.html","style.css","app.js","brief.html","brief.js","candidates.html",
        "candidates.js","candidate_history.js","scanner.js","chart.js","history.html","history.js","themes.html","themes.js","history_compare.js","editorial.html","editorial.css","editorial.js")
JSON_NAMES=("events.json","brief-pre.json","brief-post.json","quality.json",
            "official-status.json","media-status.json","manifest.json","editorial-pre.json","editorial-post.json","taxonomy-audit.json","editorial-followup.json")

def read_rows(path):
    rows=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows,list) or any(not isinstance(x,dict) for x in rows):
        raise ValueError("Expected an article metadata array")
    return rows

def public_rows(rows):
    # Explicit allowlist: no article bodies, private archive excerpts, or API keys.
    keys=("title","url","press","source_feed","source_kind","cat","score","stocks","themes",
          "published_at","observed_at","seen","publication_verified_at","publication_basis","featured_title","featured_observed_at","featured_press","retention_reasons")
    return [{k:r[k] for k in keys if k in r} for r in rows]

def data_market_available(data,day,available):
    return available and market_brief(data,day,{})["status"]=="available"

def generate(rows, day, previous, output, official_rows=(), source_status=(), post_cutoff=time(15,30), session=None, media_rows=(), media_status=(), market_data=None, market_available=False, capture_stats=None,as_of=None):
    if previous>=day:
        raise ValueError("Invalid previous session")
    built=as_of or datetime.now(KST)
    if built.tzinfo is None:raise ValueError("as_of must be timezone aware")
    built=built.astimezone(KST)
    output=Path(output).resolve()
    if output.exists():
        raise FileExistsError("Choose a new empty destination; existing folders are never replaced")
    output.parent.mkdir(parents=True,exist_ok=True)
    rows=public_rows(list(rows)+list(official_rows))
    additional=public_rows(media_rows)
    events=build(rows+additional)
    def report(edition):
        result=briefing(rows,day,previous,edition,post_cutoff,limit=max(50,len(rows)) if edition=="post" and market_available else 50,session=session)
        # Additional sources have not been calibrated against the existing score.
        # Keep them separate rather than assigning artificial importance.
        result["supplemental_media"]=briefing(additional,day,previous,edition,post_cutoff,limit=30,session=session)
        if edition=="post":
            result["market"]=market_brief(market_data if market_available else None,day,result)
            result["events"]=result["events"][:50]
            result["unknown_events_preview"]=result["unknown_events_preview"][:50]
        return result
    def editorial(edition):
        # Separate new report output; retain old 50-item reports and consumers.
        full=briefing(rows,day,previous,edition,post_cutoff,limit=None,session=session,include_late_pre=edition=="pre")
        market=market_brief(market_data if market_available else None,day,full) if edition=="post" else None
        known=full.pop("events");unknown=full.pop("unknown_events_preview")
        if market and market["status"]=="available":
            rates={s["code"]:s["rate_pct"] for s in market["stocks"]}
            def priority(e):
                return -max((rates.get(s["code"],0) for s in e["stocks"]),default=0)
            known.sort(key=priority);unknown.sort(key=priority)
        featured=featured_editions(rows,day,previous,edition,post_cutoff,session)
        full.pop("categories",None)
        return {**full,"built_at":built.isoformat(),"window_status":"partial" if built<parse_time(full["cutoff_exclusive"]) else "closed_window_unreviewed",
                "capture_health":capture_health(capture_stats,built), "market":market,"taxonomy_version":VERSION,"sections":annotate_evidence(annotate_sections(group(known))),
                "unknown_sections":annotate_evidence(annotate_sections(group(unknown))),"featured":featured, "note":"Title-only category research; not verified impact or article summary."}
    extra=followup(rows,day,previous,built,post_cutoff,session)
    data={"events.json":events,
          "editorial-followup.json":extra,
          "brief-pre.json":report("pre"),
          "brief-post.json":report("post"),
          "quality.json":review(events),
          "editorial-pre.json":editorial("pre"),
          "editorial-post.json":editorial("post"),
          "taxonomy-audit.json":audit(events["events"]),
          "official-status.json":{"rows":len(official_rows),"sources":list(source_status),"checked_at":datetime.now(KST).isoformat()},
          "media-status.json":{"rows":len(additional),"sources":list(media_status),"checked_at":datetime.now(KST).isoformat()},
          "manifest.json":{"schema":1,"status":"research_preview","report_date":day.isoformat(),
                           "previous_trading_date":previous.isoformat(),"built_at":built.isoformat(),
                           "preferred_edition":"post" if built>=(parse_time(session["close"]) if session else datetime.combine(day,time(15,30),KST)) else "pre",
                           "input_rows":len(rows)+len(additional),"media_rows":len(additional),"history_included":False,"market_data_included":data_market_available(market_data,day,market_available),
                           "official_rows":len(official_rows),"calendar_basis":"XKRX" if session else "unverified_nominal_hours"}}
    assets=Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix=".smile-preview-",dir=output.parent) as tmp:
        stage=Path(tmp)/"site"
        stage.mkdir()
        for name in ASSETS:
            # Old entry and briefing bookmarks now serve the same B editorial UI.
            source="editorial.html" if name in ("index.html","brief.html") else name
            shutil.copyfile(assets/source,stage/name)
        # The landing page and briefing aliases serve the same versioned assets.
        editorial=(stage/"editorial.html").read_text(encoding="utf-8")
        for asset in ("editorial.js","editorial.css"):
            digest=sha256((stage/asset).read_bytes()).hexdigest()[:12]
            editorial=re.sub(re.escape(asset)+r'(?:\?[^"]*)?"',asset+'?v='+digest+'"',editorial)
        for name in ("index.html","brief.html","editorial.html"):
            (stage/name).write_text(editorial,encoding="utf-8")
        for name in JSON_NAMES:
            (stage/name).write_text(json.dumps(data[name],ensure_ascii=False,separators=(",",":")),encoding="utf-8")
        stage.rename(output)
    return data["manifest.json"]

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--day",type=date.fromisoformat,required=True)
    p.add_argument("--previous",type=date.fromisoformat,required=True)
    p.add_argument("--post-cutoff",type=time.fromisoformat,default=time(15,30))
    p.add_argument("--official",action="store_true",help="Collect public official RSS, no API credentials")
    p.add_argument("--calendar",action="store_true",help="Require XKRX calendar validation")
    p.add_argument("--media",action="store_true",help="Include trial public media feeds; not calibrated importance")
    args=p.parse_args()
    official,status=collect() if args.official else ([],[])
    if args.calendar:
        from .calendar import session_window
        session=session_window(args.day)
    else:
        session=None
    media,media_status=collect_media() if args.media else ([],[])
    manifest=generate(read_rows(args.input),args.day,args.previous,args.output,official,status,args.post_cutoff,session=session,media_rows=media,media_status=media_status)
    print(json.dumps(manifest,ensure_ascii=False))
if __name__=="__main__":
    main()
