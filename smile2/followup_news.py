"""Separate latest-session followup view, without rewriting as-of editions."""
from .briefing import bounds
from .news_engine import build,parse_time,seen_time,canonical_url
from .taxonomy import group
from .material_stage import annotate_sections
from .editorial_evidence import annotate_sections as evidence_sections
from news_feed.sources import is_featured_title

def followup(rows,day,previous,as_of,post_cutoff,session=None):
    start,pre_end=bounds(day,previous,"pre",post_cutoff,session)
    post_start,end=bounds(day,previous,"post",post_cutoff,session)
    known=[];unknown=[];why={}
    for r in rows:
        seen=parse_time(r.get("observed_at")) or seen_time(r.get("seen"))
        pub=parse_time(r.get("published_at"))
        verified=parse_time(r.get("publication_verified_at"))
        tagged=parse_time(r.get("featured_observed_at"))
        if not seen or seen>as_of or (pub and pub>seen):continue
        if verified and verified>as_of:
            pub=None
        reasons=[]
        if pub and start<=pub<pre_end and seen>=pre_end:reasons.append("late_pre")
        if pub and post_start<=pub<end and seen>=end:reasons.append("late_post")
        if pre_end<=(pub or seen)<post_start:reasons.append("morning_gap")
        if (pub and pub>=end) or (pub is None and seen>=end):reasons.append("after_cutoff")
        relevant=pub is not None and (start<=pub<pre_end or post_start<=pub<end)
        cutoff=pre_end if pub and pub<pre_end else end
        if relevant and verified and cutoff<=verified<=as_of:reasons.append("late_timestamp")
        late_tag=(relevant and tagged and cutoff<=tagged<=as_of and tagged>=seen and is_featured_title(r.get("featured_title")))
        if late_tag:reasons.append("late_featured")
        if not reasons:continue
        a={**r,"published_at":pub.isoformat() if pub else None}
        if late_tag:
            a["title"]=r["featured_title"];a["observed_at"]=tagged.isoformat()
            a["press"]=r.get("featured_press") or r.get("press")
        url=canonical_url(a.get("url"))
        if not url:continue
        why.setdefault(url,set()).update(reasons)
        (known if pub else unknown).append(a)
    def sections(rows):
        es=build(rows)["events"]
        for e in es:
            e["followup_reasons"]=sorted({reason for a in e["articles"] for reason in why.get(a["url"],())})
        return evidence_sections(annotate_sections(group(es)))
    ks,us=sections(known),sections(unknown)
    return {"schema":1,"report_date":day.isoformat(),"as_of":as_of.isoformat(),"sections":ks,"unknown_sections":us,
            "event_count":sum(s["count"] for s in ks+us),
            "note":"Supplemental observations only; not additive to frozen editions. Future next-session pre may overlap."}
