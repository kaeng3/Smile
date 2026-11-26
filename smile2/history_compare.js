"use strict";
// Local-only comparison. Lexical similarity does not establish that two events are identical.
function compareHistory(rows,headline,day,minScore=0.3){
 const normalize=s=>String(s??"").normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu," ").trim();
 const grams=s=>{const x=normalize(s).replace(/\s/g,"");return new Set(Array.from({length:Math.max(0,x.length-2)},(_,i)=>x.slice(i,i+3)))};
 const words=s=>new Set(normalize(s).split(/\s+/).filter(x=>x.length>=2));
 const sim=(a,b)=>{const union=new Set([...a,...b]);return union.size?[...a].filter(x=>b.has(x)).length/union.size:0};
 const q=normalize(headline),g=grams(headline),w=words(headline);
 if(q.length<5||!day||!Number.isFinite(minScore)||minScore<0||minScore>1)throw Error("비교 제목 5자 이상, 기준일 및 유사도 필요");
 let eligible=0,first=null,last=null;const hits=[];
 for(const r of rows){
  if(!r||typeof r.date!=="string"||!/^\d{4}-\d{2}-\d{2}$/.test(r.date)||r.date>=day)continue;
  const title=decode(r,"title");if(!title)continue;
  eligible++;if(first===null||r.date<first)first=r.date;if(last===null||r.date>last)last=r.date;
  const exact=normalize(title)===q;
  const score=exact?1:0.7*sim(g,grams(title))+0.3*sim(w,words(title));
  if(exact||score>=minScore)hits.push({date:r.date,title,score,kind:exact?"exact_title":"lexical_candidate"});
 }
 hits.sort((a,b)=>b.score-a.score||b.date.localeCompare(a.date));
 return {eligible,first,last,hits,classification:hits.length?"prior_similarity_candidate":eligible?"no_match_in_available_records":"no_prior_records"};
}
function renderCompare(){
 const out=$("compare-results");out.replaceChildren();
 const c=$("compare-code").value.trim().toUpperCase(),day=$("compare-day").value,title=$("compare-title").value.trim();
 if(!data){out.append(el("p","먼저 로컬 자료를 선택하세요."));return}
 if(!/^[0-9A-Z]{6}$/.test(c)){out.append(el("p","올바른 종목코드를 입력하세요."));return}
 try{
  const r=compareHistory(data[c]||[],title,day,Number($("compare-threshold").value));
  out.append(el("p","기준일 이전 비교 가능 기록 "+r.eligible+"건"+(r.first?" · "+r.first+" ~ "+r.last:""),"meta"));
  out.append(el("h2",r.classification==="prior_similarity_candidate"?"과거 유사 재료 검토 후보":r.classification==="no_match_in_available_records"?"보유 기록에서 유사 제목 미검출":"기준일 이전 기록 없음"));
  out.append(el("p","동일 사건 또는 신규 재료 확정이 아닙니다. 자료 공백과 제목 차이가 있을 수 있습니다.","small"));
  for(const hit of r.hits.slice(0,30)){const a=el("article",null,"event");a.append(el("p",hit.date+" · "+(hit.kind==="exact_title"?"정규화 제목 일치":"문자·단어 유사도 "+Math.round(hit.score*100)+"%"),"meta"),el("h2",hit.title));out.append(a)}
  if(r.hits.length>30)out.append(el("p","상위 30개 표시 / "+r.hits.length+"개 후보","small"));
 }catch(e){out.append(el("p",e.message))}
}
$("compare-form").addEventListener("submit",e=>{e.preventDefault();renderCompare()});
const query=new URLSearchParams(location.search);
if(/^[0-9A-Z]{6}$/.test(query.get("code")||"")){$("compare-code").value=query.get("code");$("code").value=query.get("code")}
if(/^\d{4}-\d{2}-\d{2}$/.test(query.get("day")||""))$("compare-day").value=query.get("day");
