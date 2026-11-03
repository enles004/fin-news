from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import support

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from fin_news import health, doctor, config, pipeline
from fin_news.health import SourceHealth


class TestHealth(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_home = os.environ.get("FIN_NEWS_HOME")
        os.environ["FIN_NEWS_HOME"] = self.temp_dir

    def tearDown(self):
        if self.old_home is not None:
            os.environ["FIN_NEWS_HOME"] = self.old_home
        else:
            os.environ.pop("FIN_NEWS_HOME", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_health_render_all_ok(self):
        healths = [
            SourceHealth("s1", "ok", "10 articles", "2026-11-03T10:00:00Z"),
            SourceHealth("s2", "ok", "5 articles", "2026-11-03T10:00:00Z"),
        ]
        text = health.render(healths)
        self.assertIn("Tất cả nguồn hoạt động bình thường.", text)

    def test_health_render_lists_only_failures_with_since_date(self):
        healths = [
            SourceHealth("s_ok", "ok", "10 articles", "2026-11-03T10:00:00Z"),
            SourceHealth("s_err", "error", "Connection timed out", "2026-11-03T10:00:00Z"),
        ]
        text = health.render(healths)
        self.assertNotIn("s_ok", text)
        self.assertIn("s_err", text)
        self.assertIn("Connection timed out", text)
        self.assertIn("lỗi từ", text)

    def test_health_since_date_uses_last_ok_record(self):
        # Step 1: record an OK state on 2026-11-01
        h_ok = [SourceHealth("s1", "ok", "10 articles", "2026-11-01T08:00:00Z")]
        health.record(h_ok)

        # Step 2: render with an error state on 2026-11-03
        h_err = [SourceHealth("s1", "error", "404 Not Found", "2026-11-03T10:00:00Z")]
        text = health.render(h_err)
        self.assertIn("s1", text)
        self.assertIn("404 Not Found", text)
        self.assertIn("2026-11-01", text)

    def test_doctor_flags_unwritable_home(self):
        # Point FIN_NEWS_HOME to a non-existent or read-only directory
        unwritable = Path(self.temp_dir) / "unwritable"
        unwritable.mkdir()
        # On windows, remove write permission
        os.chmod(unwritable, 0o444)
        os.environ["FIN_NEWS_HOME"] = str(unwritable)

        # Doctor checks
        results = doctor.run(check_network=False, check_sources=False)
        # Find home writable check
        home_check = next((c for c in results if "home" in c[0].lower() or "writable" in c[0].lower()), None)
        self.assertIsNotNone(home_check)
        # Note: on Windows, chmod 444 might still allow writing for administrator,
        # but let's test doctor.check_home_writable with a mocked failing path
        mock_res = doctor.check_home_writable(Path("Z:\\nonexistent_drive_999\\fin_news"))
        self.assertFalse(mock_res[1])

    def test_fulltext_health_persists_since_and_resets_on_full(self):
        # Day 1: degraded
        health.record_fulltext_health([{"source": "srcA", "status": "degraded", "tier": "hint"}], date_str="2026-11-01")
        d1 = health.load_fulltext_health()
        self.assertEqual(d1["srcA"]["status"], "degraded")
        self.assertEqual(d1["srcA"]["since"], "2026-11-01")

        # Day 2: summary_only -> since stays 2026-11-01
        health.record_fulltext_health([{"source": "srcA", "status": "summary_only", "tier": ""}], date_str="2026-11-02")
        d2 = health.load_fulltext_health()
        self.assertEqual(d2["srcA"]["status"], "summary_only")
        self.assertEqual(d2["srcA"]["since"], "2026-11-01")

        # Day 3: full -> since resets to None, last_full is updated
        health.record_fulltext_health([{"source": "srcA", "status": "full", "tier": "json-ld"}], date_str="2026-11-03")
        d3 = health.load_fulltext_health()
        self.assertEqual(d3["srcA"]["status"], "full")
        self.assertIsNone(d3["srcA"]["since"])
        self.assertEqual(d3["srcA"]["last_full"], "2026-11-03")

        # Day 4: degraded again -> new streak starting 2026-11-04
        health.record_fulltext_health([{"source": "srcA", "status": "degraded", "tier": "density"}], date_str="2026-11-04")
        d4 = health.load_fulltext_health()
        self.assertEqual(d4["srcA"]["status"], "degraded")
        self.assertEqual(d4["srcA"]["since"], "2026-11-04")
        self.assertEqual(d4["srcA"]["last_full"], "2026-11-03")

    def test_health_render_lists_degraded_and_summary_only_sources(self):
        health.record_fulltext_health([
            {"source": "src_deg", "status": "degraded", "tier": "density"},
            {"source": "src_sum", "status": "summary_only", "tier": ""},
        ], date_str="2026-11-02")

        rendered = health.render([])
        self.assertIn("### Toàn văn", rendered)
        self.assertIn("src_deg: trích xuất dự phòng (tầng density, từ 2026-11-02)", rendered)
        self.assertIn("src_sum: chỉ có tóm tắt RSS (từ 2026-11-02)", rendered)

    def test_health_render_unchanged_when_all_full(self):
        health.record_fulltext_health([
            {"source": "src_ok", "status": "full", "tier": "article"},
        ], date_str="2026-11-03")

        h_ok = [SourceHealth("src_conn", "ok", "10 articles", "2026-11-03T10:00:00Z")]
        rendered = health.render(h_ok)
        self.assertEqual(rendered, "Tất cả nguồn hoạt động bình thường.")

    def test_fulltext_command_updates_fulltext_health(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)

        articles = [
            {"id": "art-fh1", "source": "src1", "title": "Tin tức thị trường chứng khoán", "url": "https://example.com/art1", "summary_raw": "Tóm tắt"}
        ]
        clusters = [
            {"cluster_id": "c-001", "headline": "Tin tức thị trường chứng khoán", "article_ids": ["art-fh1"]}
        ]
        (data_dir / "articles.json").write_text(json.dumps(articles, ensure_ascii=False), encoding="utf-8")
        (data_dir / "clusters.json").write_text(json.dumps(clusters, ensure_ascii=False), encoding="utf-8")

        # Mock fetch to return valid HTML
        from fin_news import fetch
        from unittest.mock import MagicMock
        mock_opener = MagicMock()
        full_html = "<html><body><article><p>" + "Tin tức thị trường chứng khoán phục vụ kiểm tra toàn văn dữ liệu. " * 6 + "</p></article></body></html>"
        resp = MagicMock()
        resp.read.return_value = full_html.encode("utf-8")
        resp.headers = {}
        mock_opener.open.return_value = resp

        old_opener = fetch._DEFAULT_OPENER
        fetch._DEFAULT_OPENER = mock_opener
        try:
            pipeline.run_fulltext(["c-001"])
        finally:
            fetch._DEFAULT_OPENER = old_opener

        fh_data = health.load_fulltext_health()
        self.assertIn("src1", fh_data)
        self.assertEqual(fh_data["src1"]["status"], "full")


if __name__ == "__main__":
    unittest.main()
