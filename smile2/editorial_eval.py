"""ECC-inspired evaluation harness for editorial taxonomy.
Offline only. Blind human labels, deterministic content-addressed sampling.
No model call or claim of accuracy without human adjudication.
"""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from .taxonomy import classify,LABELS,VERSION
from .analysis_queue import digest

def identity(e):
    # Only public headline/source metadata; changing content invalidates labels.
    evidence=[{"title":a["title"],"url":a["url"],"press":a.get("press",""),
               "published_at":a.get("published_at")} for a in e["articles"]]
    return {"event_id":e["id"],"headline":e["headline"],"evidence":evidence}

def sample(data,size,seed,mode="uniform"):
    if type(size) is not int or not 1<=size<=500 or not isinstance(seed,str) or not seed or mode not in ("uniform","review"):
        raise ValueError("Invalid sample settings")
    events=data["events"]
    if len({e["id"] for e in events})!=len(events):raise ValueError("Duplicate event ID")
    ranked=sorted(events,key=lambda e:(hashlib.sha256((seed+"\0"+digest(identity(e))).encode()).hexdigest(),e["id"]))
    if mode=="review":
        ranked=[e for e in ranked if classify(e["headline"],e.get("category",""))["review_required"]]
    selected=ranked[:size]
    items=[]
    for e in selected:
        item=identity(e)
        item["content_id"]=digest(item)
        items.append(item)
    body={"schema":1,"mode":mode,"seed":seed,"population":len(ranked),"items":items}
    return {**body,"sample_id":digest(body)}

def evaluate(data,packet,labels):
    if digest({k:v for k,v in packet.items() if k!="sample_id"})!=packet.get("sample_id"):
        raise ValueError("Sample changed")
    if labels.get("sample_id")!=packet["sample_id"]:
        raise ValueError("Wrong sample labels")
    events={e["id"]:e for e in data["events"]}
    if len(events)!=len(data["events"]):raise ValueError("Duplicate event ID")
    ids={x["content_id"]:x for x in packet["items"]}
    if len(ids)!=len(packet["items"]):raise ValueError("Duplicate sample content")
    supplied=labels["labels"]
    if not isinstance(supplied,list):raise ValueError("Invalid labels")
    gold={}
    for r in supplied:
        if not isinstance(r,dict) or set(r)!={"content_id","category_id","basis"}:
            raise ValueError("Invalid human label fields")
        k=r["content_id"]
        if k not in ids or k in gold or r["category_id"] not in LABELS or r["basis"] not in ("title_only","source_checked","insufficient"):
            raise ValueError("Invalid or repeated human label")
        if r["basis"]=="insufficient" and r["category_id"]!="other":
            raise ValueError("Insufficient evidence must remain unclassified")
        gold[k]=r
    matrix=Counter();checked=0;abstained=0;correct=0;classified_correct=0;review=0;basis=Counter()
    for k,item in ids.items():
        e=events.get(item["event_id"])
        if e is None or digest(identity(e))!=k:raise ValueError("Source content missing or changed")
        if k not in gold:continue
        c=classify(e["headline"],e.get("category",""))
        actual=gold[k]["category_id"];pred=c["category_id"]
        matrix[(actual,pred)]+=1;basis[gold[k]["basis"]]+=1
        checked+=1;correct+=actual==pred;abstained+=pred=="other"
        classified_correct+=actual==pred and pred!="other";review+=c["review_required"]
    def ratio(a,b):return round(a/b,4) if b else None
    per_category={}
    for cat in LABELS:
        tp=matrix[(cat,cat)];actual=sum(n for (a,p),n in matrix.items() if a==cat);pred=sum(n for (a,p),n in matrix.items() if p==cat)
        per_category[cat]={"support":actual,"predicted":pred,"precision":ratio(tp,pred),"recall":ratio(tp,actual)}
    return {"schema":1,"taxonomy_version":VERSION,"sample_id":packet["sample_id"],"mode":packet["mode"],
            "sample_size":len(ids),"labeled":checked,"unlabeled":len(ids)-checked,
            "status":"complete_label_set" if checked==len(ids) and checked else "incomplete_labels",
            "agreement":ratio(correct,checked),"classified_agreement":ratio(classified_correct,checked-abstained),
            "abstention_rate":ratio(abstained,checked),"review_rate":ratio(review,checked),
            "label_basis":dict(basis),"per_category":per_category,
            "confusion":[{"actual":a,"predicted":p,"count":n} for (a,p),n in sorted(matrix.items()) if n],
            "note":"Human-label agreement on this sample only. Review-mode samples are deliberately biased; title-only labels do not verify facts. No automatic release approval."}

def main():
    p=argparse.ArgumentParser()
    sub=p.add_subparsers(dest="command",required=True)
    s=sub.add_parser("sample");s.add_argument("--size",type=int,required=True);s.add_argument("--seed",required=True);s.add_argument("--mode",choices=("uniform","review"),default="uniform")
    e=sub.add_parser("evaluate");e.add_argument("--sample",type=Path,required=True);e.add_argument("--labels",type=Path,required=True)
    for sp in (s,e):sp.add_argument("--input",type=Path,required=True);sp.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    read=lambda path:json.loads(path.read_text(encoding="utf-8"))
    d=read(a.input)
    result=sample(d,a.size,a.seed,a.mode) if a.command=="sample" else evaluate(d,read(a.sample),read(a.labels))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("x",encoding="utf-8") as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({"status":result.get("status","unlabeled_sample"),"sample_id":result["sample_id"],
                      "count":len(result["items"]) if "items" in result else result["labeled"]}))
if __name__=="__main__":main()
