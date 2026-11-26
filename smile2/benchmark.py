"""Local comparison of an authorized saved reference report against collected links.

Do not upload the reference HTML, its titles, or missing links to public CI.
URL overlap is a lower bound on coverage, not semantic event recall.
"""
import argparse
from collections import Counter
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import urlsplit
from .news_engine import canonical_url

class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=set()
    def handle_starttag(self,tag,attrs):
        if tag!="a":
            return
        u=canonical_url(dict(attrs).get("href"))
        if not u:
            return
        host=(urlsplit(u).hostname or "").lower()
        if host=="thealphahorizon.com" or host.endswith(".thealphahorizon.com"):
            return
        self.links.add(u)

def report_links(html,include_hosts=None):
    p=Links()
    p.feed(html)
    return {u for u in p.links if not include_hosts or
            any(urlsplit(u).hostname==h or urlsplit(u).hostname.endswith("."+h) for h in include_hosts)}

def compare(reference,rows):
    collected={canonical_url(r.get("url")) for r in rows if isinstance(r,dict)}
    collected.discard("")
    matched=reference & collected
    counts=Counter(urlsplit(u).hostname for u in reference)
    hit_counts=Counter(urlsplit(u).hostname for u in matched)
    return {"reference_external_links":len(reference),"collected_unique_links":len(collected),
            "exact_url_matches":len(matched),"exact_url_coverage_pct":round(100*len(matched)/len(reference),2) if reference else None,
            "hosts":[{"host":h,"reference":n,"matched":hit_counts[h]} for h,n in counts.most_common()],
            "note":"Exact URL overlap only. Reference links may include non-news links, portals or historical evidence. Review host filter, time windows and semantic equivalents separately."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--reference",type=Path,required=True)
    p.add_argument("--news",type=Path,required=True)
    p.add_argument("--host",action="append",default=[])
    a=p.parse_args()
    rows=json.loads(a.news.read_text(encoding="utf-8"))
    if not isinstance(rows,list):
        p.error("Expected a news metadata array")
    print(json.dumps(compare(report_links(a.reference.read_text(encoding="utf-8"),a.host),rows),ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
