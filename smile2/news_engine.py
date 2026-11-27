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
from .contract_identity import contract_identity, compatible_contract

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
    seen = parse_time(row.get("observed_at")) or seen_time(row.get("seen"))
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
    host=urlsplit(url).hostname or ""
    link_kind="aggregator" if host=="news.google.com" or row.get("source_kind")=="media_probe_aggregator" else "portal" if host in ("n.news.naver.com","news.naver.com","v.daum.net","news.daum.net") else "source_url"
    return {"title":title,"url":url,"link_kind":link_kind,"press":str(row.get("press") or urlsplit(url).hostname),
            "source_feed":str(row.get("source_feed") or ""),
            "source_kind":str(row.get("source_kind") or "news_metadata"),
            "published_at":published.isoformat() if published else None,
            "seen_at":seen.isoformat() if seen else None,
            "category":str(row.get("cat") or "기타"),"score":score,
            "stocks":stocks,"themes":[str(t) for t in row.get("themes") or []],
            "event_types":sorted(event_types(title)),
            "retention_reasons":[v for v in (row.get("retention_reasons") or []) if v in ("corporate","biotech","market","policy")]}

def clock(a):
    return parse_time(a["published_at"]) or parse_time(a["seen_at"])

def signature(text):
    return re.findall(r"[+-]?\d[\d,.]*(?:%|억원|억|조원|조|만|원|달러)?",text)

def stage(text):
    return {x for x in ("검토","추진","신청","승인","허가","부인","철회","취소","완료","중단","예정","반려","체결","증가","감소","상승","하락","흑자전환","적자전환") if x in text}

def similar(a,b):
    if abs((clock(a)-clock(b)).total_seconds())>48*3600:
        return False
    if compatible_contract(a,b):
        return True
    if signature(a["title"]) != signature(b["title"]) or stage(a["title"]) != stage(b["title"]):
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

def stock_evidence(articles):
    links={}
    for a in articles:
        # DART adapter supplies the filing issuer's stock code. This is not proof of benefit.
        u=urlsplit(a["url"])
        is_filing=(a.get("source_kind")=="official_disclosure" and a.get("source_feed")=="DART"
                   and u.scheme=="https" and u.hostname=="dart.fss.or.kr"
                   and u.path=="/dsaf001/main.do"
                   and bool(re.fullmatch(r"\d{14}",dict(parse_qsl(u.query)).get("rcpNo",""))))
        for name,code in a["stocks"]:
            row=links.setdefault(code,{"code":code,"name":name,"relation":"title_mention_unverified","evidence":[]})
            relation="official_filing_issuer" if is_filing else "title_mention_unverified"
            if is_filing:
                row["name"]=name
                row["relation"]=relation
            row["evidence"].append({"url":a["url"],"relation":relation})
    return [links[c] for c in sorted(links)]

def build(rows):
    prepared = [a for row in rows if isinstance(row,dict) if (a:=prepare(row))]
    prepared.sort(key=lambda a:(-a["score"],-clock(a).timestamp(),a["url"]))
    groups, by_url, index = [], {}, defaultdict(set)
    contract_index=defaultdict(set)
    for a in prepared:
        if a["url"] in by_url:
            continue
        ts = tokens(a["title"])
        candidates = set().union(*(index[t] for t in ts)) if ts else set()
        key=contract_identity(a)
        if key:candidates.update(contract_index[key])
        # Complete-link comparison prevents a bridge headline from joining incompatible contracts.
        g = next((i for i in sorted(candidates) if all(similar(a,x) for x in groups[i])),None)
        if g is None:
            g = len(groups)
            groups.append([])
        groups[g].append(a)
        by_url[a["url"]] = g
        if key:contract_index[key].add(g)
        for t in ts:
            index[t].add(g)
    result=[]
    for articles in groups:
        lead=articles[0]
        stocks=stock_evidence(articles)
        result.append({"id":hashlib.sha256(lead["url"].encode()).hexdigest()[:20],
                       "headline":lead["title"],"category":lead["category"],
                       "keyword_score":lead["score"],"article_count":len(articles),
                       "source_count":len({a["press"] for a in articles}),
                       "stocks":stocks,
                       "themes":sorted({t for a in articles for t in a["themes"]}),
                       "articles":articles,"status":"candidate_not_verified"})
    return {"schema":1,"method":"conservative_title_clustering_v2_contract_anchor",
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
