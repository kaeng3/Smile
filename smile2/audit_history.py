"""Aggregate-only audit of a locally authorized historical JSON file."""
import argparse
import base64
from collections import Counter
from datetime import date
import json
import re
from pathlib import Path

def audit(data):
    if not isinstance(data,dict):
        raise ValueError("Expected stock-code dictionary")
    years, days = Counter(), Counter()
    total=invalid_dates=invalid_codes=duplicates=encoded=invalid_encoding=invalid_rows=0
    for code, rows in data.items():
        if not re.fullmatch(r"[0-9A-Z]{6}",str(code)):
            invalid_codes+=1
        if not isinstance(rows,list):
            invalid_rows+=1
            continue
        seen=set()
        for row in rows:
            if not isinstance(row,dict):
                invalid_rows+=1
                continue
            total+=1
            d=str(row.get("date",""))
            try:
                parsed=date.fromisoformat(d)
                if parsed.isoformat()!=d:
                    raise ValueError()
                years[d[:4]]+=1
                days[d]+=1
            except ValueError:
                invalid_dates+=1
            title=row.get("title")
            if isinstance(title,str):
                key=(d,title)
                if key in seen:
                    duplicates+=1
                seen.add(key)
            if row.get("enc") is True:
                encoded+=1
                for field in ("title","content"):
                    try:
                        base64.b64decode(row.get(field,""),validate=True).decode("utf-8")
                    except (ValueError,TypeError):
                        invalid_encoding+=1
    return {"stock_keys":len(data),"stock_news_rows":total,"years":dict(sorted(years.items())),
            "first_date":min(days,default=None),"last_date":max(days,default=None),
            "distinct_dates":len(days),"duplicate_stock_date_title":duplicates,
            "invalid_dates":invalid_dates,"invalid_codes":invalid_codes,
            "invalid_rows":invalid_rows,"encoded_rows":encoded,"invalid_encoded_fields":invalid_encoding,
            "note":"Stock-linked rows, not unique events; no source text exported."}

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("path",type=Path)
    a=p.parse_args()
    print(json.dumps(audit(json.loads(a.path.read_text(encoding="utf-8"))),ensure_ascii=False,indent=2))
