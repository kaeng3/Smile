"""Publisher-tagged stock news, selected before clustering to retain its label."""
from news_feed.sources import is_featured_title
from .briefing import briefing
from .news_engine import parse_time,seen_time
from .taxonomy import classify

def featured_editions(rows,day,previous,edition,post_cutoff,session=None):
    tagged=[]
    for r in rows:
        if not isinstance(r,dict):continue
        if is_featured_title(r.get("title")):
            tagged.append(r)
        elif is_featured_title(r.get("featured_title")):
            seen=parse_time(r.get("featured_observed_at"))
            original=parse_time(r.get("observed_at")) or seen_time(r.get("seen"))
            if seen is None or original is None or seen<original:continue
            tagged.append({**r,"title":r["featured_title"],"observed_at":seen.isoformat(),
                           "press":r.get("featured_press") or r.get("press")})
    b=briefing(tagged,day,previous,edition,post_cutoff,limit=None,session=session)
    def order(events,field):
        items=[{**e,"classification":classify(e["headline"],e.get("category",""))} for e in events]
        return sorted(items,key=lambda e:max((a.get(field) or "" for a in e["articles"]),default=""),reverse=True)
    known=order(b["events"],"published_at");unknown=order(b["unknown_events_preview"],"seen_at")
    return {"method":"explicit_publisher_tag_only","events":known,"unknown_events":unknown,
            "article_count":sum(e["article_count"] for e in known+unknown),
            "known_article_count":sum(e["article_count"] for e in known),
            "unknown_article_count":sum(e["article_count"] for e in unknown),
            "note":"Cross-view only; not additive to industry totals. News title labels are not proof of price causation."}
