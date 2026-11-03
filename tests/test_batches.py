import json
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

from fin_news import batches
from fin_news.models import Article


def make_art(idx: int, summary_raw: str = None) -> Article:
    return Article(
        id=f"art{idx:03d}",
        source="test_src",
        source_group="finance",
        url=f"https://example.com/{idx}",
        title=f"Title {idx}",
        summary_raw=summary_raw if summary_raw is not None else f"Summary raw {idx}",
        published_at="2026-11-03T10:00:00+07:00",
        fetched_at="2026-11-03T10:05:00+07:00",
        fulltext=None,
    )


class TestBatches(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_make_batches_sizes_25_25_rest(self):
        articles = [make_art(i) for i in range(60)]
        batch_files = batches.make_batches(articles, size=25, out_dir=self.temp_dir)
        self.assertEqual(len(batch_files), 3)

        b1 = json.loads(batch_files[0].read_text(encoding="utf-8"))
        b2 = json.loads(batch_files[1].read_text(encoding="utf-8"))
        b3 = json.loads(batch_files[2].read_text(encoding="utf-8"))
        self.assertEqual(len(b1), 25)
        self.assertEqual(len(b2), 25)
        self.assertEqual(len(b3), 10)

    def test_batch_files_contain_only_prompt_fields(self):
        articles = [make_art(1)]
        batch_files = batches.make_batches(articles, size=25, out_dir=self.temp_dir)
        data = json.loads(batch_files[0].read_text(encoding="utf-8"))
        self.assertEqual(len(data), 1)
        expected_keys = {"id", "source", "title", "summary_raw"}
        self.assertEqual(set(data[0].keys()), expected_keys)

    def test_batch_files_truncate_summary_raw_at_word_boundary(self):
        long_summary = (
            "Ngân hàng Nhà nước Việt Nam vừa công bố quyết định điều chỉnh giảm lãi suất "
            "điều hành nhằm hỗ trợ doanh nghiệp và nền kinh tế phục hồi tăng trưởng mạnh mẽ "
            "trong giai đoạn cuối năm 2026 với nhiều giải pháp thiết thực."
        )
        art = make_art(1, summary_raw=long_summary)
        batch_files = batches.make_batches([art], size=70, out_dir=self.temp_dir, lede_chars=100)
        data = json.loads(batch_files[0].read_text(encoding="utf-8"))
        summary = data[0]["summary_raw"]
        self.assertLessEqual(len(summary), 100)
        self.assertFalse(summary.endswith(" "))
        # Ensure it didn't cut inside a word (e.g. "kinh tế" instead of "kinh t")
        self.assertTrue(long_summary.startswith(summary))

    def test_validate_accepts_good_rows(self):
        topics = {"ngan-hang", "chung-khoan"}
        raw = "art001|ngan-hang|4|0|vcb-tang-von\n"
        valid, problems = batches.validate_lines(raw, ["art001"], topics)
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(problems), 0)
        self.assertEqual(valid[0]["id"], "art001")
        self.assertEqual(valid[0]["topics"], ["ngan-hang"])
        self.assertEqual(valid[0]["importance"], 4)
        self.assertEqual(valid[0]["is_noise"], False)
        self.assertEqual(valid[0]["event_key"], "vcb-tang-von")

    def test_validate_flags_unknown_topic(self):
        topics = {"ngan-hang"}
        raw = "art001|unknown-topic|2|0|ev-1\n"
        valid, problems = batches.validate_lines(raw, ["art001"], topics)
        self.assertEqual(len(valid), 0)
        self.assertIn("art001", problems)

    def test_validate_accepts_empty_topics_for_noise_row(self):
        topics = {"ngan-hang"}
        raw = "art_noise||0|1|sau-rieng-giam-gia\n"
        valid, problems = batches.validate_lines(raw, ["art_noise"], topics)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["id"], "art_noise")
        self.assertEqual(valid[0]["topics"], [])
        self.assertEqual(valid[0]["is_noise"], True)
        self.assertEqual(len(problems), 0)

    def test_validate_flags_empty_topics_when_not_noise(self):
        topics = {"ngan-hang"}
        raw = "art_non_noise||2|0|ev-empty\n"
        valid, problems = batches.validate_lines(raw, ["art_non_noise"], topics)
        self.assertEqual(len(valid), 0)
        self.assertIn("art_non_noise", problems)

    def test_validate_flags_unknown_topic_even_when_noise(self):
        topics = {"ngan-hang"}
        raw = "art_noise_bad_topic|unknown-topic|0|1|ev-noise-bad\n"
        valid, problems = batches.validate_lines(raw, ["art_noise_bad_topic"], topics)
        self.assertEqual(len(valid), 0)
        self.assertIn("art_noise_bad_topic", problems)

    def test_validate_flags_missing_and_duplicate_ids(self):
        topics = {"ngan-hang"}
        raw = "art001|ngan-hang|3|0|ev-1\nart001|ngan-hang|3|0|ev-1\n"
        valid, problems = batches.validate_lines(raw, ["art001", "art002"], topics)
        self.assertIn("art002", problems)
        self.assertIn("art001", problems)

    def test_validate_unparseable_json_flags_all(self):
        topics = {"ngan-hang"}
        raw = "Not valid JSON {"
        valid, problems = batches.validate_lines(raw, ["art001", "art002"], topics)
        self.assertEqual(len(valid), 0)
        self.assertEqual(set(problems), {"art001", "art002"})

    def test_validate_flags_bad_fields_and_formats(self):
        topics = {"ngan-hang"}
        # Bad importance (not 0-5)
        raw_imp = "art001|ngan-hang|6|0|ev-1"
        valid, probs = batches.validate_lines(raw_imp, ["art001"], topics)
        self.assertIn("art001", probs)

        # Bad noise (not 0 or 1)
        raw_noise = "art001|ngan-hang|3|2|ev-1"
        valid, probs = batches.validate_lines(raw_noise, ["art001"], topics)
        self.assertIn("art001", probs)

        # Bad event_key (uppercase / invalid chars)
        raw_ek = "art001|ngan-hang|3|0|BAD_KEY_123!"
        valid, probs = batches.validate_lines(raw_ek, ["art001"], topics)
        self.assertIn("art001", probs)

        # Wrong field count (4 fields)
        raw_fc = "art001|ngan-hang|3|0"
        valid, probs = batches.validate_lines(raw_fc, ["art001"], topics)
        self.assertIn("art001", probs)

    def test_merge_results_reports_ids_without_valid_result(self):
        topics = {"ngan-hang"}
        b1_path = self.temp_dir / "batch-01.json"
        b1_path.write_text(json.dumps([
            {"id": "art001", "source": "s1", "title": "T1", "summary_raw": "S1"},
            {"id": "art002", "source": "s1", "title": "T2", "summary_raw": "S2"}
        ]), encoding="utf-8")

        # Result-01 has valid art001, but art002 is missing
        r1_path = self.temp_dir / "result-01.txt"
        r1_path.write_text("art001|ngan-hang|3|0|ev-1\n", encoding="utf-8")

        rows, needed = batches.merge_results(self.temp_dir, topics=topics)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "art001")
        self.assertEqual(needed, ["art002"])


if __name__ == "__main__":
    unittest.main()
