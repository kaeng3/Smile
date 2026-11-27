"""Publisher-tagged stock news, selected before clustering to retain its label."""
from news_feed.sources import is_featured_title
from .briefing import briefing
from .taxonomy import classify

def featured_editions(rows,day,previous,edition,post_cutoff,session=None):
    tagged=[r for r in rows if isinstance(r,dict) and is_featured_title(r.get("title"))]
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
