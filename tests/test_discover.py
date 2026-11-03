from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import support

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from fin_news import discover, config
from fin_news.models import Article


class FakeOpener:
    def __init__(self, responses=None):
        self.responses = responses or {}

    def open(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if url in self.responses:
            data = self.responses[url]
            mock = MagicMock()
            mock.read.return_value = data
            mock.headers = {}
            return mock
        raise Exception(f"404 Not Found: {url}")


class TestDiscover(unittest.TestCase):
    def setUp(self):
        self._home_cm = support.isolated_home()
        self.temp_home = self._home_cm.__enter__()

    def tearDown(self):
        self._home_cm.__exit__(None, None, None)
    def test_discover_finds_link_alternate(self):
        html_page = b"""
        <html>
        <head>
          <link rel="alternate" type="application/rss+xml" title="RSS" href="/rss/feed.xml" />
        </head>
        <body>Hello</body>
        </html>
        """
        sample_rss = b"""<rss version="2.0"><channel><item><title>A</title><link>https://example.com/1</link></item></channel></rss>"""
        opener = FakeOpener({
            "https://example.com": html_page,
            "https://example.com/rss/feed.xml": sample_rss,
        })
        feeds = discover.discover_feeds("https://example.com", opener=opener)
        self.assertEqual(feeds, ["https://example.com/rss/feed.xml"])

    def test_discover_falls_back_to_common_path(self):
        html_page = b"<html><head><title>No Feeds</title></head><body>No link tags</body></html>"
        sample_rss = b"""<rss version="2.0"><channel><item><title>A</title><link>https://example.com/1</link></item></channel></rss>"""
        opener = FakeOpener({
            "https://example.com": html_page,
            "https://example.com/rss": sample_rss,
        })
        feeds = discover.discover_feeds("https://example.com", opener=opener)
        self.assertEqual(feeds, ["https://example.com/rss"])

    def test_add_source_saves_and_returns_sample_titles(self):
        html_page = b"""<html><head><link rel="alternate" type="application/rss+xml" href="https://example.com/feed.xml" /></head></html>"""
        sample_rss = b"""<rss version="2.0"><channel>
          <item><title>Sample Title 1</title><link>https://example.com/1</link></item>
          <item><title>Sample Title 2</title><link>https://example.com/2</link></item>
        </channel></rss>"""
        opener = FakeOpener({
            "https://example.com": html_page,
            "https://example.com/feed.xml": sample_rss,
        })
        res = discover.add_source("https://example.com", source_id="test-src", group="test-grp", opener=opener)
        self.assertEqual(res.get("source_id"), "test-src")
        self.assertIn("https://example.com/feed.xml", res.get("feed_urls", []))
        self.assertIn("Sample Title 1", res.get("sample_titles", []))

        # Check saved in config
        sources = config.load("sources")
        self.assertIn("test-src", sources.get("sources", {}))

    def test_add_source_without_feed_saves_nothing(self):
        html_page = b"<html><head><title>No Feeds</title></head><body>No RSS here</body></html>"
        opener = FakeOpener({"https://example.com/no-feed": html_page})
        res = discover.add_source("https://example.com/no-feed", source_id="no-feed", group="test", opener=opener)
        self.assertFalse(res.get("found"))
        self.assertEqual(res.get("hint"), "scrape")

        # Verify nothing saved
        sources = config.load("sources")
        self.assertNotIn("no-feed", sources.get("sources", {}))


if __name__ == "__main__":
    unittest.main()
