"""Evidence provenance and review triage, not source truth or investment ranking."""
from urllib.parse import urlsplit,parse_qs
import re
from .official_feeds import FEEDS
from .taxonomy import classify
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
