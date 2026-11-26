import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs,urlsplit
from smile2.media_probe import probe,google_site
class MediaProbeTests(unittest.TestCase):
    def test_site_query(self):
        self.assertEqual(parse_qs(urlsplit(google_site("newspim.com")).query)["q"],["site:newspim.com when:2d"])
    def test_classifies_aggregator_and_keeps_counts_only(self):
        xml=b'<rss><channel><item><title>test title</title><link>https://news.google.com/rss/articles/abc</link></item></channel></rss>'
        with patch("smile2.media_probe.FEEDS",{"test":("https://news.google.com/rss","aggregator","other")}),patch("smile2.media_probe.get",return_value=xml):
            r=probe()
        self.assertEqual(r["sources"][0]["link_kind"],"aggregator")
        self.assertEqual(r["rows"],1)
        self.assertNotIn("test title",str(r))
    def test_http_denial_reported(self):
        err=HTTPError("https://example.org/rss",403,"Forbidden",None,None)
        with patch("smile2.media_probe.FEEDS",{"test":("https://example.org/rss","direct","other")}),patch("smile2.media_probe.get",side_effect=err):
            r=probe()
        self.assertEqual(r["sources"][0]["http_status"],403)
        self.assertEqual(r["rows"],0)
if __name__=="__main__":
    unittest.main()
