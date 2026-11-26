"""Independent official-source collection; no paid data, no automatic production publishing."""
import argparse
from datetime import datetime, date
import json
import os
from pathlib import Path
import re
import urllib.request
from urllib.parse import urlencode, urljoin
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from .news_engine import KST, canonical_url

FEEDS = {
    "한국은행 통화정책": ("https://www.bok.or.kr/portal/bbs/P0000559/news.rss?menuNo=200690","경제 일반"),
    "한국은행 금통위 의결": ("https://www.bok.or.kr/portal/bbs/P0000093/news.rss?menuNo=200761","경제 일반"),
    "금융위원회 보도자료": ("https://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111","정부 정책"),
    "금융위원회 보도설명": ("https://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0112","정부 정책"),
    "미 연준 보도자료": ("https://www.federalreserve.gov/feeds/press_all.xml","국제 - 미국"),
    "미 연준 통화정책": ("https://www.federalreserve.gov/feeds/press_monetary.xml","국제 - 미국"),
}
MAX_BYTES=4*1024*1024
def get(url):
    req=urllib.request.Request(url,headers={"User-Agent":"SmileResearch/2.0 (official public RSS reader)","Accept":"application/xml, application/rss+xml, application/json"})
    with urllib.request.urlopen(req,timeout=12) as r:
        data=r.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:
            raise ValueError("Response size limit")
        return data

def local(tag):
    return tag.rsplit("}",1)[-1]

def publication(raw):
    if not raw:
        return None
    try:
        d=parsedate_to_datetime(raw)
    except (ValueError,TypeError,OverflowError):
        try:
            d=datetime.fromisoformat(raw.replace("Z","+00:00"))
        except (ValueError,TypeError,OverflowError):
            return None
    return d.astimezone(KST).isoformat() if d and d.tzinfo else None

def parse_feed(raw,name,base,category,observed):
    if re.search(br"<!\s*(DOCTYPE|ENTITY)\b",raw,re.I):
        raise ValueError("DTD not allowed")
    root=ET.fromstring(raw)
    if local(root.tag) not in ("rss","feed","RDF"):
        raise ValueError("Not a recognized feed")
    rows=[]
    for node in root.iter():
        if local(node.tag) not in ("item","entry"):
            continue
        children={local(x.tag):x for x in node}
        title=children.get("title")
        if title is None:
            continue
        title=" ".join("".join(title.itertext()).split())
        link=""
        for x in node:
            if local(x.tag)=="link" and x.attrib.get("rel","alternate")=="alternate":
                link=x.attrib.get("href") or x.text or ""
                break
        if not link.strip():
            continue
        link=canonical_url(urljoin(base,link.strip()))
        if not title or not link:
            continue
        raw_date=next((children[k].text for k in ("pubDate","published") if k in children),None)
        rows.append({"title":title,"url":link,"press":name,"source_feed":name,"source_kind":"official_rss",
                     "cat":category,"score":6,"stocks":[],"themes":[],"published_at":publication(raw_date),
                     "observed_at":observed.isoformat(),"seen":observed.strftime("%Y-%m-%d %H:%M")})
    return rows

def collect():
    rows=[]; status=[]
    for name,(url,cat) in FEEDS.items():
        try:
            raw=get(url)
            entries=parse_feed(raw,name,url,cat,datetime.now(KST))
            rows.extend(entries)
            status.append({"source":name,"status":"ok" if entries else "empty","count":len(entries)})
        except Exception as e:
            status.append({"source":name,"status":"failed","error_type":type(e).__name__})
    return rows,status

def dart_rows(payload,observed):
    if payload.get("status")=="013":
        return []
    if payload.get("status")!="000":
        raise ValueError("DART status "+str(payload.get("status")))
    out=[]
    for x in payload.get("list",[]):
        receipt=str(x.get("rcept_no",""))
        if not re.fullmatch(r"\d{14}",receipt):
            continue
        code=str(x.get("stock_code",""))
        name=str(x.get("corp_name",""))
        title=str(x.get("report_nm",""))
        if not title or not name:
            continue
        out.append({"title":name+" "+title,"url":"https://dart.fss.or.kr/dsaf001/main.do?rcpNo="+receipt,
                    "press":"DART","source_feed":"DART","source_kind":"official_disclosure","cat":"M&A / 공시",
                    "score":6,"stocks":[[name,code]] if re.fullmatch(r"[0-9A-Z]{6}",code) else [],
                    "themes":[],"receipt_date":x.get("rcept_dt"),"published_at":None,
                    "observed_at":observed.isoformat(),"seen":observed.strftime("%Y-%m-%d %H:%M")})
    return out

def collect_dart(day,key):
    rows=[]
    for page in range(1,21):
        q=urlencode({"crtfc_key":key,"bgn_de":day.strftime("%Y%m%d"),"end_de":day.strftime("%Y%m%d"),
                     "page_no":page,"page_count":100})
        try:
            payload=json.loads(get("https://opendart.fss.or.kr/api/list.json?"+q))
        except Exception:
            # Never echo credential-bearing URL or exception details.
            raise RuntimeError("DART request failed") from None
        rows.extend(dart_rows(payload,datetime.now(KST)))
        if page>=int(payload.get("total_page",1)):
            return rows
    raise RuntimeError("DART page cap exceeded; incomplete result")

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--dart-day",type=date.fromisoformat)
    a=p.parse_args()
    rows,status=collect()
    if a.dart_day:
        key=os.environ.get("DART_API_KEY")
        if not key:
            status.append({"source":"DART","status":"not_configured"})
        else:
            try:
                d=collect_dart(a.dart_day,key)
                rows.extend(d);status.append({"source":"DART","status":"ok","count":len(d)})
            except Exception:
                status.append({"source":"DART","status":"failed"})
    a.output.parent.mkdir(parents=True,exist_ok=True)
    tmp=a.output.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows,ensure_ascii=False),encoding="utf-8")
    tmp.replace(a.output)
    print(json.dumps({"rows":len(rows),"sources":status},ensure_ascii=False))
if __name__=="__main__":
    main()
