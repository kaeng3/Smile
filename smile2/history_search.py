"""Local-only search of the user's authorized history. No web server or upload."""
import argparse
import base64
from datetime import date
import json
from pathlib import Path
import re
import unicodedata

def norm(s):
    return unicodedata.normalize("NFKC", str(s)).casefold()

def decode(row, field):
    value=row.get(field,"")
    if not isinstance(value,str):
        return ""
    if row.get("enc") is True:
        try:
            return base64.b64decode(value,validate=True).decode("utf-8")
        except (ValueError,TypeError):
            return ""
    return value

def search(data, query="", code=None, start=None, end=None, limit=30):
    if not isinstance(data,dict):
        raise ValueError("Expected stock-keyed JSON")
    if code is not None and not re.fullmatch(r"[0-9A-Z]{6}",code):
        raise ValueError("Invalid stock code")
    if not 1<=limit<=500 or (start and end and start>end):
        raise ValueError("Invalid search range or limit")
    terms=norm(query).split()
    if not terms and not code:
        raise ValueError("Provide a query or stock code")
    hits=[]
    for c,rows in data.items():
        if code and c!=code:
            continue
        if not isinstance(rows,list):
            continue
        for row in rows:
            if not isinstance(row,dict):
                continue
            try:
                d=date.fromisoformat(row.get("date",""))
            except (ValueError,TypeError):
                continue
            if (start and d<start) or (end and d>end):
                continue
            name=str(row.get("stock_name",""))
            category=str(row.get("category",""))
            # Match within an authorized local file, without emitting excerpts.
            hay=norm(" ".join([c,name,category,decode(row,"title"),decode(row,"content")]))
            if all(t in hay for t in terms):
                hits.append({"date":d.isoformat(),"code":c,"stock_name":name,
                             "category":category,"rate":row.get("rate"),
                             "title":decode(row,"title")})
    hits.sort(key=lambda h:(h["date"],h["code"]),reverse=True)
    return {"total_matches":len(hits),"matches":hits[:limit]}

def main():
    p=argparse.ArgumentParser(description="Local-only authorized history lookup; default output is aggregate counts")
    p.add_argument("path",type=Path)
    p.add_argument("--query",default="")
    p.add_argument("--code")
    p.add_argument("--start",type=date.fromisoformat)
    p.add_argument("--end",type=date.fromisoformat)
    p.add_argument("--limit",type=int,default=30)
    p.add_argument("--local-details",action="store_true",help="Print local result titles; do not use in public CI")
    a=p.parse_args()
    result=search(json.loads(a.path.read_text(encoding="utf-8")),a.query,a.code,a.start,a.end,a.limit)
    if not a.local_details:
        result={"total_matches":result["total_matches"],"returned_count":len(result["matches"])}
    print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
