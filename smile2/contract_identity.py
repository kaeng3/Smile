"""Conservative same-day contract candidate anchors; no body verification."""
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from html import unescape
from datetime import datetime,timedelta

# Recognize explicit product phrases, not a broad sector or company alone.
PRODUCTS={"ai_server":r"(?<![a-z0-9])ai\s*서버","lng_ship":r"lng\s*(?:운반선|선박|선)",
          "transformer":r"변압기","solar_module":r"태양광\s*모듈"}
CONTRACT=re.compile(r"수주|공급\s*(?:본\s*)?계약|본계약|계약\s*체결")
# Any uncertain, adverse, revision or alternative transaction cue blocks this rule.
BLOCK=re.compile(r"취소|철회|해지|중단|반려|부인|해명|정정|변경|감액|증액|연장|만료|검토|추진|협상|예정|신청|가능성|수주설|계약설|사실무근|미확정|잠정|추정|목표|기대|(?:작년|지난해|전년|과거)\s|수주\s*잔고|계약\s*잔액|미체결|가계약|양해각서|mou|(?:첫|최초)\s*수주")
AMOUNT=re.compile(r"(?<![\d.,])(\d[\d,]*(?:\.\d+)?)\s*(조|억)\s*(?:원)?(?![\d만])")
# Secondary totals are not individual contract amounts.
TOTAL=re.compile(r"누적|합계|총액|총\s*수주|연간|상반기|하반기|올해|수주\s*잔고")
def contract_identity(a):
    codes={s[1] for s in a.get("stocks",[]) if len(s)==2}
    if len(codes)!=1:return None
    # A published date must exist. Unknown times remain distinct from dated evidence.
    try: d=datetime.fromisoformat(a.get("published_at") or "")
    except (ValueError,TypeError):return None
    if d.tzinfo is None:return None
    t=unicodedata.normalize("NFKC",unescape(a["title"])).casefold()
    if BLOCK.search(t):return None
    # Avoid vague headline-only matching when there is no explicit product or multiple products.
    products=[k for k,p in PRODUCTS.items() if re.search(p,t)]
    if len(products)!=1:return None
    # The leading clause contains the individual contract; subsequent clauses may give aggregates.
    head=re.split(r"\.{2,}|…+|[;；]",t,maxsplit=1)[0]
    if TOTAL.search(head) or not CONTRACT.search(head) or not re.search(PRODUCTS[products[0]],head):return None
    amounts=list(AMOUNT.finditer(head))
    if len(amounts)!=1:return None
    m=amounts[0]
    # Exclude foreign currency or compound values (1조 200억원) instead of guessing.
    if re.search(r"달러|유로|엔화|위안|조\s*\d|억\s*\d",head):return None
    try: amount=Decimal(m[1].replace(",",""))*(10000 if m[2]=="조" else 1)
    except InvalidOperation:return None
    if amount<=0:return None
    # A named issuer must actually be present; other entities/counterparties should not be conflated.
    names={str(s[0]).casefold() for s in a["stocks"] if s[0]}
    if not any(n in head for n in names):return None
    return (next(iter(codes)),products[0],str(amount.normalize()),d.date().isoformat())

def compatible_contract(a,b):
    ka,kb=contract_identity(a),contract_identity(b)
    if ka is None or ka!=kb:return False
    # Keep explicit customer/region distinctions separate. Unknown customer is not a match
    # to an explicit one: this rule deliberately abstains on such headlines.
    def explicit(t):
        t=unicodedata.normalize("NFKC",t).casefold()
        return bool(re.search(r"(?:(?:와|과)\s+(?:공급|계약|본계약)|(?:에|로)\s+(?:공급|납품|수출)|(?:고객사|발주처|공급처|계약상대방|상대방|미국|중국|일본|유럽|국내|해외|글로벌|북미|대만|인도))",t))
    if explicit(a["title"]) or explicit(b["title"]):return False
    # Narrow same-day temporal window for an identical product/amount/issuer.
    da=datetime.fromisoformat(a["published_at"]);db=datetime.fromisoformat(b["published_at"])
    return abs(da-db)<=timedelta(hours=12)
