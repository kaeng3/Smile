"""후보 뉴스 출처 일괄 점검 → logs/feeds_test.txt"""
import sys, time, news
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from urllib.parse import quote
C = {
 "머니투데이 증권":"https://rss.mt.co.kr/mt_news_stock.xml",
 "뉴시스 경제":"https://newsis.com/RSS/economy.xml", "뉴시스 산업":"https://newsis.com/RSS/industry.xml", "뉴시스 금융":"https://newsis.com/RSS/bank.xml",
 "뉴스1 경제":"https://www.news1.kr/rss/economy", "뉴스1 산업":"https://www.news1.kr/rss/industry",
 "서울경제":"https://www.sedaily.com/rss/newsall", "서울경제2":"https://www.sedaily.com/RSS/S1N1.xml",
 "이투데이 증권":"https://rss.etoday.co.kr/eto/finance_news.xml", "이투데이 기업":"https://rss.etoday.co.kr/eto/company_news.xml",
 "아주경제":"https://www.ajunews.com/rss/economy.xml", "아주경제2":"https://www.ajunews.com/rss/rss_all.xml",
 "연합인포맥스":"https://news.einfomax.co.kr/rss/allArticle.xml", "비즈니스포스트":"https://www.businesspost.co.kr/rss/allArticle.xml",
 "머니S":"https://www.moneys.co.kr/rss/allArticle.xml", "비즈워치":"https://news.bizwatch.co.kr/rss/all", 
 "뉴스토마토":"https://www.newstomato.com/rss/rss_all.xml", "이코노미스트":"https://economist.co.kr/rss/allArticle.xml",
 "블로터":"https://www.bloter.net/rss/allArticle.xml", "디일렉":"https://www.thelec.kr/rss/allArticle.xml",
 "ZDNet":"https://feeds.feedburner.com/zdkorea", "IT조선":"https://it.chosun.com/rss/allArticle.xml",
 "에너지경제":"https://www.ekn.kr/rss/allArticle.xml", "전기신문":"https://www.electimes.com/rss/allArticle.xml",
 "더바이오":"https://www.thebionews.net/rss/allArticle.xml", "히트뉴스":"https://www.hitnews.co.kr/rss/allArticle.xml",
 "약업신문":"https://www.yakup.com/rss/news.xml", "메디게이트":"https://www.medigatenews.com/rss/allArticle.xml",
 "바이오타임즈":"https://www.biotimes.co.kr/rss/allArticle.xml", "팜뉴스":"https://www.pharmnews.com/rss/allArticle.xml",
 "한국경제TV":"https://www.wowtv.co.kr/rss/news.xml", "SBS Biz":"https://biz.sbs.co.kr/rss/news_all.xml",
 "데일리안 경제":"https://www.dailian.co.kr/rss/economy.xml", "글로벌이코노믹":"https://www.g-enews.com/rss/allArticle.xml",
 "한경 마켓인사이트":"https://www.hankyung.com/feed/all-news", "매경 전체":"https://www.mk.co.kr/rss/40300001/",
 "조선일보 경제":"https://www.chosun.com/arc/outboundfeeds/rss/category/economy/?outputType=xml",
 "동아 경제":"https://rss.donga.com/economy.xml", "중앙 경제":"https://rss.joins.com/joins_money_list.xml",
 "KBS 경제":"https://world.kbs.co.kr/rss/rss_news.htm?lang=k", "YTN 경제":"https://www.ytn.co.kr/_ln/0102_rss.xml",
 "더구루":"https://www.theguru.co.kr/rss/S1N1.xml", "딜사이트":"https://dealsite.co.kr/rss/rss.xml?code=all",
 "구글뉴스 특징주":"https://news.google.com/rss/search?q=" + quote("특징주 when:1d") + "&hl=ko&gl=KR&ceid=KR:ko",
 "구글뉴스 증시":"https://news.google.com/rss/search?q=" + quote("증시 OR 코스닥 when:1d") + "&hl=ko&gl=KR&ceid=KR:ko",
 "구글뉴스 비즈":"https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=ko&gl=KR&ceid=KR:ko",
}
ok = {}
for name, url in C.items():
    try:
        x = news.fetch_rss(name, url); print(f"{'OK ' if x else 'EMP'} {name} {len(x)}  {x[0]['time']+' '+x[0]['title'][:35] if x else ''}"); 
        if x: ok[name] = url
    except Exception as e: print(f"ERR {name} {str(e)[:70]}")
    time.sleep(0.3)
# 포털 HTML 시도
import re
for name, url in {"네이버 증권속보":"https://news.naver.com/breakingnews/section/101/258",
                  "네이버 경제속보":"https://news.naver.com/breakingnews/section/101/263",
                  "다음 경제":"https://news.daum.net/economy",
                  "다음 증권":"https://finance.daum.net/news"}.items():
    try:
        h = news._get(url); links = re.findall(r'href="(https://n\.news\.naver\.com/mnews/article/\d+/\d+)[^"]*"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{8,})', h) if "naver" in url else re.findall(r'href="(https://v\.daum\.net/v/\d+)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{8,})', h)
        print(f"{'OK ' if links else 'EMP'} {name} {len(links)}  {links[0][1].strip()[:35] if links else len(h)}")
    except Exception as e: print(f"ERR {name} {str(e)[:70]}")
import json; json.dump(ok, open("logs/feeds_ok.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
