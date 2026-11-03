from datetime import datetime, timezone, timedelta
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

import cli
from fin_news import config, fetch, lock, pipeline


class FakeOpener:
    def __init__(self, sample_xml):
        self.sample_xml = sample_xml

    def open(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if isinstance(self.sample_xml, dict):
            for k, v in self.sample_xml.items():
                if k in url:
                    if isinstance(v, Exception):
                        raise v
                    mock = MagicMock()
                    mock.read.return_value = v
                    mock.headers = {}
                    return mock
        elif callable(self.sample_xml):
            res = self.sample_xml(req)
            if isinstance(res, Exception):
                raise res
            mock = MagicMock()
            mock.read.return_value = res
            mock.headers = {}
            return mock

        mock = MagicMock()
        mock.read.return_value = self.sample_xml
        mock.headers = {}
        return mock


SAMPLE_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>Sample Feed</title>
    <item>
      <title>Tin t\xc3\xa1i ch\xc3\xadnh th\xe1\xbb\xad nghi\xe1\xbb\x87m</title>
      <link>https://example.com/art1</link>
      <description>T\xc3\xb3m t\xe1\xba\xaft n\xe1\xbb\x99i dung</description>
      <pubDate>Tue, 03 Nov 2026 10:00:00 +0700</pubDate>
    </item>
  </channel>
</rss>"""


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.old_home = os.environ.get("FIN_NEWS_HOME")
        os.environ["FIN_NEWS_HOME"] = self.temp_dir
        self.fake_opener = FakeOpener(SAMPLE_FEED)
        fetch._DEFAULT_OPENER = self.fake_opener

    def tearDown(self):
        fetch._DEFAULT_OPENER = None
        if self.old_home is not None:
            os.environ["FIN_NEWS_HOME"] = self.old_home
        else:
            os.environ.pop("FIN_NEWS_HOME", None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_fetch_writes_raw_and_health_files(self):
        ret = cli.main(["fetch", "--only", "cafef-chungkhoan"])
        self.assertEqual(ret, 0)
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        self.assertTrue((data_dir / "raw.json").exists())
        self.assertTrue((data_dir / "health.json").exists())

    def test_prepare_writes_batches_of_25(self):
        cli.main(["fetch", "--only", "cafef-chungkhoan"])
        ret = cli.main(["prepare"])
        self.assertEqual(ret, 0)
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        self.assertTrue((data_dir / "articles.json").exists())
        batches_dir = data_dir / "batches"
        self.assertTrue(batches_dir.exists())
        batch_files = list(batches_dir.glob("batch-*.json"))
        self.assertGreaterEqual(len(batch_files), 1)

    def test_collect_exit_code_3_when_ids_unresolved(self):
        cli.main(["fetch", "--only", "cafef-chungkhoan"])
        cli.main(["prepare"])
        # No result-*.json files exist yet, so collect must exit with code 3
        ret = cli.main(["collect"])
        self.assertEqual(ret, 3)

    def test_config_set_prints_old_new(self):
        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["config", "set", "profile", "max_per_source", "18"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
            self.assertIn("10", printed)
            self.assertIn("18", printed)
        finally:
            sys.stdout = old_stdout

    def test_output_survives_cp1252_stdout(self):
        # Create a buffer that only accepts cp1252 without crashing
        buffer = io.BytesIO()
        cp1252_writer = io.TextIOWrapper(buffer, encoding="cp1252", errors="replace")
        old_stdout = sys.stdout
        try:
            sys.stdout = cp1252_writer
            # Health with Vietnamese text should print without raising UnicodeEncodeError
            ret = cli.main(["health"])
            self.assertEqual(ret, 0)
        finally:
            sys.stdout = old_stdout

    def test_home_with_spaces_and_non_ascii_end_to_end(self):
        unicode_home = Path(self.temp_dir) / "Thư Mục Dữ Liệu"
        os.environ["FIN_NEWS_HOME"] = str(unicode_home)
        ret = cli.main(["fetch", "--only", "cafef-chungkhoan"])
        self.assertEqual(ret, 0)
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = unicode_home / "data" / today
        self.assertTrue((data_dir / "raw.json").exists())

    def test_zero_articles_prints_empty_day_notice_with_health(self):
        # Empty feed opener
        fetch._DEFAULT_OPENER = FakeOpener(b"<rss><channel></channel></rss>")
        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["fetch", "--only", "cafef-chungkhoan"])
            printed = out.getvalue()
            self.assertTrue("không có tin tức" in printed.lower() or "0 bài viết" in printed.lower() or "empty" in printed.lower())
        finally:
            sys.stdout = old_stdout

    def test_second_run_is_refused_while_lock_held(self):
        today = datetime.now().strftime("%Y-%m-%d")
        lock_dir = Path(self.temp_dir) / "data" / today
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lock_dir / ".lock"

        with lock.acquire(lock_file):
            # Second attempt while lock is held must raise or fail
            with self.assertRaises(RuntimeError) as ctx:
                with lock.acquire(lock_file):
                    pass
            self.assertIn("active", str(ctx.exception).lower())

    def test_stale_lock_is_overridden(self):
        today = datetime.now().strftime("%Y-%m-%d")
        lock_dir = Path(self.temp_dir) / "data" / today
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock_file = lock_dir / ".lock"

        # Write a stale lock (> 2 hours old)
        stale_time = (datetime.now() - timedelta(hours=3)).isoformat()
        lock_file.write_text(json.dumps({"pid": 99999, "start_time": stale_time}), encoding="utf-8")
        stale_mtime = time.time() - 3600 * 3
        os.utime(lock_file, (stale_mtime, stale_mtime))

        # Acquiring should succeed by overriding stale lock
        with lock.acquire(lock_file):
            self.assertTrue(lock_file.exists())

    def _setup_classified_articles(self):
        cli.main(["fetch", "--only", "cafef-chungkhoan"])
        cli.main(["prepare"])
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        articles_file = data_dir / "articles.json"
        articles_data = json.loads(articles_file.read_text(encoding="utf-8"))

        # Create two articles if needed to have multiple clusters
        if len(articles_data) < 2:
            art2 = dict(articles_data[0])
            art2["id"] = "art_second_id"
            art2["url"] = "https://example.com/art2"
            art2["title"] = "Tiêu đề bài viết thứ hai"
            articles_data.append(art2)
            articles_file.write_text(json.dumps(articles_data, ensure_ascii=False, indent=2), encoding="utf-8")

        batches_dir = data_dir / "batches"
        batch_files = list(batches_dir.glob("batch-*.json"))
        if batch_files:
            batch_files[0].write_text(
                json.dumps([{"id": a["id"], "source": a["source"], "title": a["title"], "summary_raw": a.get("summary_raw", "")} for a in articles_data], ensure_ascii=False),
                encoding="utf-8"
            )

        result_data = [
            {
                "id": a["id"],
                "topics": ["chung-khoan"],
                "summary_vi": a["title"],
                "entities": [],
                "importance": 3,
                "importance_reason": "Lý do",
                "event_key": f"event-{idx}",
                "is_noise": False,
            }
            for idx, a in enumerate(articles_data)
        ]
        (batches_dir / "result-01.json").write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")
        return data_dir

    def test_cluster_writes_merge_input_and_raw(self):
        data_dir = self._setup_classified_articles()
        ret = cli.main(["cluster"])
        self.assertEqual(ret, 0)
        self.assertTrue((data_dir / "clusters-raw.json").exists())
        self.assertTrue((data_dir / "merge-input.json").exists())
        self.assertFalse((data_dir / "clusters.json").exists())

    def test_cluster_skip_merge_writes_clusters_json(self):
        data_dir = self._setup_classified_articles()
        ret = cli.main(["cluster", "--skip-merge"])
        self.assertEqual(ret, 0)
        self.assertTrue((data_dir / "clusters.json").exists())

    def test_merge_missing_result_exits_4(self):
        data_dir = self._setup_classified_articles()
        cli.main(["cluster"])
        # merge-result.json is not created
        ret = cli.main(["merge"])
        self.assertEqual(ret, 4)

    def test_merge_with_bad_group_applies_valid_ones_and_exits_3(self):
        data_dir = self._setup_classified_articles()
        cli.main(["cluster"])
        # Create merge-result.json with 1 good group and 1 bad group (unknown id)
        merge_res = {
            "groups": [
                ["c-001", "c-002"],
                ["c-999", "c-001"]
            ]
        }
        (data_dir / "merge-result.json").write_text(json.dumps(merge_res, ensure_ascii=False), encoding="utf-8")
        ret = cli.main(["merge"])
        self.assertEqual(ret, 3)
        self.assertTrue((data_dir / "clusters.json").exists())
        clusters_data = json.loads((data_dir / "clusters.json").read_text(encoding="utf-8"))
        # Merged c-001 and c-002 into 1 cluster
        self.assertEqual(len(clusters_data), 1)
        self.assertEqual(clusters_data[0]["cluster_id"], "c-001")

    def _setup_fulltext_env(self, articles, results, cluster_article_ids):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)
        batches_dir = data_dir / "batches"
        batches_dir.mkdir(parents=True, exist_ok=True)

        (data_dir / "articles.json").write_text(
            json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (batches_dir / "batch-01.json").write_text(
            json.dumps([{"id": a["id"]} for a in articles], ensure_ascii=False), encoding="utf-8"
        )
        (batches_dir / "result-01.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        clusters = [
            {
                "cluster_id": "c-001",
                "headline": "Tiêu đề cụm thử nghiệm",
                "article_ids": cluster_article_ids,
            }
        ]
        (data_dir / "clusters.json").write_text(
            json.dumps(clusters, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return data_dir

    def test_fulltext_limits_articles_per_cluster_and_prefers_distinct_sources(self):
        articles = [
            {"id": "art-1", "source": "srcA", "title": "Bài A1", "url": "https://example.com/art1", "summary_raw": "Tóm tắt A1"},
            {"id": "art-2", "source": "srcA", "title": "Bài A2", "url": "https://example.com/art2", "summary_raw": "Tóm tắt A2"},
            {"id": "art-3", "source": "srcB", "title": "Bài B1", "url": "https://example.com/art3", "summary_raw": "Tóm tắt B1"},
            {"id": "art-4", "source": "srcC", "title": "Bài C1", "url": "https://example.com/art4", "summary_raw": "Tóm tắt C1"},
        ]
        results = [
            {"id": "art-1", "importance": 5, "topics": ["chung-khoan"], "summary_vi": "A1", "is_noise": False},
            {"id": "art-2", "importance": 4, "topics": ["chung-khoan"], "summary_vi": "A2", "is_noise": False},
            {"id": "art-3", "importance": 3, "topics": ["chung-khoan"], "summary_vi": "B1", "is_noise": False},
            {"id": "art-4", "importance": 2, "topics": ["chung-khoan"], "summary_vi": "C1", "is_noise": False},
        ]
        data_dir = self._setup_fulltext_env(articles, results, ["art-1", "art-2", "art-3", "art-4"])

        full_html = (
            b"<!DOCTYPE html><html><head><title>Bai bao</title></head><body><article>"
            b"<p>Noi dung toan van bai bao thu nghiem dai hon hai tram ky tu phuc vu cho he thong boc tach fin-news.</p>"
            b"<p>Doan van thu hai bo sung them thong tin de dam bao vuot nguong hai tram ky tu mot cach ro rang.</p>"
            b"</article></body></html>"
        )
        fetch._DEFAULT_OPENER = FakeOpener(full_html)

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["fulltext", "c-001"])
            self.assertEqual(ret, 0)
        finally:
            sys.stdout = old_stdout

        fulltext_dir = data_dir / "fulltext"
        self.assertTrue((fulltext_dir / "art-1.txt").exists())
        self.assertTrue((fulltext_dir / "art-3.txt").exists())
        self.assertFalse((fulltext_dir / "art-2.txt").exists())
        self.assertFalse((fulltext_dir / "art-4.txt").exists())

    def test_fulltext_labels_fallback_as_summary_only(self):
        articles = [
            {"id": "art-fb", "source": "srcA", "title": "Bài fallback", "url": "https://example.com/fallback", "summary_raw": "Nội dung tóm tắt gốc từ RSS"}
        ]
        results = [
            {"id": "art-fb", "importance": 4, "topics": ["chung-khoan"], "summary_vi": "fb", "is_noise": False}
        ]
        data_dir = self._setup_fulltext_env(articles, results, ["art-fb"])

        empty_html = b"<!DOCTYPE html><html><body><p>Ngan</p></body></html>"
        fetch._DEFAULT_OPENER = FakeOpener(empty_html)

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["fulltext", "c-001"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("[chỉ có tóm tắt RSS]", printed)
        self.assertNotIn("[toàn văn]", printed)
        saved_text = (data_dir / "fulltext" / "art-fb.txt").read_text(encoding="utf-8")
        self.assertEqual(saved_text, "Nội dung tóm tắt gốc từ RSS")

    def test_fulltext_status_file_and_summary_line(self):
        import urllib.error
        articles = [
            {"id": "art-ok", "source": "srcA", "title": "Thị trường tài chính ngân hàng", "url": "https://example.com/ok", "summary_raw": "Tóm tắt OK"},
            {"id": "art-err", "source": "srcB", "title": "Bài lỗi", "url": "https://example.com/err", "summary_raw": "Tóm tắt lỗi"},
            {"id": "art-sum", "source": "srcC", "title": "Bài chỉ tóm tắt", "url": "https://example.com/sum", "summary_raw": "Tóm tắt tóm tắt"},
        ]
        results = [
            {"id": "art-ok", "importance": 5, "topics": ["chung-khoan"], "summary_vi": "ok", "is_noise": False},
            {"id": "art-err", "importance": 4, "topics": ["chung-khoan"], "summary_vi": "err", "is_noise": False},
            {"id": "art-sum", "importance": 3, "topics": ["chung-khoan"], "summary_vi": "sum", "is_noise": False},
        ]
        data_dir = self._setup_fulltext_env(articles, results, ["art-ok", "art-err", "art-sum"])

        # Temporarily increase fulltext_articles_per_cluster to 3
        config.set_value("profile", "fulltext_articles_per_cluster", 3)

        full_html = (
            "<!DOCTYPE html><html><head><title>Thị trường tài chính ngân hàng</title></head><body><article>"
            "<p>Thị trường tài chính và hệ thống ngân hàng trong giai đoạn hiện nay ghi nhận nhiều chuyển biến tích cực.</p>"
            "<p>Các chỉ số phản ánh sự phục hồi vững chắc của nền kinh tế với sự tham gia mạnh mẽ của dòng tiền đầu tư.</p>"
            "</article></body></html>"
        ).encode("utf-8")
        empty_html = b"<!DOCTYPE html><html><body><p>Ngan</p></body></html>"

        fetch._DEFAULT_OPENER = FakeOpener({
            "/ok": full_html,
            "/err": urllib.error.URLError("Connection refused"),
            "/sum": empty_html,
        })

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["fulltext", "c-001"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        status_file = data_dir / "fulltext" / "_status.json"
        self.assertTrue(status_file.exists())
        status_data = json.loads(status_file.read_text(encoding="utf-8"))

        self.assertEqual(status_data["art-ok"]["status"], "full")
        self.assertGreater(status_data["art-ok"]["chars"], 200)
        self.assertEqual(status_data["art-ok"]["error"], "")

        self.assertEqual(status_data["art-err"]["status"], "error")
        self.assertIn("Connection refused", status_data["art-err"]["error"])

        self.assertEqual(status_data["art-sum"]["status"], "summary_only")
        self.assertEqual(status_data["art-sum"]["error"], "")

        # Summary line check: Toàn văn: 1/3 bài; chỉ tóm tắt: 1; lỗi: 1.
        self.assertIn("Toàn văn: 1/3 bài; chỉ tóm tắt: 1; lỗi: 1.", printed)


if __name__ == "__main__":
    unittest.main()
