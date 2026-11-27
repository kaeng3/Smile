"""Read-only Pages integration. Build from already collected public metadata."""
from datetime import datetime,timedelta
import json
from pathlib import Path
import shutil
import tempfile
from .news_engine import KST,parse_time
from .pipeline import generate,read_rows,ASSETS
from .calendar import session_window

def latest_session(now):
    import exchange_calendars as xc
    import pandas as pd
    day=now.astimezone(KST).date()
    cal=xc.get_calendar("XKRX",start=day-timedelta(days=60),end=day+timedelta(days=2))
    label=cal.date_to_session(pd.Timestamp(day),direction="previous")
    return session_window(label.date())

def release(root,now=None,session=None):
    """Only change the generated site's smile2 subdirectory, never source or data."""
    from datetime import date
    root=Path(root).resolve()
    news=root/"news_feed"/"news.json"
    if not news.is_file():
        raise FileNotFoundError("No existing public news metadata")
    now=now or datetime.now(KST)
    s=session or latest_session(now)
    day,prev=date.fromisoformat(s["day"]),date.fromisoformat(s["previous"])
    target=root/"smile2"
    if target.is_symlink():
        raise ValueError("Unexpected symlink")
    with tempfile.TemporaryDirectory(prefix="smile-release-",dir=root.parent) as tmp:
        output=Path(tmp)/"site"
        extra=root/"news_feed"/"smile2-official.json"
        official=json.loads(extra.read_text(encoding="utf-8")) if extra.is_file() else {}
        market=root/"daily_issues.json"
        observations=json.loads(market.read_text(encoding="utf-8")) if market.is_file() else {}
        stats_path=root/"news_feed"/"keyword_stats.json"
        try:
            stats=json.loads(stats_path.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            stats=None
        result=generate(read_rows(news),day,prev,output,session=s,capture_stats=stats,
                        official_rows=official.get("rows",[]),source_status=official.get("sources",[]),
                        market_data=observations,market_available=now>=parse_time(s["close"]))
        # Stage before changing the generated site, and restore on failure.
        backup=Path(tmp)/"previous"
        if target.exists():
            target.rename(backup)
        try:
            output.rename(target)
        except OSError:
            if backup.exists():
                backup.rename(target)
            raise
    return result

def fallback(root):
    """Keep legacy site available; publish only a clear unavailable notice."""
    root=Path(root).resolve()
    target=root/"smile2"
    if target.is_symlink():
        raise ValueError("Unexpected symlink")
    if target.exists():
        shutil.rmtree(target)
    target.mkdir()
    (target/"index.html").write_text(
        '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>SMILE 2.0</title><h1>뉴스 연구 화면 일시 준비 중</h1><p>최신 데이터 생성 또는 거래일 검증에 실패했습니다. 기존 홈페이지는 이용할 수 있습니다.</p>'
        '<p><a href="../">기존 홈페이지</a></p></html>',encoding="utf-8")

def add_entry(root):
    """Add an ordinary link in the existing generated header, preserving its code."""
    p=Path(root)/"index.html"
    if not p.is_file():
        return
    html=p.read_text(encoding="utf-8")
    marker='id="smile2-entry"'
    if marker in html:
        return
    link='<p id="smile2-entry" style="margin:12px 0"><a href="./smile2/" style="display:inline-block;padding:10px 16px;border:1px solid currentColor;border-radius:8px;font-weight:700;color:inherit">SMILE 2.0 뉴스 연구실 ↗</a></p>'
    if "</header>" not in html:
        raise ValueError("Legacy header missing")
    p.write_text(html.replace("</header>",link+"</header>",1),encoding="utf-8")
