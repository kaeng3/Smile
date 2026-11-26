import unittest
from datetime import date,datetime
from smile2.market_brief import market_brief
from smile2.supplemental_store import merge
from smile2.news_engine import KST
class MarketTests(unittest.TestCase):
    def test_dated_rows_only(self):
        day=date(2026,11,26)
        d={"20261125":[{"code":"000100","rate":99,"trading_value":100}],"20261126":[
          {"code":"000100","name":"예시","rate":10,"trading_value":123456,"summary":"UNVERIFIED_CAUSE"},
          {"code":"000200","rate":12,"trading_value":-1}]}
        r=market_brief(d,day,{})
        self.assertEqual(len(r["stocks"]),1)
        self.assertEqual(r["stocks"][0]["trading_value_won"],123456)
        self.assertNotIn("UNVERIFIED_CAUSE",str(r))
        self.assertEqual(market_brief(d,date(2026,11,27),{})["status"],"unavailable")
    def test_links_not_causes(self):
        r=market_brief({"20261126":[{"code":"000100","rate":10,"trading_value":123}]},date(2026,11,26),
           {"events":[{"articles":[{"title":"예시","url":"https://example.org/a","stocks":[["예시","000100"]]}]}]})
        self.assertEqual(r["stocks"][0]["evidence"][0]["relation"],"same_session_title_mention_not_causation")
    def test_preserve_first_seen(self):
        now=datetime(2026,11,26,18,tzinfo=KST)
        a={"url":"https://example.org/a","observed_at":"2026-11-26T08:00:00+09:00","published_at":None}
        b={**a,"observed_at":"2026-11-26T10:00:00+09:00","published_at":"2026-11-26T07:00:00+09:00"}
        r=merge([a],[b],now)
        self.assertEqual(r[0]["observed_at"],a["observed_at"])
        self.assertEqual(r[0]["publication_verified_at"],b["observed_at"])
        self.assertEqual(merge(r,[],now),r)
if __name__=="__main__":unittest.main()
