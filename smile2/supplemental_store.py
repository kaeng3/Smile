"""Persist official public RSS metadata without replacing prior observations."""
import argparse
from datetime import datetime,timedelta
import json
from pathlib import Path
from .news_engine import KST,canonical_url,parse_time
from .official_feeds import collect

def merge(previous,incoming,now,days=10):
    by_url={}
    for row in list(previous)+list(incoming):
        url=canonical_url(row.get("url"))
        seen=parse_time(row.get("observed_at"))
        if not url or not seen or seen>now or seen<now-timedelta(days=days):
            continue
        pub=parse_time(row.get("published_at"))
        if pub and pub>seen:
            row={**row,"published_at":None}
        old=by_url.get(url)
        if old is None or seen<parse_time(old["observed_at"]):
            by_url[url]={**row,"url":url}
        elif not old.get("published_at") and row.get("published_at"):
            old["published_at"]=row["published_at"]
            old["publication_verified_at"]=seen.isoformat()
    return sorted(by_url.values(),key=lambda r:r["observed_at"],reverse=True)

def capture(path):
    now=datetime.now(KST)
    prior=json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    rows,status=collect()
    now=datetime.now(KST)
    result={"schema":1,"checked_at":now.isoformat(),"sources":status,
            "rows":merge(prior.get("rows",[]),rows,now)}
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    temp.replace(path)
    return {"rows":len(result["rows"]),"sources":status}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(capture(a.output),ensure_ascii=False))
if __name__=="__main__":
    main()
