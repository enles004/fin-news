from datetime import datetime, timezone, timedelta
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import support

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
            for k in sorted(self.sample_xml.keys(), key=len, reverse=True):
                if k in url:
                    v = self.sample_xml[k]
                    if isinstance(v, Exception):
                        raise v
                    mock = MagicMock()
                    mock.read.return_value = v
                    mock.headers = {}
                    return mock
            raise Exception(f"404 Not Found: {url}")
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

        result_lines = [
            f"{a['id']}|chung-khoan|3|0|event-{idx}"
            for idx, a in enumerate(articles_data)
        ]
        (batches_dir / "result-01.txt").write_text("\n".join(result_lines) + "\n", encoding="utf-8")
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
        result_lines = [
            f"{r['id']}|{','.join(r.get('topics', []))}|{r.get('importance', 0)}|{1 if r.get('is_noise') else 0}|event-{idx}"
            for idx, r in enumerate(results)
        ]
        (batches_dir / "result-01.txt").write_text(
            "\n".join(result_lines) + "\n", encoding="utf-8"
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

    # --- Part 2 Tests ---

    def test_prepare_skips_cached_articles_and_reports_counts(self):
        cli.main(["fetch", "--only", "cafef-chungkhoan"])
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        raw_file = data_dir / "raw.json"
        raw_items = json.loads(raw_file.read_text(encoding="utf-8"))
        art2 = dict(raw_items[0])
        art2["id"] = "art_second_cached_test"
        art2["url"] = "https://example.com/second"
        art2["title"] = "Bài viết thứ hai"
        raw_items.append(art2)
        raw_file.write_text(json.dumps(raw_items, ensure_ascii=False), encoding="utf-8")

        cache_dir = Path(self.temp_dir) / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "classified.json"
        cache_file.write_text(json.dumps({
            "art_second_cached_test": {
                "topics": ["chung-khoan"],
                "importance": 3,
                "is_noise": False,
                "event_key": "ev-cached",
                "date": today,
            }
        }, ensure_ascii=False), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["prepare"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("1 bài viết mới", printed)
        self.assertIn("bỏ qua 1 bài", printed)

        batches_dir = data_dir / "batches"
        b1_data = json.loads((batches_dir / "batch-01.json").read_text(encoding="utf-8"))
        self.assertEqual(len(b1_data), 1)
        self.assertEqual(b1_data[0]["id"], raw_items[0]["id"])

        arts_data = json.loads((data_dir / "articles.json").read_text(encoding="utf-8"))
        self.assertEqual(len(arts_data), 2)

    def test_collect_writes_cache_and_prunes_old_entries(self):
        cache_dir = Path(self.temp_dir) / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "classified.json"
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        cache_file.write_text(json.dumps({
            "old_art_id": {
                "topics": ["ngan-hang"],
                "importance": 2,
                "is_noise": False,
                "event_key": "old-event",
                "date": old_date,
            }
        }), encoding="utf-8")

        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        batches_dir = data_dir / "batches"
        batches_dir.mkdir(parents=True, exist_ok=True)
        (batches_dir / "batch-01.json").write_text(json.dumps([{"id": "new_art_id"}]), encoding="utf-8")
        (batches_dir / "result-01.txt").write_text("new_art_id|chung-khoan|4|0|new-event\n", encoding="utf-8")

        ret = cli.main(["collect"])
        self.assertEqual(ret, 0)

        updated_cache = json.loads(cache_file.read_text(encoding="utf-8"))
        self.assertIn("new_art_id", updated_cache)
        self.assertEqual(updated_cache["new_art_id"]["importance"], 4)
        self.assertEqual(updated_cache["new_art_id"]["topics"], ["chung-khoan"])
        self.assertNotIn("old_art_id", updated_cache)

    def test_cluster_uses_cached_classifications(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)

        arts = [
            {"id": "c_art1", "source": "src1", "source_group": "g", "url": "https://example.com/1",
             "title": "Thị trường chứng khoán tăng điểm mạnh", "summary_raw": "Lede 1", "published_at": None, "fetched_at": "", "fulltext": None},
            {"id": "c_art2", "source": "src2", "source_group": "g", "url": "https://example.com/2",
             "title": "Ngân hàng Nhà nước hạ lãi suất điều hành", "summary_raw": "Lede 2", "published_at": None, "fetched_at": "", "fulltext": None},
        ]
        (data_dir / "articles.json").write_text(json.dumps(arts, ensure_ascii=False), encoding="utf-8")

        cache_dir = Path(self.temp_dir) / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "classified.json").write_text(json.dumps({
            "c_art1": {"topics": ["chung-khoan"], "importance": 4, "is_noise": False, "event_key": "event-c1", "date": today},
            "c_art2": {"topics": ["ngan-hang"], "importance": 3, "is_noise": False, "event_key": "event-c2", "date": today},
        }), encoding="utf-8")

        ret = cli.main(["cluster", "--skip-merge"])
        self.assertEqual(ret, 0)

        clusters_file = data_dir / "clusters.json"
        self.assertTrue(clusters_file.exists())
        clusters = json.loads(clusters_file.read_text(encoding="utf-8"))
        self.assertEqual(len(clusters), 2)

    def test_prepare_drops_articles_older_than_max_age_but_keeps_undated(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc)
        fresh_time = (now - timedelta(hours=2)).isoformat()
        stale_time = (now - timedelta(hours=48)).isoformat()

        raw_articles = [
            {"id": "fresh_art", "source": "cafef-chungkhoan", "source_group": "chuyen-tai-chinh",
             "url": "https://example.com/fresh", "title": "Tin mới", "summary_raw": "S",
             "published_at": fresh_time, "fetched_at": now.isoformat(), "fulltext": None},
            {"id": "stale_art", "source": "cafef-chungkhoan", "source_group": "chuyen-tai-chinh",
             "url": "https://example.com/stale", "title": "Tin cũ", "summary_raw": "S",
             "published_at": stale_time, "fetched_at": now.isoformat(), "fulltext": None},
            {"id": "undated_art", "source": "cafef-chungkhoan", "source_group": "chuyen-tai-chinh",
             "url": "https://example.com/undated", "title": "Tin không ngày", "summary_raw": "S",
             "published_at": None, "fetched_at": now.isoformat(), "fulltext": None},
        ]
        (data_dir / "raw.json").write_text(json.dumps(raw_articles, ensure_ascii=False), encoding="utf-8")

        ret = cli.main(["prepare"])
        self.assertEqual(ret, 0)

        articles_data = json.loads((data_dir / "articles.json").read_text(encoding="utf-8"))
        art_ids = [a["id"] for a in articles_data]
        self.assertIn("fresh_art", art_ids)
        self.assertIn("undated_art", art_ids)
        self.assertNotIn("stale_art", art_ids)

    def test_prepare_with_nothing_new_creates_no_batches(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)

        raw_articles = [
            {"id": "cached_art", "source": "cafef-chungkhoan", "source_group": "chuyen-tai-chinh",
             "url": "https://example.com/cached", "title": "Tin đã có", "summary_raw": "S",
             "published_at": None, "fetched_at": "", "fulltext": None},
        ]
        (data_dir / "raw.json").write_text(json.dumps(raw_articles, ensure_ascii=False), encoding="utf-8")

        cache_dir = Path(self.temp_dir) / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        (cache_dir / "classified.json").write_text(json.dumps({
            "cached_art": {"topics": ["chung-khoan"], "importance": 3, "is_noise": False, "event_key": "ev", "date": today}
        }), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["prepare"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("Không có bài viết mới cần phân loại", printed)
        batches_dir = data_dir / "batches"
        if batches_dir.exists():
            batch_files = list(batches_dir.glob("batch-*.json"))
            self.assertEqual(len(batch_files), 0)

    # --- Part 3 Tests ---

    def test_brief_prints_top_clusters_with_links_for_distinct_sources(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)

        arts = [
            {"id": "b1", "source": "cafef-chungkhoan", "title": "Lãi suất điều hành hạ nhiệt", "url": "https://cafef.vn/art1",
             "summary_raw": "Ngân hàng Nhà nước quyết định giảm lãi suất điều hành 0.5%."},
            {"id": "b2", "source": "vietstock", "title": "NHNN giảm lãi suất điều hành", "url": "https://vietstock.vn/art2",
             "summary_raw": "Thị trường tài chính đón nhận thông tin NHNN hạ lãi suất."},
        ]
        (data_dir / "articles.json").write_text(json.dumps(arts, ensure_ascii=False), encoding="utf-8")

        clusters = [
            {
                "cluster_id": "c-001",
                "headline": "Ngân hàng Nhà nước hạ lãi suất điều hành",
                "score": 4.5,
                "source_count": 2,
                "topics": ["vi-mo-chinh-sach", "ngan-hang"],
                "article_ids": ["b1", "b2"],
            }
        ]
        (data_dir / "clusters.json").write_text(json.dumps(clusters, ensure_ascii=False), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["brief"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("#c-001 | điểm 4.5 | 2 nguồn | Vĩ mô & Chính sách, Ngân hàng | Ngân hàng Nhà nước hạ lãi suất điều hành", printed)
        self.assertIn("(https://cafef.vn/art1)", printed)
        self.assertIn("(https://vietstock.vn/art2)", printed)

    def test_brief_urls_exactly_match_article_urls(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)

        exact_url = "https://example.com/very/long/url/with?query=param&utm_source=rss#hash"
        arts = [
            {"id": "art_url", "source": "cafef-chungkhoan", "title": "Tiêu đề URL", "url": exact_url,
             "summary_raw": "Tóm tắt"}
        ]
        (data_dir / "articles.json").write_text(json.dumps(arts, ensure_ascii=False), encoding="utf-8")

        clusters = [
            {
                "cluster_id": "c-001",
                "headline": "Tiêu đề URL",
                "score": 3.0,
                "source_count": 1,
                "topics": ["chung-khoan"],
                "article_ids": ["art_url"],
            }
        ]
        (data_dir / "clusters.json").write_text(json.dumps(clusters, ensure_ascii=False), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            cli.main(["brief"])
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn(f"({exact_url})", printed)

    def test_brief_respects_cluster_and_link_caps(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)

        config.set_value("profile", "brief_clusters", 2)
        config.set_value("profile", "brief_links_per_cluster", 1)

        arts = [
            {"id": f"art_{i}_{j}", "source": f"src_{j}", "title": f"T {i} {j}", "url": f"https://example.com/{i}/{j}", "summary_raw": "S"}
            for i in range(5) for j in range(3)
        ]
        (data_dir / "articles.json").write_text(json.dumps(arts, ensure_ascii=False), encoding="utf-8")

        clusters = [
            {
                "cluster_id": f"c-00{i+1}",
                "headline": f"Cụm {i}",
                "score": float(10 - i),
                "source_count": 3,
                "topics": ["chung-khoan"],
                "article_ids": [f"art_{i}_{j}" for j in range(3)],
            }
            for i in range(5)
        ]
        (data_dir / "clusters.json").write_text(json.dumps(clusters, ensure_ascii=False), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            cli.main(["brief"])
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("#c-001", printed)
        self.assertIn("#c-002", printed)
        self.assertNotIn("#c-003", printed)

        lines = [line for line in printed.splitlines() if line.startswith("  ")]
        self.assertEqual(len(lines), 2)
        for l in lines:
            links_in_line = re.findall(r"\[.*?\]\(.*?\)", l)
            self.assertEqual(len(links_in_line), 1)

    def test_brief_lede_cut_at_160_chars(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)

        long_lede = (
            "Đây là đoạn tóm tắt mở đầu rất dài của bài viết tin tức tài chính "
            "được lấy từ nguồn RSS, mục đích để kiểm tra xem hệ thống có cắt ngắn "
            "đúng 160 ký tự tại ranh giới từ hay không trong chế độ tóm tắt compact brief."
        )
        self.assertGreater(len(long_lede), 160)

        arts = [
            {"id": "a_lede", "source": "src1", "title": "Tiêu đề", "url": "https://example.com/1", "summary_raw": long_lede}
        ]
        (data_dir / "articles.json").write_text(json.dumps(arts, ensure_ascii=False), encoding="utf-8")

        clusters = [
            {"cluster_id": "c-001", "headline": "Tiêu đề", "score": 3.0, "source_count": 1, "topics": ["chung-khoan"], "article_ids": ["a_lede"]}
        ]
        (data_dir / "clusters.json").write_text(json.dumps(clusters, ensure_ascii=False), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            cli.main(["brief"])
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        indented_lines = [l for l in printed.splitlines() if l.startswith("  ")]
        self.assertEqual(len(indented_lines), 1)
        line = indented_lines[0].strip()
        link_idx = line.find("[")
        lede_text = line[:link_idx].strip() if link_idx != -1 else line
        self.assertLessEqual(len(lede_text), 160)
        self.assertTrue(lede_text.endswith("…"))
        self.assertTrue(long_lede.startswith(lede_text.rstrip("…")))

    def test_brief_lede_has_ellipsis_only_when_cut(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)

        long_lede = (
            "Thị trường tài chính quốc tế và trong nước tiếp tục diễn biến phức tạp "
            "với nhiều biến động lãi suất khó lường trước sự dịch chuyển của các dòng vốn đầu tư lớn "
            "trên toàn cầu trong bối cảnh các ngân hàng trung ương có xu hướng nới lỏng chính sách tiền tệ."
        )
        short_lede = "Thị trường tài chính duy trì đà tăng trưởng ổn định."

        arts = [
            {"id": "a_long", "source": "src1", "title": "Tin dài", "url": "https://example.com/long", "summary_raw": long_lede},
            {"id": "a_short", "source": "src2", "title": "Tin ngắn", "url": "https://example.com/short", "summary_raw": short_lede},
        ]
        clusters = [
            {"cluster_id": "c-001", "headline": "Tin dài", "score": 4.0, "source_count": 1, "topics": ["chung-khoan"], "article_ids": ["a_long"]},
            {"cluster_id": "c-002", "headline": "Tin ngắn", "score": 3.0, "source_count": 1, "topics": ["ngan-hang"], "article_ids": ["a_short"]},
        ]
        (data_dir / "articles.json").write_text(json.dumps(arts, ensure_ascii=False), encoding="utf-8")
        (data_dir / "clusters.json").write_text(json.dumps(clusters, ensure_ascii=False), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            cli.main(["brief"])
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        indented_lines = [l for l in printed.splitlines() if l.startswith("  ")]
        self.assertEqual(len(indented_lines), 2)

        # 1. Long lede cut with ellipsis
        line1 = indented_lines[0].strip()
        link_idx1 = line1.find("[")
        lede1 = line1[:link_idx1].strip() if link_idx1 != -1 else line1
        self.assertLessEqual(len(lede1), 160)
        self.assertTrue(lede1.endswith("…"))
        # Check no partial word before ellipsis:
        base_cut = lede1[:-1]
        self.assertFalse(base_cut.endswith(" "))
        last_word = base_cut.split()[-1]
        self.assertIn(last_word + " ", long_lede)

        # 2. Short lede uncut without ellipsis
        line2 = indented_lines[1].strip()
        link_idx2 = line2.find("[")
        lede2 = line2[:link_idx2].strip() if link_idx2 != -1 else line2
        self.assertFalse(lede2.endswith("…"))
        self.assertEqual(lede2, short_lede)

    # --- Part 4 Tests ---

    def test_quiet_commands_print_no_paths_or_ids(self):
        out_run = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out_run
            ret = cli.main(["run", "--only", "cafef-chungkhoan"])
            self.assertEqual(ret, 0)
            printed_run = out_run.getvalue()
        finally:
            sys.stdout = old_stdout

        for line in printed_run.splitlines():
            if "batch-" in line and line.endswith(".json"):
                continue
            self.assertNotIn("\\", line)
        self.assertNotIn("c-0", printed_run)

        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        batches_dir = data_dir / "batches"
        batch_files = list(batches_dir.glob("batch-*.json"))
        for bf in batch_files:
            rf = batches_dir / bf.name.replace("batch-", "result-").replace(".json", ".txt")
            b_data = json.loads(bf.read_text(encoding="utf-8"))
            lines = [f"{item['id']}|chung-khoan|3|0|event-0" for item in b_data]
            rf.write_text("\n".join(lines) + "\n", encoding="utf-8")

        out_finish = io.StringIO()
        try:
            sys.stdout = out_finish
            ret = cli.main(["finish"])
            self.assertEqual(ret, 0)
            printed_finish = out_finish.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertNotIn("\\", printed_finish)
        self.assertNotIn("c-0", printed_finish)

        # 3. Test brief
        out_brief = io.StringIO()
        try:
            sys.stdout = out_brief
            ret = cli.main(["brief"])
            self.assertEqual(ret, 0)
            printed_brief = out_brief.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertNotIn("\\", printed_brief)

    def test_verbose_flag_restores_details(self):
        self._setup_classified_articles()
        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["--verbose", "cluster", "--skip-merge"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("[c-001]", printed)
        self.assertIn("Score:", printed)

    def test_log_file_records_step_durations(self):
        cli.main(["fetch", "--only", "cafef-chungkhoan"])
        today = datetime.now().strftime("%Y-%m-%d")
        log_file = Path(self.temp_dir) / "logs" / f"{today}.log"
        self.assertTrue(log_file.exists())
        content = log_file.read_text(encoding="utf-8")
        self.assertIn("step=fetch", content)
        self.assertIn("seconds=", content)

    def test_stats_prints_last_run_steps(self):
        cli.main(["fetch", "--only", "cafef-chungkhoan"])
        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["stats"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("fetch", printed)
        self.assertIn("s", printed)

    def test_finish_prints_rerun_lines_and_exit_3(self):
        cli.main(["fetch", "--only", "cafef-chungkhoan"])
        cli.main(["prepare"])

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["finish"])
            self.assertEqual(ret, 3)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("RERUN", printed)
        self.assertIn("batch-01.json", printed)

    def test_finish_exit_0_when_all_batches_complete(self):
        self._setup_classified_articles()
        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["finish"])
            self.assertEqual(ret, 0)
        finally:
            sys.stdout = old_stdout

        today = datetime.now().strftime("%Y-%m-%d")
        clusters_file = Path(self.temp_dir) / "data" / today / "clusters.json"
        self.assertTrue(clusters_file.exists())

    def test_test_source_fulltext_exit_codes(self):
        full_p = "Tin tức tài chính thử nghiệm phục vụ kiểm tra toàn văn bài viết của trang tin tức điện tử. " * 6
        full_html = f"<html><body><article><p>{full_p}</p></article></body></html>".encode("utf-8")
        empty_html = b"<html><body><p>Ngan</p></body></html>"

        # 1. Full -> exit 0
        fetch._DEFAULT_OPENER = FakeOpener({
            "cafef.vn": SAMPLE_FEED,
            "example.com/art1": full_html,
        })
        ret_full = cli.main(["test-source", "cafef-chungkhoan", "--fulltext"])
        self.assertEqual(ret_full, 0)

        # 2. Summary only -> exit 1
        fetch._DEFAULT_OPENER = FakeOpener({
            "cafef.vn": SAMPLE_FEED,
            "example.com/art1": empty_html,
        })
        ret_sum = cli.main(["test-source", "cafef-chungkhoan", "--fulltext"])
        self.assertEqual(ret_sum, 1)

    def test_doctor_fulltext_prints_table_and_plain_doctor_has_no_page_fetch(self):
        full_p = "Tin tức tài chính thử nghiệm phục vụ kiểm tra toàn văn bài viết của trang tin tức điện tử. " * 6
        full_html = f"<html><body><article><p>{full_p}</p></article></body></html>".encode("utf-8")

        fetched_urls = []
        def tracking_opener(req):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            fetched_urls.append(url)
            if "art" in url:
                return full_html
            return SAMPLE_FEED

        fetch._DEFAULT_OPENER = FakeOpener(tracking_opener)

        # 1. doctor --fulltext
        out_ft = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out_ft
            cli.main(["doctor", "--fulltext"])
            printed_ft = out_ft.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("BÁO CÁO TOÀN VĂN", printed_ft)
        self.assertIn("NGUỒN", printed_ft)
        self.assertIn("TRẠNG THÁI", printed_ft)
        self.assertTrue(any("art" in u for u in fetched_urls), "doctor --fulltext must fetch page URLs")

        # 2. plain doctor must NOT fetch page URLs
        fetched_urls.clear()
        out_plain = io.StringIO()
        try:
            sys.stdout = out_plain
            cli.main(["doctor"])
        finally:
            sys.stdout = old_stdout

        self.assertFalse(any("art" in u for u in fetched_urls), "plain doctor must not fetch article page URLs")

    def test_doctor_failure_prints_install_hint_path(self):
        import fin_news.doctor as doctor_mod
        old_check = doctor_mod.check_python_version
        doctor_mod.check_python_version = lambda: ("Python Version", False, "3.8 is too old")
        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["doctor"])
            self.assertEqual(ret, 1)
            printed = out.getvalue()
        finally:
            doctor_mod.check_python_version = old_check
            sys.stdout = old_stdout

        self.assertIn("Xem hướng dẫn:", printed)
        self.assertIn("INSTALL.md", printed)
        self.assertIn("TROUBLESHOOT.md", printed)

    def test_brief_has_no_problem_block_when_all_fine(self):
        self._setup_classified_articles()
        cli.main(["cluster", "--skip-merge"])
        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["brief"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertNotIn("NGUỒN LỖI", printed)

    def test_brief_problem_block_has_only_feed_problems_in_plain_words(self):
        self._setup_classified_articles()
        cli.main(["cluster", "--skip-merge"])

        from fin_news import health
        # Record fulltext health (must be ignored by brief)
        health.record_fulltext_health([
            {"source": "vietnamnet", "status": "degraded", "tier": "density"},
            {"source": "cafebiz", "status": "summary_only", "tier": ""},
        ], date_str="2026-11-03")

        # Today's feed health has 1 error (multi-day) and 1 empty (first-day)
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        h_today = [
            {"source_id": "cafef-chungkhoan", "status": "error", "detail": "Connection timed out", "checked_at": f"{today}T10:00:00Z", "since": "2026-11-01"},
            {"source_id": "tuoitre", "status": "empty", "detail": "0 articles", "checked_at": f"{today}T10:00:00Z"},
            {"source_id": "vnexpress", "status": "ok", "detail": "10 articles", "checked_at": f"{today}T10:00:00Z"},
        ]
        (data_dir / "health.json").write_text(json.dumps(h_today, ensure_ascii=False), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["brief"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("NGUỒN LỖI", printed)
        self.assertIn("- CafeF: hôm nay không đọc được (từ 01/11)", printed)
        self.assertIn("- Tuổi Trẻ: hôm nay không có bài mới", printed)
        self.assertNotIn("vietnamnet", printed)
        self.assertNotIn("cafebiz", printed)
        self.assertNotIn("tầng", printed)
        self.assertNotIn("trích xuất dự phòng", printed)
        self.assertNotIn("chỉ có tóm tắt", printed)
        self.assertNotIn("cafef-chungkhoan:", printed)
        self.assertNotIn("2026-11-01", printed)
        self.assertNotIn("2026-11-03", printed)

    def test_brief_problem_block_ignores_fulltext_health(self):
        self._setup_classified_articles()
        cli.main(["cluster", "--skip-merge"])

        from fin_news import health
        health.record_fulltext_health([
            {"source": "src_deg", "status": "degraded", "tier": "density"},
            {"source": "src_sum", "status": "summary_only", "tier": ""},
        ], date_str="2026-11-03")

        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        h_today = [
            {"source_id": "vnexpress", "status": "ok", "detail": "10 articles", "checked_at": f"{today}T10:00:00Z"},
        ]
        (data_dir / "health.json").write_text(json.dumps(h_today, ensure_ascii=False), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["brief"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertNotIn("NGUỒN LỖI", printed)

    def test_brief_problem_block_uses_labels_and_omits_since_for_first_day(self):
        self._setup_classified_articles()
        cli.main(["cluster", "--skip-merge"])

        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        h_today = [
            {"source_id": "cafef-chungkhoan", "status": "error", "detail": "Connection error", "checked_at": f"{today}T10:00:00Z"},
        ]
        (data_dir / "health.json").write_text(json.dumps(h_today, ensure_ascii=False), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            ret = cli.main(["brief"])
            self.assertEqual(ret, 0)
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("NGUỒN LỖI", printed)
        self.assertIn("- CafeF: hôm nay không đọc được", printed)
        self.assertNotIn("(từ", printed)
        self.assertNotIn("cafef-chungkhoan:", printed)

    def test_brief_uses_label_not_id(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)

        arts = [
            {"id": "a1", "source": "cafef-chungkhoan", "title": "Tin CafeF", "url": "https://cafef.vn/1", "summary_raw": "Lede"}
        ]
        clusters = [
            {"cluster_id": "c-001", "headline": "Tin CafeF", "score": 3.0, "source_count": 1, "topics": ["chung-khoan"], "article_ids": ["a1"]}
        ]
        (data_dir / "articles.json").write_text(json.dumps(arts, ensure_ascii=False), encoding="utf-8")
        (data_dir / "clusters.json").write_text(json.dumps(clusters, ensure_ascii=False), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            cli.main(["brief"])
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("[CafeF](https://cafef.vn/1)", printed)
        self.assertNotIn("[cafef-chungkhoan](https://cafef.vn/1)", printed)

    def test_brief_falls_back_when_no_label(self):
        today = datetime.now().strftime("%Y-%m-%d")
        data_dir = Path(self.temp_dir) / "data" / today
        data_dir.mkdir(parents=True, exist_ok=True)

        arts = [
            {"id": "a2", "source": "unlabeled-source", "title": "Tin Unlabeled", "url": "https://example.com/2", "summary_raw": "Lede"}
        ]
        clusters = [
            {"cluster_id": "c-001", "headline": "Tin Unlabeled", "score": 3.0, "source_count": 1, "topics": ["chung-khoan"], "article_ids": ["a2"]}
        ]
        (data_dir / "articles.json").write_text(json.dumps(arts, ensure_ascii=False), encoding="utf-8")
        (data_dir / "clusters.json").write_text(json.dumps(clusters, ensure_ascii=False), encoding="utf-8")

        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            cli.main(["brief"])
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        self.assertIn("[Unlabeled-Source](https://example.com/2)", printed)

    def test_add_source_sets_default_label_and_accepts_label_flag(self):
        feed_xml = b"""<rss version="2.0"><channel><item><title>A</title><link>https://example.com/1</link></item></channel></rss>"""

        # 1. Without --label flag -> derives from host name
        page_html1 = b"""<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml" /></head></html>"""
        fetch._DEFAULT_OPENER = FakeOpener({
            "https://testnews.com": page_html1,
            "https://testnews.com/feed.xml": feed_xml,
        })
        cli.main(["add-source", "https://testnews.com", "--id", "testnews"])
        sources_cfg = config.load("sources")
        self.assertEqual(sources_cfg["sources"]["testnews"]["label"], "testnews.com")

        # 2. With --label flag -> uses provided label
        page_html2 = b"""<html><head><link rel="alternate" type="application/rss+xml" href="/rss" /></head></html>"""
        fetch._DEFAULT_OPENER = FakeOpener({
            "https://customsite.vn": page_html2,
            "https://customsite.vn/rss": feed_xml,
        })
        cli.main(["add-source", "https://customsite.vn", "--id", "customsite", "--label", "Custom Báo"])
        sources_cfg2 = config.load("sources")
        self.assertEqual(sources_cfg2["sources"]["customsite"]["label"], "Custom Báo")

    def test_default_sources_all_have_labels(self):
        defaults_file = Path(__file__).resolve().parent.parent / "defaults" / "sources.json"
        sources_data = json.loads(defaults_file.read_text(encoding="utf-8")).get("sources", {})
        self.assertGreaterEqual(len(sources_data), 15)
        for sid, scfg in sources_data.items():
            self.assertIn("label", scfg, f"Source '{sid}' in defaults/sources.json missing 'label'")
            self.assertTrue(scfg["label"], f"Source '{sid}' has empty 'label'")

    def test_brief_first_line_is_vietnamese_date(self):
        self._setup_classified_articles()
        cli.main(["cluster", "--skip-merge"])
        out = io.StringIO()
        old_stdout = sys.stdout
        try:
            sys.stdout = out
            cli.main(["brief"])
            printed = out.getvalue()
        finally:
            sys.stdout = old_stdout

        first_line = printed.splitlines()[0]
        self.assertTrue(first_line.startswith("Ngày: "), f"First line must start with 'Ngày: ', got: '{first_line}'")
        date_part = first_line.replace("Ngày: ", "").strip()
        self.assertRegex(date_part, r"^\d{2}/\d{2}/\d{4}$")

    def test_skill_title_uses_ddmmyyyy_format(self):
        skill_file = Path(__file__).resolve().parent.parent / "skills" / "fin-news-digest" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")
        self.assertIn("# Bản tin Tài chính — DD/MM/YYYY", content)


if __name__ == "__main__":
    unittest.main()
