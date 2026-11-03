import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = Path(__file__).resolve().parent
if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))
import support

ROOT_DIR = Path(__file__).resolve().parent.parent
CORE_DIR = ROOT_DIR / "core"
PROMPTS_DIR = ROOT_DIR / "prompts"

if str(CORE_DIR) not in sys.path:
    sys.path.insert(0, str(CORE_DIR))

import cli


class TestPrompts(unittest.TestCase):
    def test_agent_declares_haiku(self):
        agent_file = ROOT_DIR / "agents" / "news-classifier.md"
        self.assertTrue(agent_file.exists(), f"Missing {agent_file}")
        content = agent_file.read_text(encoding="utf-8")
        self.assertRegex(content, r"(?i)model:\s*haiku")

    def test_plugin_json_valid_and_references_existing_files(self):
        plugin_file = ROOT_DIR / ".claude-plugin" / "plugin.json"
        self.assertTrue(plugin_file.exists(), f"Missing {plugin_file}")
        data = json.loads(plugin_file.read_text(encoding="utf-8"))
        self.assertIn("name", data)

    def test_classify_prompt_names_every_schema_field(self):
        # Schema fields are now documented in agents/news-classifier.md
        agent_file = ROOT_DIR / "agents" / "news-classifier.md"
        self.assertTrue(agent_file.exists(), f"Missing {agent_file}")
        content = agent_file.read_text(encoding="utf-8")
        schema_fields = [
            "id",
            "topic",
            "importance",
            "noise",
            "event_key",
        ]
        for field in schema_fields:
            self.assertIn(field, content, f"Schema field '{field}' missing from news-classifier.md")

    def test_skill_mentions_every_cli_subcommand_it_uses(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        self.assertTrue(skill_file.exists(), f"Missing {skill_file}")
        content = skill_file.read_text(encoding="utf-8")

        expected_cmds = ["run", "finish", "brief", "stats", "health"]
        for cmd in expected_cmds:
            self.assertIn(cmd, content, f"Subcommand '{cmd}' not mentioned in SKILL.md")

    def test_cluster_merger_agent_declares_haiku(self):
        agent_file = ROOT_DIR / "agents" / "cluster-merger.md"
        self.assertTrue(agent_file.exists(), f"Missing {agent_file}")
        content = agent_file.read_text(encoding="utf-8")
        self.assertRegex(content, r"(?i)model:\s*haiku")

    def test_plugin_json_references_cluster_merger(self):
        agent_file = ROOT_DIR / "agents" / "cluster-merger.md"
        self.assertTrue(agent_file.exists(), f"Missing {agent_file}")
        plugin_file = ROOT_DIR / ".claude-plugin" / "plugin.json"
        self.assertTrue(plugin_file.exists(), f"Missing {plugin_file}")
        data = json.loads(plugin_file.read_text(encoding="utf-8"))
        self.assertNotIn("agents", data)

    def test_skill_mentions_merge_command(self):
        # Default procedure in SKILL.md has no merge step; config-guide.md and CONFIGURE.md document it
        cfg_guide = ROOT_DIR / "skills" / "fin-news-digest" / "config-guide.md"
        self.assertTrue(cfg_guide.exists(), f"Missing {cfg_guide}")
        content = cfg_guide.read_text(encoding="utf-8")
        self.assertIn("merge", content)

    def test_merge_prompt_requires_json_groups_only(self):
        merge_file = PROMPTS_DIR / "merge.md"
        self.assertTrue(merge_file.exists(), f"Missing {merge_file}")
        content = merge_file.read_text(encoding="utf-8")
        self.assertIn("groups", content)
        self.assertRegex(content, r"(?i)json")

    def test_digest_template_has_four_sections_in_order(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        self.assertTrue(skill_file.exists(), f"Missing {skill_file}")
        content = skill_file.read_text(encoding="utf-8")

        s1 = content.find("Tiêu điểm hôm nay")
        s2 = content.find("Điểm tin")
        s3 = content.find("Theo dõi")
        s4 = content.find("Lưu ý về nguồn")

        self.assertNotEqual(s1, -1, "Missing section 1: Tiêu điểm hôm nay")
        self.assertNotEqual(s2, -1, "Missing section 2: Điểm tin")
        self.assertNotEqual(s3, -1, "Missing section 3: Theo dõi")
        self.assertNotEqual(s4, -1, "Missing section 4: Lưu ý về nguồn")

        self.assertTrue(s1 < s2 < s3 < s4, "Four sections must appear in exact order")

    def test_plugin_root_layout_and_no_plugin_dir(self):
        self.assertFalse((ROOT_DIR / "plugin").exists(), "plugin/ directory must not exist")

        self.assertTrue((ROOT_DIR / ".claude-plugin" / "plugin.json").is_file(), "Missing .claude-plugin/plugin.json")
        self.assertTrue((ROOT_DIR / ".claude-plugin" / "marketplace.json").is_file(), "Missing .claude-plugin/marketplace.json")
        self.assertTrue((ROOT_DIR / "commands" / "tin-tai-chinh.md").is_file(), "Missing commands/tin-tai-chinh.md")
        self.assertTrue((ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md").is_file(), "Missing skills/fin-news-digest/SKILL.md")
        self.assertTrue((ROOT_DIR / "skills" / "fin-news-digest" / "config-guide.md").is_file(), "Missing skills/fin-news-digest/config-guide.md")
        self.assertTrue((ROOT_DIR / "agents" / "news-classifier.md").is_file(), "Missing agents/news-classifier.md")
        self.assertTrue((ROOT_DIR / "agents" / "cluster-merger.md").is_file(), "Missing agents/cluster-merger.md")

    def test_plugin_json_declares_no_component_paths_and_has_name_version(self):
        plugin_file = ROOT_DIR / ".claude-plugin" / "plugin.json"
        self.assertTrue(plugin_file.is_file(), f"Missing {plugin_file}")
        data = json.loads(plugin_file.read_text(encoding="utf-8"))
        self.assertEqual(data.get("name"), "fin-news")
        import re
        self.assertRegex(str(data.get("version", "")), r"^\d+\.\d+\.\d+$")
        self.assertIn("description", data)
        self.assertTrue(data["description"])

        self.assertNotIn("commands", data)
        self.assertNotIn("skills", data)
        self.assertNotIn("agents", data)

    def test_marketplace_json_valid_and_name_matches_plugin_json(self):
        mkt_file = ROOT_DIR / ".claude-plugin" / "marketplace.json"
        self.assertTrue(mkt_file.is_file(), f"Missing {mkt_file}")
        data = json.loads(mkt_file.read_text(encoding="utf-8"))

        self.assertIn("name", data)
        self.assertEqual(data["name"], "fin-news")
        self.assertIn("owner", data)
        self.assertIsInstance(data["owner"], dict)
        self.assertEqual(data["owner"].get("name"), "fin-news")
        self.assertIn("plugins", data)
        self.assertIsInstance(data["plugins"], list)
        self.assertGreaterEqual(len(data["plugins"]), 1)

        plugin_file = ROOT_DIR / ".claude-plugin" / "plugin.json"
        plugin_data = json.loads(plugin_file.read_text(encoding="utf-8")) if plugin_file.is_file() else {}

        plugin_entry = data["plugins"][0]
        self.assertEqual(plugin_entry.get("name"), plugin_data.get("name", "fin-news"))
        source = plugin_entry.get("source", "")
        self.assertTrue(source.startswith("./"), f"source '{source}' must start with './'")
        self.assertNotIn("..", source, f"source '{source}' must not contain '..'")

    def test_markdown_paths_use_plugin_root_variable(self):
        component_files = [
            ROOT_DIR / "commands" / "tin-tai-chinh.md",
            ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md",
            ROOT_DIR / "skills" / "fin-news-digest" / "config-guide.md",
            ROOT_DIR / "agents" / "news-classifier.md",
            ROOT_DIR / "agents" / "cluster-merger.md",
        ]

        bare_prompts_pattern = re.compile(r"(?<!\$\{CLAUDE_PLUGIN_ROOT\}/)prompts/")
        bare_launcher_pattern = re.compile(r"(?<!\$\{CLAUDE_PLUGIN_ROOT\}\\)(?<!\$\{CLAUDE_PLUGIN_ROOT\}/)\brun\.(cmd|sh)\b")

        for md_file in component_files:
            if not md_file.exists():
                self.fail(f"Missing component file {md_file}")
            text = md_file.read_text(encoding="utf-8")

            self.assertFalse(
                bare_prompts_pattern.search(text),
                f"File {md_file.name} contains bare 'prompts/' without ${{CLAUDE_PLUGIN_ROOT}}/"
            )
            self.assertFalse(
                bare_launcher_pattern.search(text),
                f"File {md_file.name} contains bare launcher call without ${{CLAUDE_PLUGIN_ROOT}}"
            )

    def test_skill_dispatches_scoped_agent_names_with_haiku(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        self.assertTrue(skill_file.is_file(), f"Missing {skill_file}")
        content = skill_file.read_text(encoding="utf-8")

        self.assertIn("fin-news:news-classifier", content)
        self.assertIn('model: "haiku"', content)

    def test_launchers_work_from_other_cwd(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            env = os.environ.copy()
            env["FIN_NEWS_HOME"] = tmp_dir
            launcher = ROOT_DIR / ("run.cmd" if os.name == "nt" else "run.sh")
            self.assertTrue(launcher.is_file(), f"Launcher {launcher} missing")

            res = subprocess.run(
                [str(launcher), "config", "get", "profile", "watchlist"],
                cwd=tmp_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertEqual(
                res.returncode, 0,
                f"Launcher failed when invoked from other cwd {tmp_dir}. Stderr: {res.stderr}"
            )

    def test_every_topic_slug_in_defaults_appears_in_classify_prompt(self):
        topics_file = ROOT_DIR / "defaults" / "topics.json"
        self.assertTrue(topics_file.is_file(), f"Missing {topics_file}")
        topics_data = json.loads(topics_file.read_text(encoding="utf-8")).get("topics", {})

        agent_file = ROOT_DIR / "agents" / "news-classifier.md"
        self.assertTrue(agent_file.is_file(), f"Missing {agent_file}")
        content = agent_file.read_text(encoding="utf-8")

        for slug in topics_data.keys():
            self.assertIn(
                slug, content,
                f"Topic slug '{slug}' from defaults/topics.json missing from agents/news-classifier.md"
            )

    def test_digest_template_has_energy_commodity_section_and_four_top_sections_in_order(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        self.assertTrue(skill_file.is_file(), f"Missing {skill_file}")
        content = skill_file.read_text(encoding="utf-8")

        self.assertIn("Năng lượng & Hàng hoá", content)

        s1 = content.find("Tiêu điểm hôm nay")
        s2 = content.find("Điểm tin")
        s3 = content.find("Theo dõi")
        s4 = content.find("Lưu ý về nguồn")

        self.assertNotEqual(s1, -1, "Missing section: Tiêu điểm hôm nay")
        self.assertNotEqual(s2, -1, "Missing section: Điểm tin")
        self.assertNotEqual(s3, -1, "Missing section: Theo dõi")
        self.assertNotEqual(s4, -1, "Missing section: Lưu ý về nguồn")
        self.assertTrue(s1 < s2 < s3 < s4, "Four top sections must appear in exact order")

        s_energy = content.find("Năng lượng & Hàng hoá")
        self.assertTrue(s2 < s_energy < s3, "Energy & commodity subsection must be under 'Điểm tin'")

    def test_classify_prompt_states_noise_has_empty_topics_and_foreign_rate_rule(self):
        agent_file = ROOT_DIR / "agents" / "news-classifier.md"
        self.assertTrue(agent_file.is_file(), f"Missing {agent_file}")
        content = agent_file.read_text(encoding="utf-8")

        self.assertIn("vi-mo-chinh-sach", content)
        self.assertTrue(
            "ngân hàng trung ương" in content.lower() or "lãi suất" in content.lower(),
            "news-classifier.md must specify foreign central bank rate rule"
        )

        self.assertIn("trai-phieu", content)
        self.assertTrue(
            "trái phiếu" in content.lower(),
            "news-classifier.md must specify trai-phieu rule"
        )

        self.assertIn("noise", content)
        self.assertTrue(
            "topics" in content and "trống" in content,
            "news-classifier.md must specify noise has empty topics"
        )

    # --- Part 4 requirement tests ---

    def test_skill_is_within_size_budget_and_has_communication_rules(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        self.assertTrue(skill_file.is_file(), f"Missing {skill_file}")
        content = skill_file.read_text(encoding="utf-8")

        self.assertLessEqual(len(content), 7000, f"SKILL.md length {len(content)} exceeds 7000 chars")
        self.assertIn("Đang thu thập tin…", content)
        self.assertIn("Đang phân loại…", content)
        self.assertIn("Đang tổng hợp bản tin…", content)
        self.assertIn("Không tường thuật từng bước", content)

    def test_skill_embeds_digest_rules_and_references_config_guide(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")

        self.assertIn("${CLAUDE_PLUGIN_ROOT}/skills/fin-news-digest/config-guide.md", content)
        self.assertIn("700–900 từ", content)
        self.assertIn("(nhận định của AI)", content)

    def test_skill_default_procedure_has_no_merge_or_fulltext_step(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")

        # Find default procedure section
        start = content.find("## Quy trình thực thi mặc định")
        end = content.find("## Cấu trúc Bản tin")
        self.assertNotEqual(start, -1)
        proc_text = content[start:end] if end != -1 else content[start:]

        # Must not contain merge step or fulltext step in the default step list
        self.assertNotIn("Chạy launcher với lệnh `merge`", proc_text)
        self.assertNotIn("Bước 5: Trích xuất tin toàn văn", proc_text)
        self.assertNotIn("Chạy launcher với lệnh `fulltext`", proc_text)

    def test_digest_template_in_skill_lists_sections_in_order(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        content = skill_file.read_text(encoding="utf-8")

        pos_tieu_diem = content.find("Tiêu điểm hôm nay")
        pos_diem_tin = content.find("Điểm tin")
        pos_theo_doi = content.find("Theo dõi")
        pos_luu_y = content.find("Lưu ý về nguồn")

        self.assertNotEqual(pos_tieu_diem, -1)
        self.assertNotEqual(pos_diem_tin, -1)
        self.assertNotEqual(pos_theo_doi, -1)
        self.assertNotEqual(pos_luu_y, -1)

        self.assertTrue(
            pos_tieu_diem < pos_diem_tin < pos_theo_doi < pos_luu_y,
            "Digest sections must appear in exact order"
        )

    def test_deleted_prompt_files_are_not_referenced_anywhere(self):
        deleted_files = ["classify.md", "synthesize.md", "digest-template.md"]
        for df in deleted_files:
            self.assertFalse((PROMPTS_DIR / df).exists(), f"{df} should be deleted from prompts/")

        # Check references in core/, agents/, commands/, skills/, .claude-plugin/, and root docs
        check_dirs = [
            ROOT_DIR / "core",
            ROOT_DIR / "agents",
            ROOT_DIR / "commands",
            ROOT_DIR / "skills",
            ROOT_DIR / ".claude-plugin",
        ]
        doc_files = [
            ROOT_DIR / "AGENTS.md",
            ROOT_DIR / "CONFIGURE.md",
            ROOT_DIR / "INSTALL.md",
            ROOT_DIR / "SCHEDULE.md",
            ROOT_DIR / "TROUBLESHOOT.md",
        ]

        all_files = list(doc_files)
        for d in check_dirs:
            if d.exists():
                all_files.extend(p for p in d.rglob("*") if p.is_file() and p.suffix in (".py", ".md", ".json"))

        for file_path in all_files:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
            for df in deleted_files:
                self.assertNotIn(
                    df, text,
                    f"Deleted prompt file '{df}' is still referenced in {file_path}"
                )


if __name__ == "__main__":
    unittest.main()
