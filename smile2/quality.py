"""Review queue for similar headlines; never automatically assert same event."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from .news_engine import normalize, tokens, parse_time

def grams(title):
    s=normalize(title).replace(" ","")
    return {s[i:i+3] for i in range(max(0,len(s)-2))}

def jaccard(a,b):
    return len(a&b)/len(a|b) if a and b else 0.0

def representative(event):
    a=event["articles"][0]
    return a,parse_time(a.get("published_at")) or parse_time(a.get("seen_at"))

def signature(text):
    # Do not lose quantities, percentages or signs during normalization.
    return re.findall(r"[+-]?\d[\d,.]*(?:%|억원|억|조원|조|만|원|달러)?",text)

def review(data,limit=100):
    events=data["events"]
    gs=[grams(e["headline"]) for e in events]
    ts=[tokens(e["headline"]) for e in events]
    counts=Counter(g for x in gs for g in x)
    index=defaultdict(list)
    out=[]
    for i,e in enumerate(events):
        a,at=representative(e)
        # Rare trigrams are used for bounded retrieval; recall must be measured separately.
        keys=sorted(gs[i],key=lambda g:(counts[g],g))[:12]
        candidates=set(j for g in keys for j in index[g])
        for j in candidates:
            b,bt=representative(events[j])
            if not at or not bt or abs((at-bt).total_seconds())>48*3600:
                continue
            if signature(a["title"])!=signature(b["title"]):
                continue
            ta,tb=set(a["event_types"]),set(b["event_types"])
            if ta and tb and ta!=tb:
                continue
            ca,cb={x[1] for x in a["stocks"]},{x[1] for x in b["stocks"]}
            if ca and cb and not ca&cb:
                continue
            # Different stages (plans, denial, approval) are kept apart.
            stage=lambda s:{x for x in ("검토","추진","신청","승인","허가","부인","철회","취소","완료","중단","예정") if x in s}
            if stage(a["title"])!=stage(b["title"]):
                continue
            char=jaccard(gs[i],gs[j]); word=jaccard(ts[i],ts[j])
            if char<.60 or word<.25:
                continue
            score=round(.7*char+.3*word,3)
            out.append({"a":events[j]["id"],"b":e["id"],"score":score,"status":"human_review_required"})
        for g in gs[i]:
            if counts[g]<=250: index[g].append(i)
    out.sort(key=lambda x:(-x["score"],x["a"],x["b"]))
    return {"schema":1,"event_count":len(events),
            "multi_article_events":sum(e["article_count"]>1 for e in events),
            "multi_source_events":sum(e["source_count"]>1 for e in events),
            "review_pair_count":len(out),"review_pairs":out[:limit],
            "note":"Review candidates only; no measured precision/recall and no automatic merge."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    data=review(json.loads(a.input.read_text(encoding="utf-8")))
    a.output.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({k:v for k,v in data.items() if k!="review_pairs"},ensure_ascii=False))
if __name__=="__main__":
    main()
