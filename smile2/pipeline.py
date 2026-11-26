"""Build a standalone public-metadata research preview; never include history archives."""
import argparse
from datetime import date, datetime, time
import json
from pathlib import Path
import shutil
import tempfile
from .news_engine import build, KST
from .briefing import briefing
from .quality import review
from .official_feeds import collect

ASSETS=("index.html","style.css","app.js","brief.html","brief.js","candidates.html",
        "candidates.js","chart.js","history.html","history.js")
JSON_NAMES=("events.json","brief-pre.json","brief-post.json","quality.json",
            "official-status.json","manifest.json")

def read_rows(path):
    rows=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows,list) or any(not isinstance(x,dict) for x in rows):
        raise ValueError("Expected an article metadata array")
    return rows

def public_rows(rows):
    # Explicit allowlist: no article bodies, private archive excerpts, or API keys.
    keys=("title","url","press","source_feed","source_kind","cat","score","stocks","themes",
          "published_at","observed_at","seen","publication_verified_at")
    return [{k:r[k] for k in keys if k in r} for r in rows]

def generate(rows, day, previous, output, official_rows=(), source_status=(), post_cutoff=time(18)):
    if previous>=day:
        raise ValueError("Invalid previous session")
    output=Path(output).resolve()
    if output.exists():
        raise FileExistsError("Choose a new empty destination; existing folders are never replaced")
    output.parent.mkdir(parents=True,exist_ok=True)
    rows=public_rows(list(rows)+list(official_rows))
    events=build(rows)
    data={"events.json":events,
          "brief-pre.json":briefing(rows,day,previous,"pre",post_cutoff),
          "brief-post.json":briefing(rows,day,previous,"post",post_cutoff),
          "quality.json":review(events),
          "official-status.json":{"rows":len(official_rows),"sources":list(source_status),"checked_at":datetime.now(KST).isoformat()},
          "manifest.json":{"schema":1,"status":"research_preview","report_date":day.isoformat(),
                           "previous_trading_date":previous.isoformat(),"built_at":datetime.now(KST).isoformat(),
                           "input_rows":len(rows),"history_included":False,"market_data_included":False,
                           "official_rows":len(official_rows)}}
    assets=Path(__file__).resolve().parent
    with tempfile.TemporaryDirectory(prefix=".smile-preview-",dir=output.parent) as tmp:
        stage=Path(tmp)/"site"
        stage.mkdir()
        for name in ASSETS:
            shutil.copyfile(assets/name,stage/name)
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
    p.add_argument("--post-cutoff",type=time.fromisoformat,default=time(18))
    p.add_argument("--official",action="store_true",help="Collect public official RSS, no API credentials")
    args=p.parse_args()
    official,status=collect() if args.official else ([],[])
    manifest=generate(read_rows(args.input),args.day,args.previous,args.output,official,status,args.post_cutoff)
    print(json.dumps(manifest,ensure_ascii=False))
if __name__=="__main__":
    main()
