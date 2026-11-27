"""SMILE 3.0 editorial categories, independent of collector scoring.
Title evidence only. Rules are hypotheses and require labeled review.
"""
from collections import Counter
from html import unescape
import re
import unicodedata

VERSION="smile3-title-v3"
CATEGORIES=(
 ("economy","경제 일반·증시"),("rivalry","미중 패권"),("usa","국제 · 미국"),
 ("europe","국제 · 유럽"),("china","국제 · 중국"),("world","국제 · 기타"),
 ("commodity","원자재"),("policy","정부정책·규제"),("semi","반도체·디스플레이"),
 ("energy","전력·원전·에너지"),("robot","AI·로봇"),("tech","IT·신기술"),
 ("auto","자동차"),("battery","이차전지"),("ship","조선·해운"),
 ("bio","바이오·의료"),("space","우주·항공"),("defense","국방·방산"),
 ("consumer","화장품·음식료·유통"),("crypto","코인·STO"),("finance","은행·증권·보험"),
 ("ent","IP·엔터"),("infra","건설·부동산·인프라"),("politics","정치"),
 ("corp","M&A·주요 공시"),("other","기타·분류 검토"),
)
LABELS=dict(CATEGORIES)
# Distinct subject signals, not generic investment/price/publisher names.
SECTORS={
 "semi":("반도체","hbm","dram","낸드","파운드리","웨이퍼","디스플레이","oled","노광장비","시스템lsi","ai칩","gpu"),
 "energy":("전력망","전력변환","변압기","원전","원자력발전","발전소","태양광","풍력","수소연료전지","전력수급","재생에너지","전력케이블"),
 "robot":("휴머노이드","피지컬 ai","로봇","인공지능","생성형 ai","llm","챗봇","ai 모델","ai 에이전트"),
 "tech":("양자컴퓨터","양자컴","양자통신","사이버보안","해킹","개인정보 유출","개인정보 추가 유출","개인정보 일부 유출","보안 패치","데이터센터","ai 서버","ai서버","클라우드","스마트폰","통신망","6g","5g","소프트웨어"),
 "auto":("자동차","전기차","완성차","현대차","기아차","산불 대응 차량","자율주행","차량용","모빌리티","자동차부품"),
 "battery":("이차전지","2차전지","배터리","전고체","양극재","음극재","전해질","전해액","ess"),
 "ship":("조선소","조선업","군수지원선","선박","해운","컨테이너선","lng선","선박운임","선박 건조"),
 "bio":("임상","신약","치료제","치료용 조성물","재생치료","헬스케어","인체조직","cdmo","항암","제약","바이오","의료ai","의료기기","진단장비","백신"),
 "space":("스페이스x","우주","위성","발사체","항공우주","우주항공","로켓","항공기"),
 "defense":("방산","국방","군함","함정","전투기","미사일","무기체계","해군","잠수함"),
 "consumer":("화장품","k뷰티","k-뷰티","뷰티","음식료","식품","면세점","홈쇼핑","유통업","편의점","백화점"),
 "crypto":("비트코인","이더리움","가상자산","암호화폐","스테이블코인","토큰증권","sto","블록체인"),
 "finance":("은행","보험사","보험업","보험금","증권업","연금 컨설팅","kb금융","금융지주","예대마진","증권사"),
 "ent":("게임","신작 판권","케이팝","k팝","k-pop","엔터테인먼트","웹툰","공연","음원","드라마"),
 "infra":("부동산","주택시장","주택가격","보유세","종부세","아파트","청약","분양","건설업","건설사","공사 수주","재개발","재건축","철도","gtx"),
 "commodity":("국제유가","국제 유가","유가 상승","유가 하락","유가 급등","유가 급락","원유","원자재","구리 가격","철광석","금값","천연가스 가격","리튬 가격","철강 가격"),
}
MACRO=("코스피","코스닥","증시","주가지수","환율","기준금리","금리인상","금리 인상","금리인하","금리 인하","물가","소비자물가","경제성장률","성장률","민간소비","한국은행","금융통화위원회","한은","fomc","federal reserve","고용지표","무역수지","수출입 동향","나스닥","다우지수","s&p")
CORPORATE=("최대주주","주주총회","자사주","합병","인수합병","유상증자","무상증자","공개매수","상장폐지","공급계약","영업이익","매출액","공시")
POLICY=("법안","법률 개정","규제","정부정책","지원 정책","정부 지원","세액공제","산업부","기획재정부","금융위원회","입법","정책 발표")
POLITICS=("국회의원","대통령","총선","대선","정당","여당","야당","국회","탄핵","청문회")
REGIONS={"usa":("미국","트럼프","연준","fed","백악관","美"),"europe":("유럽","eu","독일","프랑스","영국","유럽연합","ecb"),"china":("중국","시진핑","베이징","中"),"world":("일본","인도","베트남","러시아","중동","사우디","몽골","호주","캐나다","브라질")}
TRADE=("수출통제","수출 통제","수출규제","수출 규제","관세","무역전쟁","패권","제재")
def normalized(title):
    s=unicodedata.normalize("NFKC",unescape(str(title))).casefold()
    return re.sub(r"\s+"," ",s).strip()
