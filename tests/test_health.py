import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from fin_news import health, doctor, config
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


if __name__ == "__main__":
    unittest.main()
