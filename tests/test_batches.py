import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from fin_news import batches
from fin_news.models import Article


def make_art(idx: int) -> Article:
    return Article(
        id=f"art{idx:03d}",
        source="test_src",
        source_group="finance",
        url=f"https://example.com/{idx}",
        title=f"Title {idx}",
        summary_raw=f"Summary raw {idx}",
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

    def test_validate_accepts_good_rows(self):
        topics = {"ngan-hang", "chung-khoan"}
        raw = json.dumps([
            {
                "id": "art001",
                "topics": ["ngan-hang"],
                "summary_vi": "Tóm tắt bài 1",
                "entities": ["Vietcombank"],
                "importance": 4,
                "importance_reason": "Tác động lớn",
                "event_key": "vcb-tang-von",
                "is_noise": False,
            }
        ])
        valid, problems = batches.validate_result(raw, ["art001"], topics)
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(problems), 0)

    def test_validate_flags_unknown_topic(self):
        topics = {"ngan-hang"}
        raw = json.dumps([
            {
                "id": "art001",
                "topics": ["unknown-topic"],
                "summary_vi": "Tóm tắt",
                "entities": [],
                "importance": 2,
                "importance_reason": "Lý do",
                "event_key": "ev-1",
                "is_noise": False,
            }
        ])
        valid, problems = batches.validate_result(raw, ["art001"], topics)
        self.assertEqual(len(valid), 0)
        self.assertIn("art001", problems)

    def test_validate_accepts_empty_topics_for_noise_row(self):
        topics = {"ngan-hang"}
        raw = json.dumps([
            {
                "id": "art_noise",
                "topics": [],
                "summary_vi": "Giá sầu riêng giảm mạnh",
                "entities": ["sầu riêng"],
                "importance": 0,
                "importance_reason": "Tin nông sản cục bộ",
                "event_key": "sau-rieng-giam-gia",
                "is_noise": True,
            }
        ])
        valid, problems = batches.validate_result(raw, ["art_noise"], topics)
        self.assertEqual(len(valid), 1)
        self.assertEqual(valid[0]["id"], "art_noise")
        self.assertEqual(len(problems), 0)

    def test_validate_flags_empty_topics_when_not_noise(self):
        topics = {"ngan-hang"}
        raw = json.dumps([
            {
                "id": "art_non_noise",
                "topics": [],
                "summary_vi": "Tóm tắt không có chủ đề",
                "entities": [],
                "importance": 2,
                "importance_reason": "Lý do",
                "event_key": "ev-empty",
                "is_noise": False,
            }
        ])
        valid, problems = batches.validate_result(raw, ["art_non_noise"], topics)
        self.assertEqual(len(valid), 0)
        self.assertIn("art_non_noise", problems)

    def test_validate_flags_unknown_topic_even_when_noise(self):
        topics = {"ngan-hang"}
        raw = json.dumps([
            {
                "id": "art_noise_bad_topic",
                "topics": ["unknown-topic"],
                "summary_vi": "Tin rác nhưng có topic lạ",
                "entities": [],
                "importance": 0,
                "importance_reason": "Lý do",
                "event_key": "ev-noise-bad",
                "is_noise": True,
            }
        ])
        valid, problems = batches.validate_result(raw, ["art_noise_bad_topic"], topics)
        self.assertEqual(len(valid), 0)
        self.assertIn("art_noise_bad_topic", problems)

    def test_validate_flags_missing_and_duplicate_ids(self):
        topics = {"ngan-hang"}
        raw = json.dumps([
            {
                "id": "art001",
                "topics": ["ngan-hang"],
                "summary_vi": "Tóm tắt",
                "entities": [],
                "importance": 3,
                "importance_reason": "Lý do",
                "event_key": "ev-1",
                "is_noise": False,
            },
            {
                "id": "art001",  # duplicate
                "topics": ["ngan-hang"],
                "summary_vi": "Tóm tắt 2",
                "entities": [],
                "importance": 3,
                "importance_reason": "Lý do",
                "event_key": "ev-1",
                "is_noise": False,
            }
        ])
        # art002 is expected but missing
        valid, problems = batches.validate_result(raw, ["art001", "art002"], topics)
        # Duplicate art001 and missing art002 should both be flagged
        self.assertIn("art002", problems)
        self.assertIn("art001", problems)

    def test_validate_unparseable_json_flags_all(self):
        topics = {"ngan-hang"}
        raw = "Not valid JSON {"
        valid, problems = batches.validate_result(raw, ["art001", "art002"], topics)
        self.assertEqual(len(valid), 0)
        self.assertEqual(set(problems), {"art001", "art002"})

    def test_merge_results_reports_ids_without_valid_result(self):
        topics = {"ngan-hang"}
        # Create batch-01.json with art001 and art002
        b1_path = self.temp_dir / "batch-01.json"
        b1_path.write_text(json.dumps([
            {"id": "art001", "source": "s1", "title": "T1", "summary_raw": "S1"},
            {"id": "art002", "source": "s1", "title": "T2", "summary_raw": "S2"}
        ]), encoding="utf-8")

        # Result-01 has valid art001, but art002 is missing
        r1_path = self.temp_dir / "result-01.json"
        r1_path.write_text(json.dumps([
            {
                "id": "art001",
                "topics": ["ngan-hang"],
                "summary_vi": "Tóm tắt",
                "entities": [],
                "importance": 3,
                "importance_reason": "Lý do",
                "event_key": "ev-1",
                "is_noise": False,
            }
        ]), encoding="utf-8")

        rows, needed = batches.merge_results(self.temp_dir, topics=topics)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "art001")
        self.assertEqual(needed, ["art002"])


if __name__ == "__main__":
    unittest.main()
