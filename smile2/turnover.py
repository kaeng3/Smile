"""Read-only KIS provider cache audit. No broker requests or credentials.

The provider maps acml_tr_pbmn to trading_value. Cache metadata does not prove
regular-session scope; never relabel it as KRX regular-session data.
"""
import argparse
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import gzip
import json
from pathlib import Path
import re

CODE=re.compile(r"[0-9A-Z]{6}")
FIELDS=("open","high","low","close","volume","trading_value")

def decimal(v):
    try:
        d=Decimal(str(v))
        if not d.is_finite():
            raise ValueError("nonfinite")
        return d
    except (InvalidOperation,TypeError) as e:
        raise ValueError("invalid numeric field") from e

def validate_row(row,day,meta):
    if meta.get("adjusted") is not False:
        raise ValueError("raw price basis required")
    if date.fromisoformat(meta["covered_end"])<day:
        raise ValueError("cache not complete through requested date")
    if date.fromisoformat(meta["requested_start"])>day:
        raise ValueError("requested date outside cache coverage")
    if str(row["date"])[:10]!=day.isoformat():
        raise ValueError("wrong session date")
    v={k:decimal(row[k]) for k in FIELDS}
    if not 0<v["low"]<=min(v["open"],v["close"])<=max(v["open"],v["close"])<=v["high"]:
        raise ValueError("invalid OHLC")
    if v["volume"]<=0 or v["trading_value"]<=0:
        raise ValueError("missing or zero reported turnover")
    if any(v[k]!=v[k].to_integral_value() for k in ("volume","trading_value")):
        raise ValueError("noninteger volume or KRW turnover")
    # A raw same-scope OHLC and volume imply the volume-weighted average
    # price lies within the trading range. Reject rather than substitute.
    if not v["low"]*v["volume"]<=v["trading_value"]<=v["high"]*v["volume"]:
        raise ValueError("reported value outside OHLC/volume bounds")
    return {"day":day.isoformat(),"reported_value_won":int(v["trading_value"]),
            "estimated_close_times_volume_won":str(v["close"]*v["volume"]),
            "volume":int(v["volume"]),"basis":"KIS_cache_acml_tr_pbmn",
            "price_basis":"raw","session_scope":"unverified"}

def read_rows(path):
    if path.name.endswith(".csv.gz"):
        with gzip.open(path,"rt",encoding="utf-8",newline="") as f:
            yield from csv.DictReader(f)
    elif path.suffix==".parquet":
        import pandas as pd
        yield from pd.read_parquet(path,columns=["date",*FIELDS]).to_dict("records")
    else:
        raise ValueError("unsupported cache format")

def lookup(cache,code,day):
    if not CODE.fullmatch(code):
        raise ValueError("invalid stock code")
    daily=Path(cache)/"daily"
    meta_path=daily/(code+".meta.json")
    paths=[daily/(code+ext) for ext in (".csv.gz",".parquet")]
    present=[p for p in paths if p.is_file()]
    if len(present)!=1 or not meta_path.is_file():
        raise ValueError("missing or ambiguous cache pair")
    if meta_path.is_symlink() or present[0].is_symlink():
        raise ValueError("symlink rejected")
    meta=json.loads(meta_path.read_text(encoding="utf-8"))
    if meta.get("adjusted") is not False:
        raise ValueError("raw price basis required")
    rows=[r for r in read_rows(present[0]) if str(r.get("date",""))[:10]==day.isoformat()]
    if len(rows)!=1:
        raise ValueError("missing or duplicate session")
    return {"code":code,**validate_row(rows[0],day,meta)}

def audit(cache,day):
    from collections import Counter
    daily=Path(cache)/"daily"
    codes=sorted({p.name[:-10] for p in daily.glob("*.meta.json") if CODE.fullmatch(p.name[:-10])})
    ok=0;reasons=Counter()
    for code in codes:
        try:
            lookup(cache,code,day);ok+=1
        except (ValueError,KeyError,TypeError,OSError,ImportError) as e:
            # Only safe aggregate categories, no cache contents or paths.
            reason=str(e) if type(e) is ValueError and str(e) in {
                "raw price basis required","cache not complete through requested date",
                "requested date outside cache coverage","missing or zero reported turnover",
                "reported value outside OHLC/volume bounds","missing or duplicate session",
                "missing or ambiguous cache pair","symlink rejected"} else type(e).__name__
            reasons[reason]+=1
    return {"date":day.isoformat(),"cache_pairs":len(codes),"usable_reported_values":ok,
            "rejected":dict(reasons),"session_scope":"unverified",
            "note":"No real API requests; not a regular-session qualification."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--cache-dir",type=Path,required=True)
    p.add_argument("--day",type=date.fromisoformat,required=True)
    p.add_argument("--code",help="Optional local single-stock inspection")
    a=p.parse_args()
    print(json.dumps(lookup(a.cache_dir,a.code,a.day) if a.code else audit(a.cache_dir,a.day),ensure_ascii=False,indent=2))
if __name__=="__main__":
    main()
