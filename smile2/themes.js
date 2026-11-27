"use strict";
const $=id=>document.getElementById(id),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n};
let events=[],groups=[],limit=30,selected=null;
function groupEvents(){
 const basis=$("basis").value==="published"?"published_at":"seen_at",start=$("start").value,end=$("end").value,q=$("query").value.trim().toLocaleLowerCase();
 if(start&&end&&start>end)return [];
 const map=new Map();
 for(const e of events){
  const articles=e.articles.filter(a=>{const d=(a[basis]||"").slice(0,10);return d&&(!start||d>=start)&&(!end||d<=end)});
  for(const name of new Set(articles.flatMap(a=>a.themes||[]))){
   if(q&&!name.toLocaleLowerCase().includes(q))continue;
   const evidence=articles.filter(a=>(a.themes||[]).includes(name));
   if(!map.has(name))map.set(name,{name,events:[],urls:new Set(),stocks:new Map()});
   const g=map.get(name);g.events.push({id:e.id,headline:evidence[0].title,count:evidence.length,score:e.keyword_score});
   for(const a of evidence){g.urls.add(a.url);for(const [n,code] of a.stocks||[]){
    if(!g.stocks.has(code))g.stocks.set(code,{name:n,code,events:new Set()});
    g.stocks.get(code).events.add(e.id);
   }}
  }
 }
 return [...map.values()].sort((a,b)=>b.events.length-a.events.length||a.name.localeCompare(b.name,"ko"));
}
function show(g){selected=g.name;const d=$("detail");d.replaceChildren(el("h2",g.name),el("p",g.events.length+"개 사건 후보 · "+g.urls.size+"개 원문 URL","meta"),el("h2","뉴스에 연결된 종목"));
 const stocks=[...g.stocks.values()].sort((a,b)=>b.events.size-a.events.size||a.code.localeCompare(b.code));
 if(!stocks.length)d.append(el("p","이 기간에 연결된 종목이 없습니다.","small"));
 for(const s of stocks.slice(0,30))d.append(el("p",s.name+" ("+s.code+") · "+s.events.size+"개 사건 언급","meta"));
 d.append(el("h2","관련 사건 후보"));
 for(const e of [...g.events].sort((a,b)=>b.score-a.score).slice(0,30)){
  const p=el("p"),a=el("a",e.headline);a.href="search.html?event="+encodeURIComponent(e.id);p.append(a,el("span"," · 원문 "+e.count+"건","meta"));d.append(p);
 }
 d.append(el("p","상위 30개 종목·사건 표시. 직접 수혜를 의미하지 않습니다.","small"));
}
function render(){groups=groupEvents();$("count").textContent=groups.length+"개 테마 · "+($("basis").value==="published"?"발표 시각 확인 기사만":"수집 시각 기준, 발행일 미상 포함");
 $("list").replaceChildren();
 if(!groups.length)$("list").append(el("p","조건에 맞는 테마가 없습니다."));
 for(const g of groups.slice(0,limit)){const a=el("article",null,"event"),b=el("button",g.name);b.type="button";b.addEventListener("click",()=>show(g));a.append(b,el("p",g.events.length+"개 사건 후보 · 원문 "+g.urls.size+"건 · 종목 언급 "+g.stocks.size+"개","meta"));$("list").append(a)}
 $("more").hidden=groups.length<=limit;
 const old=groups.find(g=>g.name===selected);if(old)show(old);else{selected=null;$("detail").replaceChildren(el("h2","테마 근거"),el("p","테마를 선택하세요."))}
}
for(const id of ["query","start","end","basis"])$(id).addEventListener(id==="query"?"input":"change",()=>{limit=30;render()});
$("more").addEventListener("click",()=>{limit+=30;render()});
async function init(){try{const r=await fetch("events.json",{cache:"no-store"});if(!r.ok)throw Error();const d=await r.json();if(d.schema!==1||!Array.isArray(d.events))throw Error();events=d.events;$("status").textContent="테마 사전 기반 사건 탐색 · 동일 테마 안에서는 사건 중복 집계 방지";render()}catch{$("status").textContent="사건 데이터를 읽을 수 없습니다.";render()}}
init();