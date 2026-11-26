"""Free-tier-intended, opt-in Gemini analysis. One request per invocation.

A durable reservation is persisted before sending the request. The local limit
covers this new runner only, not other clients sharing the Google project.
"""
import argparse
from datetime import datetime,timedelta,timezone
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo
from .analysis_queue import queue,validate
from .ai_runner import SYSTEM,request

MODEL="gemini-3.5-flash-lite"
PT=ZoneInfo("America/Los_Angeles")
MAX_DAILY=3
MIN_INTERVAL=timedelta(minutes=10)
MAX_OUTPUT=512

def load_ledger(path):
    if not path.exists():
        return {"schema":1,"entries":[]}
    d=json.loads(path.read_text(encoding="utf-8"))
    if d.get("schema")!=1 or not isinstance(d.get("entries"),list):
        raise ValueError("Invalid AI ledger; refuse to reset")
    for e in d["entries"]:
        if not isinstance(e,dict) or not all(k in e for k in ("at","event_id","packet_id","status")):
            raise ValueError("Invalid ledger entry")
        if datetime.fromisoformat(e["at"]).tzinfo is None:
            raise ValueError("Invalid ledger timestamp")
        if e["status"] not in ("reserved","success","failed"):
            raise ValueError("Invalid ledger state")
    return d

def save_ledger(path,d):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(d,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    tmp.replace(path)

def execute(data,ledger,key,now,persist,transport=request,max_daily=MAX_DAILY):
    if not key or now.tzinfo is None or not 1<=max_daily<=MAX_DAILY:
        raise ValueError("Missing credential, timezone or invalid quota")
    entries=ledger["entries"]
    if any(datetime.fromisoformat(e["at"])>now for e in entries):
        raise ValueError("Future ledger timestamp; refuse to call")
    entries[:]=[e for e in entries if datetime.fromisoformat(e["at"])>=now-timedelta(days=30)]
    today=now.astimezone(PT).date()
    daily=[e for e in entries if datetime.fromisoformat(e["at"]).astimezone(PT).date()==today]
    if any(e["status"] in ("failed","reserved") for e in daily):
        return {"status":"stopped_after_failure_or_uncertain_request","attempted":0}
    if len(daily)>=max_daily:
        return {"status":"daily_local_cap","attempted":0}
    if entries and now-max(datetime.fromisoformat(e["at"]) for e in entries)<MIN_INTERVAL:
        return {"status":"local_interval_cap","attempted":0}
    seen_events={e["event_id"] for e in entries}
    seen_packets={e["packet_id"] for e in entries}
    candidates=queue(data,30,60000,max_articles=3)["packets"]
    p=next((p for p in candidates if p["event_id"] not in seen_events and p["packet_id"] not in seen_packets),None)
    if not p:
        return {"status":"no_unseen_candidate","attempted":0}
    payload={"contents":[{"role":"user","parts":[{"text":SYSTEM+"\n"+json.dumps(p,ensure_ascii=False,separators=(",",":"))}]}],
             "generationConfig":{"candidateCount":1,"maxOutputTokens":MAX_OUTPUT,"responseMimeType":"application/json"}}
    if len(payload["contents"][0]["parts"][0]["text"])>12000:
        return {"status":"input_size_cap","attempted":0}
    entry={"at":now.isoformat(),"event_id":p["event_id"],"packet_id":p["packet_id"],"status":"reserved"}
    entries.append(entry)
    # If persistent reservation fails, absolutely no network request is sent.
    persist(ledger)
    try:
        response=transport(MODEL,"generateContent",payload,key)
        candidates=response.get("candidates",[])
        if len(candidates)!=1 or candidates[0].get("finishReason")!="STOP":
            raise ValueError("Incomplete response")
        text="".join(part.get("text","") for part in candidates[0]["content"]["parts"] if not part.get("thought"))
        draft=validate(p,json.loads(text))
    except Exception as e:
        entry["status"]="failed"
        persist(ledger)
        return {"status":"failed_no_retry","attempted":1,"error_type":type(e).__name__}
    entry["status"]="success"
    persist(ledger)
    return {"status":"human_review_required","attempted":1,"draft":draft,"model":MODEL}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--ledger",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--confirm-free-project",action="store_true")
    p.add_argument("--github-ledger",action="store_true")
    a=p.parse_args()
    if not a.confirm_free_project:
        p.error("Verify the Google project is Free tier and confirm explicitly")
    key=os.environ.get("GEMINI_API_KEY")
    if not key:
        p.error("Missing GEMINI_API_KEY")
    if a.github_ledger:
        from data_store import ROOT
        expected=Path(ROOT)/"news_feed"/"smile2-ai-ledger.json"
        if a.ledger.resolve()!=expected.resolve() or not (Path(ROOT)/".data_pulled").is_file():
            p.error("GitHub ledger requires data_store pull and the designated ledger file")
    data=json.loads(a.input.read_text(encoding="utf-8"))
    if data.get("schema")!=1 or not isinstance(data.get("events"),list):
        p.error("Expected public event or briefing JSON")
    a.output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive local lock prevents overlapping invocations using the same ledger.
    a.ledger.parent.mkdir(parents=True,exist_ok=True)
    lock=a.ledger.with_suffix(".lock")
    with lock.open("x",encoding="utf-8"):
        try:
            ledger=load_ledger(a.ledger)
            def persist(d):
                save_ledger(a.ledger,d)
                if a.github_ledger:
                    from data_store import push
                    push("smile2_ai")
            with a.output.open("x",encoding="utf-8") as f:
                result=execute(data,ledger,key,datetime.now(timezone.utc),persist)
                json.dump(result,f,ensure_ascii=False,indent=2)
            print(json.dumps({k:v for k,v in result.items() if k!="draft"},ensure_ascii=False))
        finally:
            lock.unlink(missing_ok=True)
if __name__=="__main__":
    main()
