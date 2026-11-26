"use strict";
const $=id=>document.getElementById(id);
let events=[], limit=30, selected=null;
const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n;};
function timestamp(a){return a.published_at||a.seen_at||""}
function day(a){return timestamp(a).slice(0,10)}
function dates(e){return [...new Set(e.articles.map(day).filter(Boolean))]}
function newest(e){return e.articles.map(a=>a.seen_at||"").sort().at(-1)||""}
function safeLink(url){try{let u=new URL(url);return ["https:","http:"].includes(u.protocol)&&!u.username&&!u.password?u.href:null}catch{return null}}
function populate(id,values){for(const value of values){const o=el("option",value);o.value=value;$(id).append(o)}}
function tags(values){const node=el("div",null,"tags");values.slice(0,8).forEach(v=>node.append(el("span",v,"tag")));return node}
function show(e){selected=e.id;const d=$("detail");d.replaceChildren(el("h2","사건 근거"),el("p",e.headline,"headline"),el("p","제목 유사도 기반 후보 · 사실 및 인과관계 미검증"),el("h2","제목에서 언급된 종목"),tags(e.stocks.map(s=>s.name+" "+s.code)),el("h2","연결 테마 (사전 기반)"),tags(e.themes),el("h2","관련 원문 "+e.article_count+"건"));
const ul=el("ul");for(const a of e.articles){const li=el("li"),href=safeLink(a.url);if(href){const link=el("a",a.title);link.href=href;link.target="_blank";link.rel="noopener noreferrer";li.append(link)}else li.append(el("span",a.title));li.append(el("div",a.press+" · "+(a.published_at?"발표 "+a.published_at.slice(0,16).replace("T"," "):"발표 시각 미상 · 수집 "+(a.seen_at||"미상").slice(0,16).replace("T"," ")),"meta"));ul.append(li)}d.append(ul);document.querySelectorAll(".event").forEach(n=>{const active=n.dataset.id===selected;n.classList.toggle("selected",active);n.querySelector("button").setAttribute("aria-pressed",String(active))});}
function render(){let q=$("query").value.trim().toLocaleLowerCase(),cat=$("category").value,date=$("date").value;
let filtered=events.filter(e=>(!cat||e.category===cat)&&(!date||dates(e).includes(date))&&(!q||[e.headline,...e.articles.map(a=>a.title),...e.themes,...e.stocks.flatMap(s=>[s.name,s.code])].join(" ").toLocaleLowerCase().includes(q)));
if($("order").value==="recent")filtered.sort((a,b)=>newest(b).localeCompare(newest(a)));else filtered.sort((a,b)=>b.keyword_score-a.keyword_score);
$("results").textContent=filtered.length+"개 사건 후보 · 날짜는 발표 시각 우선, 없으면 수집 날짜";
$("events").replaceChildren();
if(!filtered.length)$("events").append(el("p","조건에 맞는 사건이 없습니다."));
for(const e of filtered.slice(0,limit)){let card=el("article",null,"event");card.dataset.id=e.id;let b=el("button",e.headline);b.type="button";b.setAttribute("aria-pressed",String(e.id===selected));b.addEventListener("click",()=>show(e));card.append(el("div",e.category+" · 원문 "+e.article_count+"건 · 키워드 점수 "+e.keyword_score,"meta"),b,tags(e.stocks.map(s=>s.name)),el("p","사건 후보 · "+dates(e).join(", "),"meta"));if(e.id===selected)card.classList.add("selected");$("events").append(card)}
$("more").hidden=filtered.length<=limit;if(!filtered.some(e=>e.id===selected)){selected=null;$("detail").replaceChildren(el("h2","사건 근거"),el("p","목록에서 사건을 선택하세요."))}}
for(const id of ["query","category","date","order"])$(id).addEventListener(id==="query"?"input":"change",()=>{limit=30;render()});
$("more").addEventListener("click",()=>{limit+=30;render()});
async function init(){try{const res=await fetch("events.json",{cache:"no-store"});if(!res.ok)throw new Error("HTTP "+res.status);const data=await res.json();if(data.schema!==1||!Array.isArray(data.events))throw new Error("지원하지 않는 데이터 형식");events=data.events;for(const [id,key] of [["input-count","input_count"],["url-count","unique_url_count"],["event-count","event_count"],["missing-count","missing_published_at"]])$(id).textContent=Number(data[key]).toLocaleString("ko-KR");populate("category",[...new Set(events.map(e=>e.category))].sort());populate("date",[...new Set(events.flatMap(dates))].sort().reverse());$("status").textContent="시범 분석 데이터 · 발표 시각 미상 기사는 별도 표시됩니다. 장전·장후 정식 분류 및 원인 분석은 검증 중입니다.";render()}catch(e){$("status").textContent="사건 데이터가 아직 생성되지 않았거나 읽을 수 없습니다. 개발 환경에서 news_engine을 실행해 events.json을 생성하세요.";render()}}
init();