import unittest
from smile2.benchmark import report_links,compare
class BenchmarkTests(unittest.TestCase):
    def test_local_reference_aggregate_only(self):
        html='<a href="https://news.example/a?utm_source=x">private title</a><a href="https://thealphahorizon.com/report">internal</a><a href="javascript:alert(1)">bad</a><a href="https://news.example/b">private title 2</a>'
        links=report_links(html)
        r=compare(links,[{"url":"https://news.example/a"}])
        self.assertEqual(r["reference_external_links"],2)
        self.assertEqual(r["exact_url_matches"],1)
        self.assertEqual(r["exact_url_coverage_pct"],50)
        self.assertNotIn("private title",str(r))
        self.assertNotIn("https://news.example/b",str(r))
    def test_host_filter(self):
        self.assertEqual(report_links('<a href="https://notexample.org/a">X</a><a href="https://news.example.org/a">Y</a>',['example.org']),{'https://news.example.org/a'})
    def test_empty(self):
        self.assertIsNone(compare(set(),[])["exact_url_coverage_pct"])
if __name__=="__main__":
    unittest.main()
