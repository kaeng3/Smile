"""Verify supplied daily bars against exchange sessions, without filling gaps."""
from datetime import date,timedelta
from functools import lru_cache
def compare_sessions(records,expected):
    actual=[r["day"] for r in records]
    if len(actual)!=len(set(actual)):
        raise ValueError("Duplicate trading dates")
    present=set(actual); needed=set(expected)
    return {"missing":sorted(needed-present),"unexpected":sorted(present-needed)}
@lru_cache(maxsize=128)
def expected_sessions(first,last):
    import exchange_calendars as xc
    import pandas as pd
    a,b=date.fromisoformat(first),date.fromisoformat(last)
    if a>b:
        raise ValueError("Invalid session range")
    cal=xc.get_calendar("XKRX",start=a-timedelta(days=14),end=b+timedelta(days=14))
    return tuple(x.date().isoformat() for x in cal.sessions_in_range(pd.Timestamp(a),pd.Timestamp(b)))
def require_sessions(records):
    if not records:
        raise ValueError("No daily bars")
    r=compare_sessions(records,expected_sessions(records[0]["day"],records[-1]["day"]))
    if r["missing"] or r["unexpected"]:
        raise ValueError("Unverified consecutive sessions: "+str(r))
    return r
