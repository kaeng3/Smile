"""Strict exchange session resolution. No weekday-only fallback."""
import argparse
from datetime import date,timedelta
import json

def session_window(day):
    import exchange_calendars as xc
    import pandas as pd
    cal=xc.get_calendar("XKRX",start=day-timedelta(days=40),end=day+timedelta(days=2))
    label=pd.Timestamp(day)
    if not cal.is_session(label):
        raise ValueError("Not an XKRX session")
    previous=cal.previous_session(label)
    def fmt(v):
        return v.tz_convert("Asia/Seoul").isoformat()
    return {"day":day.isoformat(),"previous":previous.date().isoformat(),
            "open":fmt(cal.session_open(label)),"close":fmt(cal.session_close(label)),
            "previous_close":fmt(cal.session_close(previous)),
            "calendar":"XKRX"}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--day",required=True,type=date.fromisoformat)
    a=p.parse_args()
    print(json.dumps(session_window(a.day)))
if __name__=="__main__":
    main()
