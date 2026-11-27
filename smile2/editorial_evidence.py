"""Evidence provenance and review triage, not source truth or investment ranking."""
from urllib.parse import urlsplit,parse_qs
import re
from .official_feeds import FEEDS
from .taxonomy import classify
from .news_engine import normalize, parse_time
from .material_stage import material_stage

OFFICIAL_HOSTS={name:urlsplit(url).hostname for name,(url,_) in FEEDS.items()}

def official_link(a):
    u=urlsplit(a.get("url") or "")
    if u.scheme!="https" or not u.hostname or u.username or u.password:
        return False
    if a.get("source_kind")=="official_rss":
        return OFFICIAL_HOSTS.get(a.get("source_feed"))==u.hostname
    if a.get("source_kind")=="official_disclosure" and a.get("source_feed")=="DART":
        return (u.hostname=="dart.fss.or.kr" and u.path=="/dsaf001/main.do"
                and bool(re.fullmatch(r"\d{14}",parse_qs(u.query).get("rcpNo",[""])[0])))
    return False

def evidence_review(e):
    articles=e.get("articles",[])
    official=[a["url"] for a in articles if official_link(a)]
    c=e.get("classification") or classify(e["headline"],e.get("category",""))
    m=e.get("material_stage") or material_stage(e)
    keys={s["id"] for s in m["signals"]}
    caution=bool(keys & {"denial","negative","risk"} or m["mixed_stage_cues"])
    material=bool(keys & {"contract","approval","completed","application","clinical","preliminary","rumor","plan"})
    reasons=[]
    if caution:reasons.append("caution")
    if official:reasons.append("official_link")
    if material:reasons.append("material_cue")
    if c["review_required"]:reasons.append("classification_review")
    if any(not a.get("published_at") for a in articles):reasons.append("publication_unknown")
    # No numerical confidence, impact score or automatic trading instruction.
    return {"schema":1,"status":"unverified","evidence_type":"title_only",
            "official_urls":sorted(set(official)),
            "source_link_count":sum(a.get("link_kind")=="source_url" for a in articles),
            "portal_link_count":sum(a.get("link_kind")=="portal" for a in articles),
            "aggregator_link_count":sum(a.get("link_kind")=="aggregator" for a in articles),
            "publisher_count":len({a.get("press") for a in articles if a.get("press")}),
            "independent_confirmation":"not_assessed","body_checked":False,
            "review_reasons":reasons,
            "note":"Official link origin is checked against configured source metadata, not article content. Publisher counts do not establish independence."}

def annotate_event(e):
    return {**e,"evidence_review":evidence_review(e)}

def annotate_sections(sections):
    return [{**s,"events":[annotate_event(e) for e in s["events"]]} for s in sections]

def premarket_signals(sections):
    """Editorial shortlist from observable source and timing signals."""
    eligible=[]
    for section in sections:
        for event in section["events"]:
            coverage={}
            titles=set()
            articles=event.get("articles",[])
            times=[stamp for article in articles if (stamp:=parse_time(article.get("published_at")))]
            if not times:
                continue
            first=min(times)
            official=any(official_link(article) for article in articles)
            for article in sorted(articles,key=lambda item:item.get("published_at") or ""):
                stamp=parse_time(article.get("published_at"))
                if not stamp or (stamp-first).total_seconds()>3600 or article.get("link_kind")!="source_url":
                    continue
                publisher=normalize(article.get("press"))
                host=urlsplit(article.get("url") or "").hostname
                title=normalize(article.get("title"))
                if not publisher or not host or not title or title in titles:
                    continue
                if publisher in coverage or host in coverage.values():
                    continue
                coverage[publisher]=host
                titles.add(title)
            # Keep material single-source candidates, explicitly unverified.
            material="material_cue" in event.get("evidence_review",{}).get("review_reasons",[])
            confirmed_signal=official or len(coverage)>=2
            if not confirmed_signal and not (material and coverage):
                continue
            evidence={"official":official,"sources_in_first_hour":len(coverage),
                      "single_source_candidate":not confirmed_signal}
            key=(-int(official),-int(confirmed_signal),-len(coverage),-event.get("keyword_score",0),-first.timestamp(),event["id"])
            eligible.append((key,section["id"],{**event,"premarket_signal":evidence}))
    picked={section["id"]:[] for section in sections}
    for _, category, event in sorted(eligible,key=lambda candidate:candidate[0]):
        if len(picked[category])<7:
            picked[category].append(event)
    return [{**section,"events":picked[section["id"]],"count":len(picked[section["id"]])}
            for section in sections]
