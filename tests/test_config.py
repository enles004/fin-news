import os
import shutil
import tempfile
import unittest
from pathlib import Path

# Add core to sys.path so fin_news can be imported
import sys
CORE_DIR = Path(__file__).resolve().parent.parent / "core"
if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

from fin_news import config


class TestConfig(unittest.TestCase):
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

    def test_load_returns_defaults_when_no_user_file(self):
        profile = config.load("profile")
        self.assertEqual(profile.get("max_per_source"), 10)

    def test_user_value_overrides_default_and_other_keys_survive(self):
        old, new = config.set_value("profile", "max_per_source", 15)
        self.assertEqual(old, 10)
        self.assertEqual(new, 15)
        profile = config.load("profile")
        self.assertEqual(profile["max_per_source"], 15)
        self.assertEqual(profile.get("batch_size"), 25)

    def test_dict_merge_adds_user_source_without_dropping_defaults(self):
        user_source = {
            "url": "https://example.com/rss",
            "kind": "rss",
            "group": "test",
            "enabled": True,
            "cookie": False,
            "mixed": False,
        }
        config.set_value("sources", "sources.demo", user_source)
        loaded = config.load("sources")
        self.assertIn("demo", loaded["sources"])
        self.assertIn("cafef-chungkhoan", loaded["sources"])

    def test_set_value_returns_old_new_and_writes_changelog(self):
        old, new = config.set_value("profile", "max_per_source", 15)
        self.assertEqual(old, 10)
        self.assertEqual(new, 15)
        changelog = Path(config.home()) / "config" / "CHANGELOG.md"
        self.assertTrue(changelog.exists())
        content = changelog.read_text(encoding="utf-8")
        self.assertIn("max_per_source", content)
        self.assertTrue("10 → 15" in content or "10 -> 15" in content or "10 \u2192 15" in content)

    def test_unset_restores_default(self):
        config.set_value("profile", "max_per_source", 20)
        self.assertEqual(config.load("profile")["max_per_source"], 20)
        config.unset("profile", "max_per_source")
        self.assertEqual(config.load("profile")["max_per_source"], 10)

    def test_home_with_spaces_and_non_ascii(self):
        non_ascii_home = Path(self.temp_dir) / "thư mục có dấu cách"
        non_ascii_home.mkdir(parents=True, exist_ok=True)
        os.environ["FIN_NEWS_HOME"] = str(non_ascii_home)
        self.assertEqual(config.home(), non_ascii_home)
        config.set_value("profile", "max_per_source", 12)
        loaded = config.load("profile")
        self.assertEqual(loaded["max_per_source"], 12)
        changelog = non_ascii_home / "config" / "CHANGELOG.md"
        self.assertTrue(changelog.exists())


if __name__ == "__main__":
    unittest.main()
