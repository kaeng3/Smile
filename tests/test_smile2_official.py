import unittest
from datetime import datetime
from smile2.news_engine import KST
from smile2.official_feeds import parse_feed,dart_rows
NOW=datetime(2026,11,26,18,0,tzinfo=KST)
class OfficialTests(unittest.TestCase):
    def test_rss(self):
        xml=b'<rss><channel><item><title>Official test</title><link>https://example.org/1</link><pubDate>Wed, 25 Nov 2026 18:30:00 GMT</pubDate></item></channel></rss>'
        r=parse_feed(xml,"official","https://example.org/rss","macro",NOW)
        self.assertEqual(r[0]["published_at"],"2026-11-26T03:30:00+09:00")
    def test_atom(self):
        xml=b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Test</title><link href="/a"/><updated>2026-11-26T02:00:00Z</updated></entry></feed>'
        r=parse_feed(xml,"official","https://example.org/rss","macro",NOW)
        self.assertIsNone(r[0]["published_at"])
        self.assertEqual(r[0]["url"],"https://example.org/a")
    def test_dtd_rejected(self):
        with self.assertRaises(ValueError):
            parse_feed(b'<!DOCTYPE rss><rss/>',"official","https://example.org","macro",NOW)
    def test_dart_no_imputed_time(self):
        r=dart_rows({"status":"000","list":[{"rcept_no":"20261126000001","corp_name":"Example","stock_code":"000100","report_nm":"Test","rcept_dt":"20261126"}]},NOW)
        self.assertIsNone(r[0]["published_at"])
        self.assertEqual(r[0]["stocks"],[["Example","000100"]])
    def test_dart_error(self):
        with self.assertRaises(ValueError):
            dart_rows({"status":"020"},NOW)
if __name__=="__main__":
    unittest.main()
