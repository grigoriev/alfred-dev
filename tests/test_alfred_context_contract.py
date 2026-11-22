#!/usr/bin/env python3
"""Contract for the Alfred Dev context assistant."""

import os
import unittest


_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(relative_path: str) -> str:
    path = os.path.normpath(os.path.join(_PROJECT_ROOT, relative_path))
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class TestAlfredContextContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.command = _read("commands/alfred.md")

    def test_reads_continuity_artifacts_before_routing(self):
        self.assertIn('python3 .claude/alfred-continuity.py consume-prefetch "$PWD" --expected alfred', self.command)
        self.assertIn(".claude/alfred-dev-state.json", self.command)
        self.assertIn(".claude/alfred-handoff.json", self.command)
        self.assertIn(".claude/alfred-uat.json", self.command)
        self.assertIn("docs/project/discovery.md", self.command)
        self.assertIn("docs/project/current.md", self.command)
        self.assertIn("docs/project/codebase-map.md", self.command)
        self.assertIn("docs/project/uat.md", self.command)
        self.assertIn('python3 .claude/alfred-continuity.py next "$PWD" --json', self.command)

    def test_routes_to_operational_commands_first(self):
        self.assertIn("действуй как `/alfred-dev:resume`", self.command)
        self.assertIn("действуй как `/alfred-dev:pause`", self.command)
        self.assertIn("действуй как `/alfred-dev:progress`", self.command)
        self.assertIn("действуй как `/alfred-dev:uat`", self.command)
        self.assertIn("действуй как `/alfred-dev:update`", self.command)
        self.assertIn("действуй как `/alfred-dev:cto`", self.command)
        self.assertIn("действуй как `/alfred-dev:discuss`", self.command)
        self.assertIn("действуй как `/alfred-dev:quick`", self.command)
        self.assertIn("действуй как `/alfred-dev:map-codebase`", self.command)
        self.assertIn("также отдавай приоритет", self.command)
        self.assertIn("не запускал мультиагентную команду «вслепую»", self.command)

    def test_routes_new_work_to_core_flows(self):
        self.assertIn("/alfred-dev:feature", self.command)
        self.assertIn("/alfred-dev:discuss", self.command)
        self.assertIn("/alfred-dev:quick", self.command)
        self.assertIn("/alfred-dev:fix", self.command)
        self.assertIn("/alfred-dev:spike", self.command)
        self.assertIn("/alfred-dev:audit", self.command)
        self.assertIn("/alfred-dev:uat", self.command)
        self.assertIn("/alfred-dev:ship", self.command)
        self.assertIn("/alfred-dev:cto", self.command)
        self.assertIn("/alfred-dev:update", self.command)
        self.assertIn("НЕ оставляй это немым перенаправлением", self.command)
        self.assertIn("НЕ повторяй `Bash`", self.command)

    def test_avoids_old_command_prefix_and_default_menu(self):
        self.assertIn("НЕ используй старые названия плагина без префикса `-dev`", self.command)
        self.assertNotIn("`/alfred feature`", self.command)
        self.assertIn("НЕ предлагай общее меню, если следующий шаг очевиден", self.command)
        self.assertIn("AskUserQuestion", self.command)
        self.assertIn("настоящим выбираемым меню", self.command)


if __name__ == "__main__":
    unittest.main()