def match(s,word):
    if re.fullmatch(r"[a-z0-9]+",word):
        return bool(re.search(r"(?<![a-z0-9])"+re.escape(word)+r"(?![a-z0-9])",s))
    return word.casefold() in s
def hits(s,words):
    found=[w for w in words if match(s,w)]
    # Nested synonyms do not give duplicate weight (e.g. 전기차/차).
    return [w for w in found if not any(w!=v and w in v for v in found)]

def classify(title,source_category=""):
    s=normalized(title)
    signals={k:hits(s,v) for k,v in SECTORS.items()}
    signals={k:v for k,v in signals.items() if v}
    # The central bank is a macroeconomic institution, not a commercial bank.
    if "finance" in signals and signals["finance"]==["은행"] and "한국은행" in s:
        del signals["finance"]
    regions={k:hits(s,v) for k,v in REGIONS.items()}
    regions={k:v for k,v in regions.items() if v}
    macro=hits(s,MACRO);corp=hits(s,CORPORATE);policy=hits(s,POLICY);politics=hits(s,POLITICS);trade=hits(s,TRADE)
    tags=list(signals)+list(regions)+(["corp"] if corp else [])+(["policy"] if policy else [])+(["politics"] if politics else [])
    # Bilateral trade conflict is a separate subject, sector is a cross-tag.
    if "usa" in regions and "china" in regions and trade:
        primary="rivalry";evidence=regions["usa"]+regions["china"]+trade;basis="bilateral_trade"
    # A broad index headline is not attributed to a single industry.
    elif hits(s,("코스피","코스닥","주가지수","나스닥","다우지수","s&p")):
        primary="economy";evidence=macro;basis="index_terms"
    elif macro and (len(signals)>=2 or not signals):
        primary="economy";evidence=macro;basis="broad_market"
    elif signals:
        ranked=sorted(signals,key=lambda k:(-len(signals[k]),k))
        top=ranked[0]
        if len(ranked)>1 and len(signals[top])==len(signals[ranked[1]]):
            primary="other";evidence=[w for k in ranked for w in signals[k]];basis="ambiguous_sectors"
        else:
            primary=top;evidence=signals[top];basis="sector_terms"
    elif macro:
        primary="economy";evidence=macro;basis="macro_terms"
    elif corp:
        primary="corp";evidence=corp;basis="corporate_terms"
    elif policy:
        primary="policy";evidence=policy;basis="policy_terms"
    elif politics:
        primary="politics";evidence=politics;basis="political_terms"
    elif len(regions)==1:
        primary=next(iter(regions));evidence=regions[primary];basis="region_only_review"
    else:
        primary="other";evidence=[];basis="insufficient_or_conflicting_evidence"
    return {"category_id":primary,"category_label":LABELS[primary],"source_category":str(source_category),
            "taxonomy_version":VERSION,"tags":list(dict.fromkeys(tags)),"matched_terms":evidence,
            "basis":basis,"review_required":primary=="other" or len(signals)>1 or basis=="region_only_review",
            "evidence_type":"title_only"}

def group(events):
    sections={k:[] for k in LABELS}
    for e in events:
        classified=classify(e["headline"],e.get("category",""))
        sections[classified["category_id"]].append({**e,"classification":classified})
    return [{"id":k,"label":LABELS[k],"count":len(v),"events":v} for k,v in sections.items()]

def audit(events):
    result=Counter();review=0;old=Counter();transitions=Counter()
    for e in events:
        c=classify(e["headline"],e.get("category",""))
        result[c["category_id"]]+=1
        review+=c["review_required"]
        old[c["source_category"]]+=1
        transitions[(c["source_category"],c["category_id"])]+=1
    return {"taxonomy_version":VERSION,"total":len(events),"review_required":review,
            "new_counts":{k:result[k] for k in LABELS},"old_counts":dict(old),
            "transitions":[{"from":a,"to":b,"count":n} for (a,b),n in transitions.most_common()],
            "note":"Distribution audit, not measured classification accuracy."}
