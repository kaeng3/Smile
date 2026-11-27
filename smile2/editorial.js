"use strict";
const $=id=>document.getElementById(id),el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n;};
let edition=new URLSearchParams(location.search).get("edition");
const fmt=n=>Number.isFinite(n)?n.toLocaleString("ko-KR",{maximumFractionDigits:2}):"미상";
let report=null,unknown=false,featured=false;
function link(text,raw){try{const u=new URL(raw);if(!["http:","https:"].includes(u.protocol)||u.username||u.password)throw Error();const a=el("a",text);a.href=u.href;a.target="_blank";a.rel="noopener noreferrer";return a}catch{return el("span",text)}}
function article(e){const a=el("article",null,"news"),h=el("h3");const lead=e.articles?.[0];h.append(link(e.headline,lead?.url));a.append(h,el("p","제목 기반 · 본문 미확인"+(e.article_count>1?" · 관련 보도 "+fmt(e.article_count)+"건 묶음":""),"meta"));
if(lead)a.append(el("p",String(lead.press||"출처 미상")+" · "+(lead.published_at?"발표 "+lead.published_at.slice(0,16).replace("T"," "):"발표 미상 · 수집 "+String(lead.seen_at||"미상").slice(0,16).replace("T"," "))+" · "+(lead.link_kind==="aggregator"?"검색 경유":lead.link_kind==="portal"?"포털":"출처 링크"),"meta"));
const v=e.evidence_review;if(v?.official_urls?.length)a.append(el("p","공식 자료 링크 "+fmt(v.official_urls.length)+"건 · 본문 미확인","meta"));
if(e.followup_reasons?.length)a.append(el("p",e.followup_reasons.map(x=>({morning_gap:"07:00~08:00 별도 뉴스",late_pre:"장전 마감 이후 발견",late_post:"장후 마감 이후 발견",after_cutoff:"장후 마감 이후 발표/수집",late_timestamp:"발표시각 뒤늦게 확인",late_featured:"특징주 표기 뒤늦게 확인"}[x]||x)).join(" · "),"meta"));
if(e.articles?.some(a=>a.retention_reasons?.length))a.append(el("p","기존 점수 미달 · 재료 단서로 추가 보관","meta"));
const m=e.material_stage;if(m&&m.signals?.length){a.append(el("p","재료 단계 단서: "+m.signals.map(x=>x.label).join(" · ")+(m.review_required?" · 검토 우선":""),"meta"))} 
for(const s of (e.stocks||[]).slice(0,12)){a.append(el("span",s.name+" "+s.code+" · "+(s.relation==="official_filing_issuer"?"공시 기업":"제목 언급"),"tag"))}
const d=el("details");d.append(el("summary",e.article_count>1?"관련 보도 "+fmt(e.article_count)+"건 및 분류 근거":"분류 근거 및 원문"));
const c=e.classification||{};d.append(el("p","분류: "+(c.category_label||"미상")+" · "+(c.review_required?"검토 필요":"제목 단서 기반")+" · "+(c.matched_terms||[]).join(", ")),el("p","기존 분류: "+(c.source_category||"미상")));
if(m?.signals?.length){d.append(el("p","제목 단서일 뿐 실제 사건 확정 여부 및 가격 영향은 미확인"));for(const signal of m.signals)d.append(el("p",signal.label+" — "+signal.terms.join(", ")))}
if(v){d.append(el("p","출처 링크 "+fmt(v.source_link_count)+" · 포털 "+fmt(v.portal_link_count)+" · 검색 경유 "+fmt(v.aggregator_link_count)+" · 언론사명 "+fmt(v.publisher_count)+"개 (독립 검증 아님)"));for(const u of v.official_urls||[]){const p=el("p");p.append(link("공식 자료 연결 ↗",u));d.append(p)}}
for(const row of e.articles||[]){const p=el("p");p.append(link(row.title,row.url),el("span"," · "+(row.press||"출처 미상")));d.append(p)}a.append(d);return a}
function search(e,q){return !q||[e.headline,...(e.stocks||[]).flatMap(s=>[s.name,s.code]),...(e.themes||[]),...(e.articles||[]).map(a=>a.title)].join(" ").toLowerCase().includes(q)}
function render(){if(!report)return;const q=$("query").value.trim().toLowerCase(),sections=featured?[{id:"featured",label:"[특징주] 모아보기",events:report.featured.events},...(report.featured.unknown_events?.length?[{id:"featured-unknown",label:"특징주 · 발표 시각 미확인",events:report.featured.unknown_events}]:[])]:unknown?report.unknown_sections:report.sections;let count=0;for(const id of ["toc","toc-mobile","sections"])$(id).replaceChildren();
if(edition==="post"&&!featured){
    let matches=0;
    for(const group of $("market-list").children){
        let visible=0;
        const matchTheme=group.firstElementChild.textContent.toLowerCase().includes(q);
        for(const row of group.querySelectorAll(".market-row")){
            row.hidden=!matchTheme&&!row.textContent.toLowerCase().includes(q);
            if(!row.hidden)visible++;
        }
        group.hidden=visible===0;
        matches+=visible;
    }
    $("results").textContent=fmt(matches)+"개 종목";
    return;
}
for(const [i,s] of sections.entries()){const list=s.events.filter(e=>search(e,q));count+=list.length;const id="section-"+s.id;for(const nav of ["toc","toc-mobile"]){const a=el("a",null,list.length?"":"zero");a.href="#"+id;a.append(el("span",s.label),el("span",fmt(list.length)));$(nav).append(a)}
const box=el("section",null,"section");box.id=id;const h=el("h2",featured?s.label:String(i+1).padStart(2,"0")+"  "+s.label);h.append(el("span",fmt(list.length)+"개 사건"));box.append(h);if(!list.length){box.append(el("p","해당 사건 없음","news small"));$("sections").append(box);continue}const body=el("div");let limit=5;const add=()=>{body.replaceChildren();for(const e of list.slice(0,limit))body.append(article(e));more.hidden=list.length<=limit;more.textContent="나머지 "+fmt(Math.max(0,list.length-limit))+"개 중 더 보기"};const more=el("button",null,"more");more.type="button";more.addEventListener("click",()=>{limit+=25;add()});box.append(body,more);add();$("sections").append(box)}
$("results").textContent=fmt(count)+"개 사건 · "+(featured?"특징주 최신순 · 발표 시각 미확인 별도 표시":(unknown?"수집 시각 기준 (발표 미상)":"발표 시각 확인")+" · 분야별 5개 우선 표시, 전체 펼침 가능");if(!count)$("sections").prepend(el("p","검색 결과가 없습니다."));
}
function captureHealth(){const c=report.capture_health||{};const labels={unknown:"최근 수집 상태 미확인",stale:"최근 수집 지연",partial:"최근 수집 일부 실패",success:"최근 수집원 응답 확인"};
$("capture-summary").textContent=c.checked_at?"최근 뉴스 수집 "+c.checked_at.slice(0,16).replace("T"," ")+" KST"+(c.status==="partial"?" · 일부 출처 실패":c.status==="stale"?" · 수집 지연":""):"최근 뉴스 수집 시각 미확인";
}
function renderMarketRow(stock){
    const s=stock;
    const a=el("details",null,"market-row");
    const heading=el("summary",null,"market-stock");
    heading.append(el("span",s.name),el("strong","+"+fmt(s.rate_pct)+"%","market-gain"));
    a.append(heading,el("p",s.code+" · 추정 거래대금 "+fmt(s.estimated_trading_value_won/1e8)+"억원","small"));
    const current=(s.evidence||[]).filter(item=>item.relation==="same_session_title_mention_not_causation");
    const references=(s.scanner_references||[]).filter(item=>!current.some(article=>article.url===item.url));
    const summary=s.gemini_material_summary;
    const lead=[...current,...references].find(item=>item.url===summary?.url)||current[0]||references[0];
    function article(item){
        const box=el("div",null,"market-article");
        box.append(link(item.title,item.url));
        const kind=item.material_kind==="disclosure"?"공시":item.material_kind==="featured"?"시황":"";
        const time=item.published_at?item.published_at.slice(11,16):item.date;
        const metadata=[kind,time].filter(Boolean).join(" · ");
        if(metadata)box.append(el("p",metadata,"small market-article-meta"));
        return box;
    }
    if(lead){
        const box=article(lead);
        if(lead.url===summary?.url){
            box.append(el("p","Gemini 재료 요약 · 인과 미확인","market-summary-label"),
                       el("p",summary.text,"market-summary"));
        }
        a.append(box);
    }else{
        a.append(el("p","관련 뉴스·공시를 확인하지 못했습니다.","small"));
    }
    const more=[...current,...references,...(s.evidence||[])].filter((item,index,items)=>
        item.url!==lead?.url&&items.findIndex(other=>other.url===item.url)===index);
    if(more.length){
        const extra=el("details",null,"market-more");
        extra.append(el("summary","관련 기사 "+fmt(more.length)+"건 더 보기"));
        for(const item of more)extra.append(article(item));
        a.append(extra);
    }
    return a;
}
async function market(){
    if(edition!=="post")return;
    const m=report.market;
    const stocks=m?.stocks||[];
    if(!stocks.length){$("market-note").textContent="당일 선별 종목 자료 없음";return;}
    $("market-note").textContent="당일 기준봉 스캐너 상승 종목 · 종목을 누르면 관련 뉴스·공시가 펼쳐집니다.";
    const day=String(report.report_date).replaceAll("-","");
    const [bundles,brief]=await Promise.all(["../theme_bundles.json","../news_feed/brief.json"].map(async url=>{
        try{const response=await fetch(url);return response.ok?await response.json():null;}catch{return null;}
    }));
    const snapshot=brief?.days?.[day];
    for(const [key,label] of [["kospi","코스피"],["kosdaq","코스닥"]]){
        const match=String(snapshot?.[key]||"").match(/([\d,]+\.\d+)\s*\(([+-]?\d+(?:\.\d+)?%)\)/);
        if(match)$("market-indices").append(el("span",label+" "+match[1]+" ("+match[2]+")"));
    }
    const codes=new Set(stocks.map(stock=>stock.code));
    const byCode=new Map();
    for(const bundle of bundles?.bundles||[]){
        for(const event of bundle.events||[]){
            if(event.date===day&&codes.has(event.code)&&!byCode.has(event.code))byCode.set(event.code,bundle.theme);
        }
    }
    const groups=new Map();
    for(const stock of stocks){
        const theme=byCode.get(stock.code)||"개별주";
        if(!groups.has(theme))groups.set(theme,[]);
        groups.get(theme).push(stock);
    }
    for(const [theme,items] of groups){
        const group=el("section",null,"market-theme");
        group.append(el("h3",theme));
        for(const stock of items)group.append(renderMarketRow(stock));
        $("market-list").append(group);
    }
    render();
}
$("query").addEventListener("input",render);
function setView(view){featured=edition==="post"&&view==="featured";unknown=false;
for(const id of ["featured-nav","featured-mobile"])if(featured)$(id).setAttribute("aria-current","page");else $(id).removeAttribute("aria-current");
for(const id of ["pre","post"])if(id===edition&&!featured)$(id).setAttribute("aria-current","page");else $(id).removeAttribute("aria-current");
$("market").hidden=edition!=="post"||featured;
$("featured-note").hidden=!featured;
if(featured)$("featured-note").textContent="당일 수집한 특징주 기사입니다. 발표 시각을 확인하지 못한 기사는 아래에 따로 표시합니다.";
$("heading").textContent=featured?"[특징주] 모아보기":edition==="pre"?"장전 리포트":"장후 이브닝";render()}
function route(){setView(location.hash==="#featured-view"?"featured":"all")}
window.addEventListener("hashchange",()=>{if(report&&(!location.hash||location.hash==="#featured-view"))route()});
for(const id of ["featured-nav","featured-mobile"])$(id).addEventListener("click",e=>{e.preventDefault();const hash=e.currentTarget.getAttribute("href");if(location.hash!==hash)history.pushState(null,"",hash);if(report){route();$("heading").scrollIntoView({block:"start"})}});
async function init(){try{if(!["pre","post"].includes(edition)){const response=await fetch("manifest.json",{cache:"no-store"});if(!response.ok)throw Error("manifest");const manifest=await response.json();edition=manifest.preferred_edition==="post"?"post":"pre"}for(const id of ["evening-extra-nav","featured-mobile"])$(id).hidden=edition!=="post";const r=await fetch("editorial-"+edition+".json",{cache:"no-store"});if(!r.ok)throw Error("HTTP "+r.status);report=await r.json();if(report.schema!==1||report.edition!==edition||report.sections?.length!==26||report.unknown_sections?.length!==26)throw Error("schema");$(edition).setAttribute("aria-current","page");$("heading").textContent=edition==="pre"?"장전 리포트":"장후 이브닝";$("date").textContent=report.report_date+" · "+(edition==="pre"?report.report_date+" 00:00":report.start.slice(0,16).replace("T"," "))+" ~ "+report.cutoff_exclusive.slice(0,16).replace("T"," ")+" KST";$("status").hidden=report.window_status!=="partial";$("status").textContent="수집 기간 진행 중 · 부분 리포트";captureHealth();market();route()}catch(e){report=null;$("status").hidden=false;$("status").textContent="리포트 자료를 읽을 수 없습니다. 뉴스 검색 화면을 이용해 주세요."}}
if(new URLSearchParams(location.search).has("event")||location.hash==="#sources"){location.replace("search.html"+location.search+location.hash)}else init();