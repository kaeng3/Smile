import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock,patch
from urllib.error import HTTPError
from news_feed.sources import fetch_checked
from smile2.capture_health import capture_health
class CaptureHealthTests(unittest.TestCase):
    def test_transient_retry_and_no_retry_on_denied(self):
        row={"published_at":"2026-11-27T09:00:00+09:00"}
        for code,retry in ((503,True),(403,False),(429,False)):
            e=HTTPError("https://example.org/rss",code,"test",{},None)
            f=Mock(side_effect=[e,[row]])
            with patch("news_feed.sources.time.sleep"):
                rows,status=fetch_checked(f,"test","https://example.org/rss")
            self.assertEqual(f.call_count,2 if retry else 1)
            self.assertEqual(status["status"],"ok" if retry else "failed")
            if not retry:self.assertEqual(status["http_status"],code)
    def test_retry_after_not_ignored(self):
        f=Mock(side_effect=HTTPError("https://example.org/rss",503,"test",{"Retry-After":"30"},None))
        self.assertEqual(fetch_checked(f,"test","https://example.org/rss")[1]["attempts"],1)
    def test_latest_health_not_full_coverage(self):
        now=datetime(2026,11,27,10,tzinfo=timezone.utc)
        stats={"capture_completed_at":now.isoformat(),"source_health":[{"source":"a","status":"ok","count":4},{"source":"b","status":"failed","http_status":403}],"score_filtered_unique_urls":3}
        r=capture_health(stats,now)
        self.assertEqual(r["status"],"partial")
        self.assertEqual(r["scope"],"latest_capture_only")
        self.assertEqual(r["ok"],1)
        self.assertEqual(capture_health(stats,now+timedelta(hours=2))["status"],"stale")
        self.assertEqual(capture_health(None,now)["status"],"unknown")
if __name__=="__main__":unittest.main()
