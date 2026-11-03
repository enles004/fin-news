import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

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
        classify_file = PROMPTS_DIR / "classify.md"
        self.assertTrue(classify_file.exists(), f"Missing {classify_file}")
        content = classify_file.read_text(encoding="utf-8")
        schema_fields = [
            "id",
            "topics",
            "summary_vi",
            "entities",
            "importance",
            "importance_reason",
            "event_key",
            "is_noise",
        ]
        for field in schema_fields:
            self.assertIn(field, content, f"Schema field '{field}' missing from classify.md")

    def test_skill_mentions_every_cli_subcommand_it_uses(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        self.assertTrue(skill_file.exists(), f"Missing {skill_file}")
        content = skill_file.read_text(encoding="utf-8")

        # Get list of subparsers defined in cli.py
        expected_cmds = [
            "fetch", "prepare", "collect", "cluster", "merge", "fulltext",
            "health", "config", "add-source", "test-source", "doctor", "run"
        ]
        for cmd in expected_cmds:
            self.assertIn(cmd, content, f"Subcommand '{cmd}' not mentioned in SKILL.md")

    def test_cluster_merger_agent_declares_haiku(self):
        agent_file = ROOT_DIR / "agents" / "cluster-merger.md"
        self.assertTrue(agent_file.exists(), f"Missing {agent_file}")
        content = agent_file.read_text(encoding="utf-8")
        self.assertRegex(content, r"(?i)model:\s*haiku")

    def test_plugin_json_references_cluster_merger(self):
        # Auto-discovered at agents/cluster-merger.md without needing explicit declaration in plugin.json
        agent_file = ROOT_DIR / "agents" / "cluster-merger.md"
        self.assertTrue(agent_file.exists(), f"Missing {agent_file}")
        plugin_file = ROOT_DIR / ".claude-plugin" / "plugin.json"
        self.assertTrue(plugin_file.exists(), f"Missing {plugin_file}")
        data = json.loads(plugin_file.read_text(encoding="utf-8"))
        self.assertNotIn("agents", data)

    def test_skill_mentions_merge_command(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        self.assertTrue(skill_file.exists(), f"Missing {skill_file}")
        content = skill_file.read_text(encoding="utf-8")
        self.assertIn("merge", content)

    def test_merge_prompt_requires_json_groups_only(self):
        merge_file = PROMPTS_DIR / "merge.md"
        self.assertTrue(merge_file.exists(), f"Missing {merge_file}")
        content = merge_file.read_text(encoding="utf-8")
        self.assertIn("groups", content)
        self.assertRegex(content, r"(?i)json")

    def test_digest_template_has_four_sections_in_order(self):
        template_file = PROMPTS_DIR / "digest-template.md"
        self.assertTrue(template_file.exists(), f"Missing {template_file}")
        content = template_file.read_text(encoding="utf-8")

        s1 = content.find("Tiêu điểm")
        s2 = content.find("Theo chủ đề")
        s3 = content.find("Theo dõi")
        s4 = content.find("Sức khoẻ nguồn")

        self.assertNotEqual(s1, -1, "Missing section 1: Tiêu điểm")
        self.assertNotEqual(s2, -1, "Missing section 2: Theo chủ đề")
        self.assertNotEqual(s3, -1, "Missing section 3: Theo dõi")
        self.assertNotEqual(s4, -1, "Missing section 4: Sức khoẻ nguồn")

        self.assertTrue(s1 < s2 < s3 < s4, "Four sections must appear in exact order")

    def test_plugin_root_layout_and_no_plugin_dir(self):
        # plugin/ directory must be absent
        self.assertFalse((ROOT_DIR / "plugin").exists(), "plugin/ directory must not exist")

        # Files must exist at their new root-relative locations
        self.assertTrue((ROOT_DIR / ".claude-plugin" / "plugin.json").is_file(), "Missing .claude-plugin/plugin.json")
        self.assertTrue((ROOT_DIR / ".claude-plugin" / "marketplace.json").is_file(), "Missing .claude-plugin/marketplace.json")
        self.assertTrue((ROOT_DIR / "commands" / "tin-tai-chinh.md").is_file(), "Missing commands/tin-tai-chinh.md")
        self.assertTrue((ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md").is_file(), "Missing skills/fin-news-digest/SKILL.md")
        self.assertTrue((ROOT_DIR / "agents" / "news-classifier.md").is_file(), "Missing agents/news-classifier.md")
        self.assertTrue((ROOT_DIR / "agents" / "cluster-merger.md").is_file(), "Missing agents/cluster-merger.md")

    def test_plugin_json_declares_no_component_paths_and_has_name_version(self):
        plugin_file = ROOT_DIR / ".claude-plugin" / "plugin.json"
        self.assertTrue(plugin_file.is_file(), f"Missing {plugin_file}")
        data = json.loads(plugin_file.read_text(encoding="utf-8"))
        self.assertEqual(data.get("name"), "fin-news")
        self.assertEqual(data.get("version"), "1.0.0")
        self.assertIn("description", data)
        self.assertTrue(data["description"])

        # Must NOT declare commands, skills, or agents keys
        self.assertNotIn("commands", data, "plugin.json should not declare commands key")
        self.assertNotIn("skills", data, "plugin.json should not declare skills key")
        self.assertNotIn("agents", data, "plugin.json should not declare agents key")

    def test_marketplace_json_valid_and_name_matches_plugin_json(self):
        mkt_file = ROOT_DIR / ".claude-plugin" / "marketplace.json"
        self.assertTrue(mkt_file.is_file(), f"Missing {mkt_file}")
        data = json.loads(mkt_file.read_text(encoding="utf-8"))

        # Required keys: name, owner, plugins
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
            ROOT_DIR / "agents" / "news-classifier.md",
            ROOT_DIR / "agents" / "cluster-merger.md",
        ]

        bare_prompts_pattern = re.compile(r"(?<!\$\{CLAUDE_PLUGIN_ROOT\}/)prompts/")
        bare_launcher_pattern = re.compile(r"(?<!\$\{CLAUDE_PLUGIN_ROOT\}\\)(?<!\$\{CLAUDE_PLUGIN_ROOT\}/)\brun\.(cmd|sh)\b")

        for md_file in component_files:
            if not md_file.exists():
                self.fail(f"Missing component file {md_file}")
            text = md_file.read_text(encoding="utf-8")

            # No bare prompts/ path
            self.assertFalse(
                bare_prompts_pattern.search(text),
                f"File {md_file.name} contains bare 'prompts/' without ${{CLAUDE_PLUGIN_ROOT}}/"
            )

            # No bare launcher call
            self.assertFalse(
                bare_launcher_pattern.search(text),
                f"File {md_file.name} contains bare launcher call without ${{CLAUDE_PLUGIN_ROOT}}"
            )

            # If the file references prompts or CLI launcher, it must contain ${CLAUDE_PLUGIN_ROOT}
            if "prompt" in text.lower() or "run.cmd" in text or "run.sh" in text:
                self.assertIn(
                    "${CLAUDE_PLUGIN_ROOT}",
                    text,
                    f"File {md_file.name} references prompts/CLI but does not contain ${{CLAUDE_PLUGIN_ROOT}}"
                )

    def test_skill_dispatches_scoped_agent_names_with_haiku(self):
        skill_file = ROOT_DIR / "skills" / "fin-news-digest" / "SKILL.md"
        self.assertTrue(skill_file.is_file(), f"Missing {skill_file}")
        content = skill_file.read_text(encoding="utf-8")

        self.assertIn("fin-news:news-classifier", content)
        self.assertIn("fin-news:cluster-merger", content)
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

        classify_file = PROMPTS_DIR / "classify.md"
        self.assertTrue(classify_file.is_file(), f"Missing {classify_file}")
        classify_content = classify_file.read_text(encoding="utf-8")

        for slug in topics_data.keys():
            self.assertIn(
                slug, classify_content,
                f"Topic slug '{slug}' from defaults/topics.json missing from prompts/classify.md"
            )

    def test_digest_template_has_energy_commodity_section_and_four_top_sections_in_order(self):
        template_file = PROMPTS_DIR / "digest-template.md"
        self.assertTrue(template_file.is_file(), f"Missing {template_file}")
        content = template_file.read_text(encoding="utf-8")

        # Must have energy & commodity subsection
        self.assertIn("Năng lượng & Hàng hoá", content)

        # Four top-level sections in exact order
        s1 = content.find("Tiêu điểm")
        s2 = content.find("Theo chủ đề")
        s3 = content.find("Theo dõi")
        s4 = content.find("Sức khoẻ nguồn")

        self.assertNotEqual(s1, -1, "Missing section: Tiêu điểm")
        self.assertNotEqual(s2, -1, "Missing section: Theo chủ đề")
        self.assertNotEqual(s3, -1, "Missing section: Theo dõi")
        self.assertNotEqual(s4, -1, "Missing section: Sức khoẻ nguồn")
        self.assertTrue(s1 < s2 < s3 < s4, "Four top sections must appear in exact order")

        # Energy section must appear after "Theo chủ đề" and before "Theo dõi"
        s_energy = content.find("Năng lượng & Hàng hoá")
        self.assertTrue(s2 < s_energy < s3, "Energy & commodity subsection must be under 'Theo chủ đề'")

    def test_classify_prompt_states_noise_has_empty_topics_and_foreign_rate_rule(self):
        classify_file = PROMPTS_DIR / "classify.md"
        self.assertTrue(classify_file.is_file(), f"Missing {classify_file}")
        content = classify_file.read_text(encoding="utf-8")

        # Foreign central bank rate decision is vi-mo-chinh-sach
        self.assertIn("vi-mo-chinh-sach", content)
        self.assertTrue(
            "ngân hàng trung ương" in content.lower() or "lãi suất" in content.lower(),
            "classify.md must specify foreign central bank rate rule"
        )

        # trai-phieu is only for bonds
        self.assertIn("trai-phieu", content)
        self.assertTrue(
            "trái phiếu" in content.lower(),
            "classify.md must specify trai-phieu rule"
        )

        # is_noise true -> topics must be []
        self.assertIn("is_noise", content)
        self.assertIn("[]", content)


if __name__ == "__main__":
    unittest.main()
