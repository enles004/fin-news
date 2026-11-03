import gzip
from datetime import datetime, timezone, timedelta
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from fin_news import fetch, models
from fin_news.health import SourceHealth


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


class FakeOpener:
    """Mock urllib opener for controlling HTTP responses."""
    def __init__(self, responses=None):
        self.responses = responses or []
        self.history = []

    def open(self, req, timeout=None):
        if isinstance(req, str):
            url = req
            headers = {}
        else:
            url = req.full_url
            headers = dict(req.headers)
        self.history.append((url, headers))
        if self.responses:
            resp_data, resp_headers = self.responses.pop(0)
            mock_resp = MagicMock()
            mock_resp.read.return_value = resp_data
            mock_resp.headers = resp_headers
            return mock_resp
        raise Exception("No more mocked responses")


class TestFetch(unittest.TestCase):
    def test_parse_date_samples(self):
        samples = [
            ("Tue, 03 Nov 26 11:38:28 +0700", "2026-11-03T11:38:28+07:00"),
            ("11/3/2026 10:11:00 AM", "2026-11-03T10:11:00+07:00"),
            ("Tue, 03 Nov 2026 02:54:34 GMT", "2026-11-03T02:54:34+00:00"),
            ("Tue, 03 Nov 2026 11:28:20 +07", "2026-11-03T11:28:20+07:00"),
            ("2026-11-03T04:28:20Z", "2026-11-03T04:28:20+00:00"),
            ("2026-11-03T11:28:20+07:00", "2026-11-03T11:28:20+07:00"),
        ]
        for raw, expected in samples:
            res = fetch.parse_date(raw)
            self.assertIsNotNone(res, f"Failed on raw date: {raw}")
            dt_res = datetime.fromisoformat(res)
            dt_exp = datetime.fromisoformat(expected)
            self.assertEqual(dt_res.timestamp(), dt_exp.timestamp(), f"Timestamp mismatch for {raw}")

        self.assertIsNone(fetch.parse_date(""))
        self.assertIsNone(fetch.parse_date("not a date"))
        self.assertIsNone(fetch.parse_date(None))

    def test_gzip_body_is_decompressed_even_without_header(self):
        plain_xml = (FIXTURES_DIR / "plain_rss.xml").read_bytes()
        gzipped = gzip.compress(plain_xml)
        opener = FakeOpener([(gzipped, {})])
        body = fetch.fetch_url("https://example.com/feed", opener=opener)
        self.assertEqual(body, plain_xml)

    def test_cookie_challenge_then_feed(self):
        challenge_html = (FIXTURES_DIR / "challenge_cookie.html").read_bytes()
        plain_xml = (FIXTURES_DIR / "plain_rss.xml").read_bytes()

        opener = FakeOpener([
            (challenge_html, {"Content-Type": "text/html"}),
            (plain_xml, {"Content-Type": "application/rss+xml"}),
        ])
        body = fetch.fetch_url("https://laodong.vn/rss/kinh-doanh.rss", opener=opener)
        self.assertEqual(body, plain_xml)
        self.assertEqual(len(opener.history), 2)
        # Check that cookie was sent on second request
        second_headers = opener.history[1][1]
        cookie_header = any("D1N=test_cookie_12345" in str(v) for v in second_headers.values())
        self.assertTrue(cookie_header)

    def test_malformed_xml_gives_error_health_not_exception(self):
        malformed = (FIXTURES_DIR / "malformed.xml").read_bytes()
        opener = FakeOpener([(malformed, {})])
        cfg = {"url": "https://example.com/bad.xml", "group": "test", "enabled": True}
        articles, health = fetch.fetch_source("bad_source", cfg, limit=10, opener=opener)
        self.assertEqual(len(articles), 0)
        self.assertEqual(health.status, "error")
        self.assertEqual(health.source_id, "bad_source")

    def test_empty_feed_gives_empty_health(self):
        empty_xml = (FIXTURES_DIR / "empty_feed.xml").read_bytes()
        opener = FakeOpener([(empty_xml, {})])
        cfg = {"url": "https://example.com/empty.xml", "group": "test", "enabled": True}
        articles, health = fetch.fetch_source("empty_source", cfg, limit=10, opener=opener)
        self.assertEqual(len(articles), 0)
        self.assertEqual(health.status, "empty")
        self.assertEqual(health.source_id, "empty_source")

    def test_limit_applies_newest_first_and_multi_feed_splits_quota(self):
        # Create 4 feeds each returning 5 articles with different pubDates
        def make_feed_xml(prefix, count):
            items = []
            for i in range(count):
                items.append(f"""
                <item>
                  <title>{prefix} Article {i}</title>
                  <link>https://example.com/{prefix}/{i}</link>
                  <description>Summary</description>
                  <pubDate>Tue, 03 Nov 2026 {10 + i:02d}:00:00 +0700</pubDate>
                </item>
                """)
            return f"""<rss version="2.0"><channel><title>{prefix}</title>{"".join(items)}</channel></rss>""".encode("utf-8")

        f1 = make_feed_xml("f1", 5)
        f2 = make_feed_xml("f2", 5)
        f3 = make_feed_xml("f3", 5)
        f4 = make_feed_xml("f4", 5)

        opener = FakeOpener([(f1, {}), (f2, {}), (f3, {}), (f4, {})])
        cfg = {
            "url": [
                "https://example.com/f1.rss",
                "https://example.com/f2.rss",
                "https://example.com/f3.rss",
                "https://example.com/f4.rss",
            ],
            "group": "test",
            "enabled": True,
        }
        articles, health = fetch.fetch_source("multi", cfg, limit=10, opener=opener)
        self.assertEqual(health.status, "ok")
        self.assertLessEqual(len(articles), 10)
        # Check that each feed provided at least 1 article
        feed_prefixes = set(a.url.split("/")[3] for a in articles)
        self.assertEqual(len(feed_prefixes), 4)

    def test_description_html_and_cdata_are_stripped(self):
        cdata_xml = (FIXTURES_DIR / "cdata_html_desc.xml").read_bytes()
        articles = fetch.parse_feed(cdata_xml, "test_source", "test_group")
        self.assertEqual(len(articles), 1)
        art = articles[0]
        self.assertNotIn("<p>", art.summary_raw)
        self.assertNotIn("<i>", art.summary_raw)
        self.assertIn("thẻ html", art.summary_raw)
        self.assertIn('"kèm ngoặc kép"', art.summary_raw)
        self.assertNotIn("<b>", art.title)
        self.assertIn("Tiêu đề in đậm & có dấu", art.title)

    def test_article_without_date_kept_with_published_at_none(self):
        xml_no_date = b"""<rss version="2.0"><channel><item>
            <title>No Date</title>
            <link>https://example.com/nodate</link>
            <description>Desc</description>
        </item></channel></rss>"""
        articles = fetch.parse_feed(xml_no_date, "test_source", "test_group")
        self.assertEqual(len(articles), 1)
        self.assertIsNone(articles[0].published_at)

    def test_one_failing_source_does_not_fail_fetch_all(self):
        plain_xml = (FIXTURES_DIR / "plain_rss.xml").read_bytes()
        opener = FakeOpener([
            (plain_xml, {}),
            (b"malformed...", {}),
        ])
        sources_cfg = {
            "s1": {"url": "https://example.com/ok.rss", "group": "g1", "enabled": True},
            "s2": {"url": "https://example.com/fail.rss", "group": "g1", "enabled": True},
        }
        articles, healths = fetch.fetch_all(sources_cfg, limit=10, opener=opener)
        self.assertGreaterEqual(len(articles), 1)
        health_by_id = {h.source_id: h.status for h in healths}
        self.assertEqual(health_by_id.get("s1"), "ok")
        self.assertEqual(health_by_id.get("s2"), "error")


if __name__ == "__main__":
    unittest.main()
