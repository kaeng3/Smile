"""Explicit headline retention cues. Preserve coverage, never increase impact scores."""
import re
import unicodedata
from html import unescape

RULES={
 "corporate":r"기업회생|회생절차|계약\s*(?:체결|해지|취소)|공급계약|지분\s*(?:매각|인수|취득)|추가\s*취득|주식.{0,24}(?:취득 결정|매각 결정)|유상증자|상장폐지|거래정지|인수합병|본계약|수주\s*확정",
 "biotech":r"임상\s*(?:[123]\s*상|시험|결과|성공|실패)|[123]\s*상(?:서|에서|\s*결과|\s*시험)|품목허가|신약\s*(?:승인|허가|개발)|오픈이노베이션",
 "market":r"(?:코스피|코스닥).{0,45}(?:사이드카|서킷브레이커|급락|급등|외국인\s*매수|외국인\s*순매수|신저가)|(?:매수|매도)\s*사이드카|증안펀드",
 "policy":r"법안\s*(?:통과|의결)|세액공제\s*(?:확대|신설|폐지)|수출\s*(?:통제|규제)|관세\s*(?:인상|인하|부과)|(?:전기차|재생에너지).{0,30}(?:목표|의무화)",
}
def retention_reasons(title):
    s=unicodedata.normalize("NFKC",unescape(str(title or ""))).strip()
    if re.match(r"^\s*\[(?:표|인사|부음|포토|사진)\]",s):
        return []
    return [k for k,v in RULES.items() if re.search(v,s)]
