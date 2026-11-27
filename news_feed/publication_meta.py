"""Bounded, public article publication metadata recovery. Never infer from URL/collection time."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit
from urllib.request import Request,build_opener,HTTPRedirectHandler
from urllib.error import HTTPError
import json
from collections import Counter

KST=timezone(timedelta(hours=9))
MAX_BYTES=1024*1024
HOSTS={"n.news.naver.com","news.naver.com","v.daum.net","www.mk.co.kr","www.infostockdaily.co.kr",
       "news.einfomax.co.kr","www.bloter.net","www.thelec.kr","it.chosun.com","www.electimes.com",
       "www.thebionews.net","www.hitnews.co.kr","www.biotimes.co.kr","www.pharmnews.com","news.mt.co.kr","www.mt.co.kr"}
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def parse(value):
    try:
        d=datetime.fromisoformat(str(value).replace("Z","+00:00"))
        return d.astimezone(KST) if d.tzinfo else None
    except (ValueError,TypeError,OverflowError):return None

class Metadata(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True);self.dates=[];self.parts=[];self.ld=False
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=="meta" and (a.get("property") or a.get("name") or a.get("itemprop") or "").lower() in {"article:published_time","datepublished","og:article:published_time"}:
            self.dates.append(a.get("content"))
        if tag=="script" and a.get("type","").lower()=="application/ld+json":self.ld=True;self.parts=[]
    def handle_data(self,data):
        if self.ld:self.parts.append(data)
    def handle_endtag(self,tag):
        if tag!="script" or not self.ld:return
        self.ld=False
        try: obj=json.loads("".join(self.parts))
        except (ValueError,RecursionError):return
        # Only NewsArticle/Article top-level objects and @graph entries, not related stories.
        for item in obj if isinstance(obj,list) else [obj]:
            if not isinstance(item,dict):continue
            graph=item.get("@graph",[])
            for node in [item]+(graph if isinstance(graph,list) else []):
                if not isinstance(node,dict):continue
                types=node.get("@type",[])
                if isinstance(types,str):types=[types]
                if isinstance(types,list) and any(t in {"NewsArticle","Article","ReportageNewsArticle","AnalysisNewsArticle"} for t in types):
                    self.dates.append(node.get("datePublished"))
    def result(self):
        values={d for v in self.dates if (d:=parse(v))}
        if not values:return None
        # Multiple inconsistent publication values: abstain.
        return next(iter(values)) if len(values)==1 else None

def fetch_publication(url):
    try:
        u=urlsplit(url)
        if u.scheme!="https" or u.hostname not in HOSTS or u.username or u.password or u.port not in (None,443):return None,"unsupported"
        req=Request(url,headers={"User-Agent":"SmileResearch/3.0 (public metadata)","Accept":"text/html"})
        with build_opener(NoRedirect()).open(req,timeout=5) as res:
            if "text/html" not in res.headers.get("Content-Type","").lower():return None,"unsupported_content"
            raw=res.read(MAX_BYTES)
            enc=res.headers.get_content_charset() or "utf-8"
        parser=Metadata();parser.feed(raw.decode(enc,errors="replace"))
        return parser.result(),"metadata"
    except HTTPError as e:return None,"http_"+str(e.code)
    except Exception:return None,"fetch_failed"

def enrich_publication(rows,fetch=fetch_publication,now=None,limit=60,per_host=6):
    fixed_now=now
    now=now or datetime.now(KST)
    candidates=[];counts=Counter()
    for row in rows:
        if row.get("published_at"):continue
        try:host=urlsplit(row.get("url","")).hostname
        except ValueError:continue
        if host not in HOSTS:continue
        checked=parse(row.get("publication_check_at"))
        if checked and now-checked<timedelta(hours=12):continue
        seen=parse(row.get("observed_at"))
        if not seen:
            try:seen=datetime.fromisoformat(row["seen"]).replace(tzinfo=KST)
            except (KeyError,ValueError,TypeError):continue
        if seen>now or now-seen>timedelta(days=5):continue
        if counts[host]>=per_host:continue
        candidates.append((row,seen));counts[host]+=1
        if len(candidates)>=limit:break
    # At most four hosts at once, each host sequential; stop on explicit access denial or throttling.
    by_host={}
    for row,seen in candidates:by_host.setdefault(urlsplit(row["url"]).hostname,[]).append((row,seen))
    def run_host(items):
        out=[]
        for row,seen in items:
            stamp,status=fetch(row["url"])
            checked_at=fixed_now or datetime.now(KST)
            row["publication_check_at"]=checked_at.isoformat()
            if stamp and stamp<=seen:
                row["published_at"]=stamp.isoformat();row["publication_basis"]="article_published_metadata"
                row["publication_verified_at"]=checked_at.isoformat()
                out.append("recovered")
            else:out.append("conflict_or_after_seen" if stamp else status)
            if status in ("http_403","http_429","http_503"):break
        return out
    with ThreadPoolExecutor(max_workers=4) as pool:
        result=Counter(x for batch in pool.map(run_host,by_host.values()) for x in batch)
    return {"enabled":True,"attempted":sum(result.values()),"recovered":result.get("recovered",0),"outcomes":dict(result)}
