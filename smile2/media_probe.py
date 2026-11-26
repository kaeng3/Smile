"""Opt-in coverage probe; public RSS metadata only, not a production collector.

Aggregated Google News links are not resolved or represented as publisher URLs.
A blocked feed is reported and is not bypassed. Review publisher terms before
enabling these sources outside personal research.
"""
import argparse
from datetime import datetime
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.error import HTTPError
from .news_engine import KST, canonical_url
from .official_feeds import get,parse_feed

def google_site(domain):
    return "https://news.google.com/rss/search?"+urlencode({"q":"site:"+domain+" when:2d","hl":"ko","gl":"KR","ceid":"KR:ko"})

FEEDS={
    "CNBC 주요 뉴스":("https://www.cnbc.com/id/100003114/device/rss/rss.html","direct","국제 - 미국"),
    "CNBC 세계 뉴스":("https://www.cnbc.com/id/100727362/device/rss/rss.html","direct","국제 - 미국"),
    "CNBC 기업 뉴스":("https://www.cnbc.com/id/10001147/device/rss/rss.html","direct","국제 - 미국"),
    "뉴스핌":(google_site("newspim.com"),"aggregator","기타"),
    "와이드데일리":(google_site("widedaily.com"),"aggregator","기타"),
    "뉴스웨이":(google_site("newsway.co.kr"),"aggregator","기타"),
    "데이터투자":(google_site("datatooza.com"),"aggregator","기타"),
    "파이낸셜포스트":(google_site("financialpost.co.kr"),"aggregator","기타"),
}

def probe():
    status=[]; rows=[]
    for name,(url,kind,category) in FEEDS.items():
        try:
            found=parse_feed(get(url),name,url,category,datetime.now(KST))
            for r in found:
                r["source_kind"]="media_probe_"+kind
                r["score"]=0  # no claim of relevance and no Korean-dictionary scoring
                r["source_feed"]=name
            rows.extend(found)
            status.append({"source":name,"link_kind":kind,"status":"ok" if found else "empty","count":len(found),
                           "published_count":sum(bool(r["published_at"]) for r in found)})
        except HTTPError as e:
            status.append({"source":name,"link_kind":kind,"status":"failed","http_status":e.code})
        except Exception as e:
            status.append({"source":name,"link_kind":kind,"status":"failed","error_type":type(e).__name__})
    return {"sources":status,"rows":len(rows),"unique_links":len({canonical_url(r["url"]) for r in rows}),
            "note":"Trial metadata only; aggregator URLs are not publisher URLs; no measured semantic recall."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--output",type=Path)
    a=p.parse_args()
    result=probe()
    if a.output:
        with a.output.open("x",encoding="utf-8") as f:
            json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False))
if __name__=="__main__":
    main()
