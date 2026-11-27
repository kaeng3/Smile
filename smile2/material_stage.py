"""Explicit title cues for editorial review, never verified event states or trade signals."""
from .taxonomy import normalized,hits
RULES=(
 ("rumor","설·미확정 보도",("인수설","매각설","투자설","수주설","가능성","관측","소문","미확정","확정되지")),
 ("denial","부인·해명",("사실무근","부인","해명","오보","아니다","없다")),
 ("negative","철회·취소·중단",("철회","취소","계약 해지","계약해지","해지","중단","반려","불허","미승인","승인 거부")),
 ("plan","검토·계획",("검토","추진","계획","예정","협상","논의","목표","전망")),
 ("application","신청·접수",("신청","접수","제출")),
 ("preliminary","잠정·추정",("잠정","추정","예비","전망치")),
 ("contract","계약 체결 표현",("공급계약 체결","계약 체결","계약체결","수주 확정","본계약 체결")),
 ("approval","승인·허가 표현",("승인","허가","법안 통과","허가 획득")),
 ("completed","완료·시행 표현",("완료","시행","집행","인수 완료","상용화")),
 ("clinical","임상 진행 단서",("임상","임상시험","임상 결과","임상 진입")),
 ("risk","위험·악재 검토 단서",("적자전환","적자 확대","실적 악화","유상증자","상장폐지","횡령","배임","리콜","과징금","거래정지")),
)
def material_stage(e):
    # Inspect each original title; contradictory terms across titles must be retained.
    signals=[]
    for key,label,words in RULES:
        evidence=[]
        for a in e.get("articles",[]):
            terms=hits(normalized(a["title"]),words)
            if terms:evidence.append({"url":a["url"],"terms":terms})
        if evidence:
            signals.append({"id":key,"label":label,"terms":sorted({w for x in evidence for w in x["terms"]}),"evidence":evidence})
    keys={s["id"] for s in signals}
    conflict=bool(keys & {"rumor","denial","negative","plan","application","preliminary"} and keys & {"contract","approval","completed"})
    return {"schema":1,"evidence_type":"title_only","status":"unverified","signals":signals,
            "review_required":bool(conflict or keys & {"rumor","denial","negative","risk"}),
            "mixed_stage_cues":conflict,"note":"Headline terms may be negated, quoted or historical. No event status, direction, price causation or trade signal established."}
def annotate_sections(sections):
    return [{**s,"events":[{**e,"material_stage":material_stage(e)} for e in s["events"]]} for s in sections]
