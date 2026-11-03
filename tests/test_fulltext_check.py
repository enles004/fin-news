from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock
import urllib.error

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import support

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from fin_news import config, extract, fulltext_check


class FakeOpener:
    def __init__(self, responses=None):
        self.responses = responses or {}

    def open(self, req, timeout=None):
        url = req if isinstance(req, str) else req.full_url
        if url in self.responses:
            data = self.responses[url]
            if isinstance(data, Exception):
                raise data
            mock = MagicMock()
            mock.read.return_value = data
            mock.headers = {}
            return mock
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


SAMPLE_RSS = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Sample Feed</title>
    <item>
      <title>Tin tức tài chính thử nghiệm</title>
      <link>https://example.com/art1</link>
      <description>Tóm tắt nội dung bài báo tài chính.</description>
      <pubDate>Tue, 03 Nov 2026 10:00:00 +0700</pubDate>
    </item>
  </channel>
</rss>""".encode("utf-8")


class TestFulltextCheck(unittest.TestCase):
    def setUp(self):
        self._home_cm = support.isolated_home()
        self.temp_home = self._home_cm.__enter__()
        self.cfg = {
            "url": "https://example.com/rss",
            "kind": "rss",
            "group": "general",
            "enabled": True,
        }
        self.profile = {
            "fulltext_max_chars": 3500,
            "body_hints": [],
        }

    def tearDown(self):
        self._home_cm.__exit__(None, None, None)

    def test_check_source_full_when_json_ld(self):
        long_body = "Tin tức tài chính thử nghiệm từ NewsArticle schema JSON-LD rất chi tiết và đầy đủ thông tin phục vụ kiểm thử. " * 5
        page_html = f"""<!DOCTYPE html>
        <html><head>
          <script type="application/ld+json">
          {{"@type": "NewsArticle", "articleBody": "{long_body}"}}
          </script>
        </head><body></body></html>""".encode("utf-8")

        opener = FakeOpener({
            "https://example.com/rss": SAMPLE_RSS,
            "https://example.com/art1": page_html,
        })

        res = fulltext_check.check_source("test-src", self.cfg, self.profile, opener=opener)
        self.assertEqual(res["status"], "full")
        self.assertEqual(res["tier"], "json-ld")
        self.assertGreaterEqual(res["chars"], 300)
        self.assertEqual(res["error"], "")

    def test_check_source_degraded_on_density_tier(self):
        p1 = "Tin tức tài chính thử nghiệm mật độ cao thứ nhất dài hơn bốn mươi ký tự nhằm kiểm tra tầng dự phòng density. " * 3
        p2 = "Đoạn văn mật độ cao thứ hai bổ sung thêm số liệu kinh tế đảm bảo độ dài trên ba trăm ký tự. " * 3
        page_html = f"""<!DOCTYPE html>
        <html><body>
          <div class="unknown-layout-box">
            <p>{p1}</p>
            <p>{p2}</p>
          </div>
        </body></html>""".encode("utf-8")

        opener = FakeOpener({
            "https://example.com/rss": SAMPLE_RSS,
            "https://example.com/art1": page_html,
        })

        res = fulltext_check.check_source("test-src", self.cfg, self.profile, opener=opener)
        self.assertEqual(res["status"], "degraded")
        self.assertEqual(res["tier"], "density")
        self.assertGreaterEqual(res["chars"], 300)

    def test_check_source_summary_only_when_empty(self):
        page_html = b"<html><body><p>Ngan</p></body></html>"
        opener = FakeOpener({
            "https://example.com/rss": SAMPLE_RSS,
            "https://example.com/art1": page_html,
        })

        res = fulltext_check.check_source("test-src", self.cfg, self.profile, opener=opener)
        self.assertEqual(res["status"], "summary_only")

    def test_check_source_error_on_fetch_failure(self):
        opener = FakeOpener({
            "https://example.com/rss": SAMPLE_RSS,
            "https://example.com/art1": urllib.error.URLError("Connection refused"),
        })

        res = fulltext_check.check_source("test-src", self.cfg, self.profile, opener=opener)
        self.assertEqual(res["status"], "error")
        self.assertIn("Connection refused", res["error"])

    def test_check_source_full_when_hint_tier_has_enough_text(self):
        p1 = "Tin tức tài chính thử nghiệm trong tầng hint có độ dài đầy đủ hơn ba trăm ký tự phục vụ kiểm thử. " * 3
        p2 = "Đoạn văn tiếp theo đảm bảo tổng số lượng ký tự vượt xa ngưỡng ba trăm một cách chắc chắn và ổn định. " * 3
        page_html = f"""<!DOCTYPE html>
        <html><body>
          <div class="article-body">
            <p>{p1}</p>
            <p>{p2}</p>
          </div>
        </body></html>""".encode("utf-8")

        opener = FakeOpener({
            "https://example.com/rss": SAMPLE_RSS,
            "https://example.com/art1": page_html,
        })

        res = fulltext_check.check_source("test-src", self.cfg, self.profile, opener=opener)
        self.assertEqual(res["status"], "full")
        self.assertEqual(res["tier"], "hint")
        self.assertGreaterEqual(res["chars"], 300)

    def test_check_source_reports_best_of_three_samples(self):
        rss_three = """<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0">
          <channel>
            <title>Three Feed</title>
            <item>
              <title>Bài 1 tóm tắt ngắn</title>
              <link>https://example.com/sample1</link>
              <pubDate>Tue, 03 Nov 2026 10:05:00 +0700</pubDate>
            </item>
            <item>
              <title>Bài 2 toàn văn đầy đủ</title>
              <link>https://example.com/sample2</link>
              <pubDate>Tue, 03 Nov 2026 10:04:00 +0700</pubDate>
            </item>
            <item>
              <title>Bài 3 lỗi mạng</title>
              <link>https://example.com/sample3</link>
              <pubDate>Tue, 03 Nov 2026 10:03:00 +0700</pubDate>
            </item>
          </channel>
        </rss>""".encode("utf-8")

        html_short = b"<html><body><p>Ngan</p></body></html>"
        p_long = "Nội dung toàn văn bài báo thứ hai đạt chuẩn bài viết dài hơn ba trăm ký tự rất rõ ràng và chuẩn xác. " * 5
        html_full = f"<html><body><article><p>{p_long}</p></article></body></html>".encode("utf-8")

        opener = FakeOpener({
            "https://example.com/rss": rss_three,
            "https://example.com/sample1": html_short,
            "https://example.com/sample2": html_full,
            "https://example.com/sample3": urllib.error.URLError("Connection refused"),
        })

        res = fulltext_check.check_source("test-src", self.cfg, self.profile, opener=opener)
        self.assertEqual(res["status"], "full")
        self.assertEqual(res["url"], "https://example.com/sample2")
        self.assertEqual(res["tier"], "article")
        self.assertGreaterEqual(res["chars"], 300)

    def test_config_set_body_hints_changes_extraction(self):
        p_text = "Nội dung bài viết nằm trong container đặc thù cần có gợi ý cấu hình mới bóc tách được đúng tầng hint. " * 4
        synthetic_html = f"""<!DOCTYPE html>
        <html><body>
          <div class="custom-synthetic-container">
            <p>{p_text}</p>
          </div>
        </body></html>"""

        # Without hint -> falls back to density tier
        text_before, tier_before = extract.extract_with_tier(synthetic_html)
        self.assertEqual(tier_before, "density")

        # Set hint via config
        config.set_value("sources", "sources.synth-src.body_hints", ["custom-synthetic-container"])
        sources_cfg = config.load("sources")
        effective_hints = fulltext_check.get_effective_hints("synth-src", sources_cfg, self.profile)
        self.assertIn("custom-synthetic-container", effective_hints)

        # With hint -> successfully uses hint tier
        text_after, tier_after = extract.extract_with_tier(synthetic_html, hints=effective_hints)
        self.assertEqual(tier_after, "hint")
        self.assertIn("container đặc thù", text_after)

    def test_effective_hints_merge_source_and_global_without_duplicates(self):
        src_cfg = {
            "sources": {
                "demo": {"body_hints": ["hint-a", "hint-shared"]}
            }
        }
        profile_cfg = {
            "body_hints": ["hint-shared", "hint-c", "hint-d"]
        }
        merged = fulltext_check.get_effective_hints("demo", src_cfg, profile_cfg)
        self.assertEqual(merged, ("hint-a", "hint-shared", "hint-c", "hint-d"))


if __name__ == "__main__":
    unittest.main()
