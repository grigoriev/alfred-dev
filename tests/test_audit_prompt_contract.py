#!/usr/bin/env python3
"""Contract tests for the audit and SonarQube prompts.

These tests protect behavior defined in Markdown. The plugin commands and
skills are prompts that Claude Code executes, so their instructions are part
of the system logic and are checked as a text contract.
"""

import os
import unicodedata
import unittest


_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(relative_path: str) -> str:
    path = os.path.normpath(os.path.join(_PROJECT_ROOT, relative_path))
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


class TestAuditCommandContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = _read("commands/audit.md")
        cls.audit_norm = _normalize(cls.audit)

    def test_audit_has_sonarqube_preflight_section(self):
        self.assertIn("## SonarQube preflight", self.audit)
        self.assertIn("docker --version", self.audit)
        self.assertIn("docker info", self.audit)

    def test_audit_asks_before_installing_or_starting_docker(self):
        self.assertIn("AskUserQuestion", self.audit)
        self.assertIn("do NOT try to install it yourself", self.audit)
        self.assertIn("do NOT try to start it yourself", self.audit)

    def test_audit_keeps_permission_prompt_even_in_autopilot(self):
        self.assertIn("even if the project is in autopilot mode", self.audit)
        self.assertIn("needs explicit user confirmation", self.audit)

    def test_audit_forbids_silent_sonarqube_skip(self):
        self.assertIn("NEVER skip it without recording it in writing", self.audit)
        self.assertIn("SonarQube was skipped by explicit user decision", self.audit)

    def test_audit_locates_plugin_files_outside_the_project(self):
        self.assertIn("${CLAUDE_PLUGIN_ROOT}/commands/_composition.md", self.audit)


class TestSonarQubeSkillContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = _read("skills/sonarqube/SKILL.md")
        cls.skill_norm = _normalize(cls.skill)

    def test_skill_requires_explicit_permission_for_docker_changes(self):
        self.assertIn(
            "Do not install Docker, open Docker Desktop or start the daemon without explicit user approval.",
            self.skill,
        )
        self.assertIn(
            "If there is no prior permission, ask for it now and wait for the answer.",
            self.skill,
        )

    def test_skill_handles_port_conflicts_and_cleanup(self):
        self.assertIn("Check whether port `9000` is in use", self.skill)
        self.assertIn("docker rm -f sonarqube-alfred", self.skill)
        self.assertIn("still try to do the final cleanup of the temporary container", self.skill)

    def test_skill_mentions_zsh_safe_status_variable(self):
        self.assertIn("Do not use the `status` variable", self.skill)
        self.assertIn("use `sonar_status`", self.skill)


class TestHelpContract(unittest.TestCase):
    def test_help_lists_the_nine_core_agents(self):
        help_md = _read("commands/alfred.md")
        self.assertIn("/alfred-dev:feature", help_md)
        self.assertIn("Agent Teams", help_md)


if __name__ == "__main__":
    unittest.main()
