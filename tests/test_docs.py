from pathlib import Path
import sys
import unittest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import support

ROOT_DIR = Path(__file__).resolve().parent.parent


class TestDocs(unittest.TestCase):
    def test_launchers_exist_and_call_cli(self):
        run_cmd = ROOT_DIR / "run.cmd"
        run_sh = ROOT_DIR / "run.sh"

        self.assertTrue(run_cmd.exists(), "run.cmd missing")
        self.assertTrue(run_sh.exists(), "run.sh missing")

        cmd_text = run_cmd.read_text(encoding="utf-8")
        sh_text = run_sh.read_text(encoding="utf-8")

        self.assertTrue("cli.py" in cmd_text, "run.cmd does not call cli.py")
        self.assertTrue("cli.py" in sh_text, "run.sh does not call cli.py")

    def test_launchers_never_install_uv_without_prompt(self):
        run_cmd = ROOT_DIR / "run.cmd"
        run_sh = ROOT_DIR / "run.sh"

        cmd_text = run_cmd.read_text(encoding="utf-8")
        sh_text = run_sh.read_text(encoding="utf-8")

        # Must have prompt or confirmation branch before installing uv
        self.assertTrue(
            ("set /p" in cmd_text.lower() or "choice" in cmd_text.lower() or "prompt" in cmd_text.lower()),
            "run.cmd must prompt before installing uv"
        )
        self.assertTrue(
            ("read -p" in sh_text or "read -r" in sh_text or "prompt" in sh_text.lower()),
            "run.sh must prompt before installing uv"
        )

    def test_every_doc_exists_and_nonempty(self):
        required_docs = [
            "AGENTS.md",
            "INSTALL.md",
            "SCHEDULE.md",
            "CONFIGURE.md",
            "TROUBLESHOOT.md",
        ]
        for doc_name in required_docs:
            p = ROOT_DIR / doc_name
            self.assertTrue(p.exists(), f"Document {doc_name} is missing")
            self.assertGreater(p.stat().st_size, 50, f"Document {doc_name} is too small / empty")

    def test_docs_mention_doctor_and_home_variable(self):
        install_doc = (ROOT_DIR / "INSTALL.md").read_text(encoding="utf-8").lower()
        agents_doc = (ROOT_DIR / "AGENTS.md").read_text(encoding="utf-8").lower()

        self.assertIn("doctor", install_doc, "INSTALL.md must mention doctor")
        self.assertIn("fin_news_home", install_doc, "INSTALL.md must mention FIN_NEWS_HOME")
        self.assertIn("fin_news_home", agents_doc, "AGENTS.md must mention FIN_NEWS_HOME")

    def test_every_test_module_imports_support_first(self):
        tests_dir = ROOT_DIR / "tests"
        test_files = sorted(tests_dir.glob("test_*.py"))
        self.assertGreater(len(test_files), 0, "No test files found")

        for tf in test_files:
            lines = tf.read_text(encoding="utf-8").splitlines()
            support_line = None
            first_project_line = None
            first_project_mod = None

            for idx, line in enumerate(lines, 1):
                clean = line.strip()
                if clean.startswith("#"):
                    continue
                if "import support" in clean:
                    if support_line is None:
                        support_line = idx
                if clean.startswith("from fin_news") or clean.startswith("import fin_news") or clean.startswith("import cli") or clean.startswith("from cli"):
                    if first_project_line is None:
                        first_project_line = idx
                        first_project_mod = clean

            self.assertIsNotNone(
                support_line,
                f"Test module {tf.name} does not import support"
            )
            if first_project_line is not None:
                self.assertLess(
                    support_line, first_project_line,
                    f"In {tf.name}: 'import support' (line {support_line}) must appear before project import '{first_project_mod}' (line {first_project_line})"
                )

    def test_support_sets_temp_home_not_real_home(self):
        import os
        fin_home = os.environ.get("FIN_NEWS_HOME")
        self.assertIsNotNone(fin_home)
        real_default = (Path.home() / ".fin-news").resolve()
        self.assertNotEqual(Path(fin_home).resolve(), real_default)
        self.assertTrue(
            "temp" in fin_home.lower() or "tmp" in fin_home.lower() or "fin_" in fin_home.lower(),
            f"Expected FIN_NEWS_HOME to be in a temporary folder, got {fin_home}"
        )

    def test_launchers_mention_install_md_path(self):
        run_cmd = ROOT_DIR / "run.cmd"
        run_sh = ROOT_DIR / "run.sh"

        cmd_text = run_cmd.read_text(encoding="utf-8")
        sh_text = run_sh.read_text(encoding="utf-8")

        self.assertIn("INSTALL.md", cmd_text)
        self.assertIn("INSTALL.md", sh_text)
        self.assertIn("Xem INSTALL.md để cài đặt", cmd_text)
        self.assertIn("Xem INSTALL.md để cài đặt", sh_text)

    def test_skill_has_step_zero_that_asks_before_installing(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")

        self.assertIn("Bước 0", content)
        self.assertIn("INSTALL.md", content)
        self.assertTrue(
            "hỏi ý kiến người dùng" in content.lower() or "hỏi trước" in content.lower(),
            "SKILL.md Step 0 must ask user before installing"
        )

    def test_troubleshoot_has_fulltext_section(self):
        trouble_file = ROOT_DIR / "TROUBLESHOOT.md"
        content = trouble_file.read_text(encoding="utf-8")

        self.assertIn("Toàn văn bị suy giảm hoặc hỏng", content)
        self.assertIn("test-source", content)
        self.assertIn("--fulltext", content)
        self.assertIn("body_hints", content)

    def test_skill_digest_rules_forbid_technical_words_in_output(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")

        forbidden_words = ["watchlist", "config set", "cluster", "URL", "[Suy luận]"]
        for word in forbidden_words:
            self.assertIn(word, content, f"SKILL.md must mention forbidden word rule for '{word}'")

        self.assertTrue(
            "rỗng" in content.lower() or "empty" in content.lower(),
            "SKILL.md must instruct model to omit empty sections"
        )


if __name__ == "__main__":
    unittest.main()
