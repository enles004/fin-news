from pathlib import Path
import unittest

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


if __name__ == "__main__":
    unittest.main()
