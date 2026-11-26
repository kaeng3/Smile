"""Offline event candidates from the existing feed. No LLM, no network."""
import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

KST = timezone(timedelta(hours=9))
STOP = {"특징주", "단독", "속보", "종합", "급등", "강세", "상승", "하락", "관련주", "주목", "기대"}
EVENTS = {
    "계약": ("공급계약", "수주", "계약 체결"),
    "승인": ("승인", "허가"),
    "신청": ("신청", "접수"),
    "실적": ("영업이익", "매출", "실적"),
    "투자": ("투자", "증설"),
    "정책": ("법안", "금리", "관세", "규제"),
    "임상": ("임상", "임상시험"),
    "인수": ("인수", "합병"),
}
def canonical_url(url):
    try:
        u = urlsplit(str(url or ""))
        if u.scheme not in ("https", "http") or not u.hostname or u.username or u.password:
            return ""
        q = sorted((k,v) for k,v in parse_qsl(u.query, keep_blank_values=True)
                   if not k.lower().startswith("utm_") and k.lower() not in {"ref","fbclid","gclid"})
        return urlunsplit((u.scheme, u.netloc.lower(), u.path, urlencode(q), ""))
    except ValueError:
        return ""

def normalize(title):
    s = unicodedata.normalize("NFKC", str(title or "")).casefold()
    s = re.sub(r"\[(?:특징주|속보|단독|종합)\]", "", s)
    return " ".join(re.findall(r"[가-힣a-z0-9]+", s))

def tokens(title):
    return {t for t in normalize(title).split() if len(t)>1 and t not in STOP}

def event_types(title):
    return {k for k, words in EVENTS.items() if any(w in title for w in words)}

def parse_time(value):
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d.astimezone(KST) if d.tzinfo else None
    except (TypeError, ValueError):
        return None

def seen_time(value):
    try:
        d = datetime.fromisoformat(str(value))
        return d.astimezone(KST) if d.tzinfo else d.replace(tzinfo=KST)
    except (TypeError, ValueError):
        return None

def prepare(row):
    title = str(row.get("title") or "").strip()
    url = canonical_url(row.get("url"))
    if not title or not url:
        return None
    published = parse_time(row.get("published_at"))
    seen = seen_time(row.get("seen"))
    if not (published or seen):
        return None
    stocks = []
    for s in row.get("stocks") or []:
        if isinstance(s,(list,tuple)) and len(s)==2 and re.fullmatch(r"[0-9A-Z]{6}", str(s[1])):
            stocks.append([str(s[0]),str(s[1])])
    score = row.get("score", 0)
    try:
        score = float(score)
        if not (-1e6 < score < 1e6):
            score = 0
    except (ValueError,TypeError):
        score = 0
    return {"title":title,"url":url,"press":str(row.get("press") or urlsplit(url).hostname),
            "published_at":published.isoformat() if published else None,
            "seen_at":seen.isoformat() if seen else None,
            "category":str(row.get("cat") or "기타"),"score":score,
            "stocks":stocks,"themes":[str(t) for t in row.get("themes") or []],
            "event_types":sorted(event_types(title))}

def clock(a):
    return parse_time(a["published_at"]) or parse_time(a["seen_at"])

def similar(a,b):
    if abs((clock(a)-clock(b)).total_seconds())>48*3600:
        return False
    if normalize(a["title"]) == normalize(b["title"]):
        return True
    ta,tb = tokens(a["title"]),tokens(b["title"])
    common = ta & tb
    ea,eb = set(a["event_types"]),set(b["event_types"])
    # Conflicting or unknown event types must not be silently merged.
    if not ea or ea != eb or len(common)<4:
        return False
    if {x for x in ta if any(c.isdigit() for c in x)} != {x for x in tb if any(c.isdigit() for c in x)}:
        return False
    ca,cb = {s[1] for s in a["stocks"]},{s[1] for s in b["stocks"]}
    return (not ca or not cb or bool(ca & cb)) and len(common)/len(ta|tb)>=0.72

def build(rows):
    prepared = [a for row in rows if isinstance(row,dict) if (a:=prepare(row))]
    prepared.sort(key=lambda a:(-a["score"],-clock(a).timestamp(),a["url"]))
    groups, by_url, index = [], {}, defaultdict(set)
    for a in prepared:
        if a["url"] in by_url:
            continue
        ts = tokens(a["title"])
        candidates = set().union(*(index[t] for t in ts)) if ts else set()
        g = next((i for i in sorted(candidates) if similar(a,groups[i][0])),None)
        if g is None:
            g = len(groups)
            groups.append([])
        groups[g].append(a)
        by_url[a["url"]] = g
        for t in ts:
            index[t].add(g)
    result=[]
    for articles in groups:
        lead=articles[0]
        stocks={s[1]:s[0] for a in articles for s in a["stocks"]}
        result.append({"id":hashlib.sha256(lead["url"].encode()).hexdigest()[:20],
                       "headline":lead["title"],"category":lead["category"],
                       "keyword_score":lead["score"],"article_count":len(articles),
                       "source_count":len({a["press"] for a in articles}),
                       "stocks":[{"code":c,"name":n,"relation":"title_mention_unverified"} for c,n in sorted(stocks.items())],
                       "themes":sorted({t for a in articles for t in a["themes"]}),
                       "articles":articles,"status":"candidate_not_verified"})
    return {"schema":1,"method":"conservative_title_clustering_v1",
            "input_count":len(rows),"accepted_count":len(prepared),
            "unique_url_count":len(by_url),"event_count":len(result),
            "missing_published_at":sum(a["published_at"] is None for a in prepared),
            "events":result}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--input",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    rows=json.loads(args.input.read_text(encoding="utf-8"))
    if not isinstance(rows,list):
        p.error("Expected a list of feed articles")
    output=build(rows)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temp=args.output.with_suffix(".tmp")
    temp.write_text(json.dumps(output,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
    temp.replace(args.output)
    print(json.dumps({k:v for k,v in output.items() if k!="events"},ensure_ascii=False))
if __name__=="__main__":
    main()
