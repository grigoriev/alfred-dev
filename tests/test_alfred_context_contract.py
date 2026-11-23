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
        self.assertIn("act as `/alfred-dev:resume`", self.command)
        self.assertIn("act as `/alfred-dev:pause`", self.command)
        self.assertIn("act as `/alfred-dev:progress`", self.command)
        self.assertIn("act as `/alfred-dev:uat`", self.command)
        self.assertIn("act as `/alfred-dev:update`", self.command)
        self.assertIn("act as `/alfred-dev:cto`", self.command)
        self.assertIn("act as `/alfred-dev:discuss`", self.command)
        self.assertIn("act as `/alfred-dev:quick`", self.command)
        self.assertIn("act as `/alfred-dev:map-codebase`", self.command)
        self.assertIn("also give priority", self.command)
        self.assertIn("does not start a multi-agent team \"blind\"", self.command)

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
        self.assertIn("do NOT leave it as a silent redirect", self.command)
        self.assertIn("do NOT retry `Bash`", self.command)

    def test_avoids_old_command_prefix_and_default_menu(self):
        self.assertIn("Do NOT use old plugin names without the `-dev` prefix", self.command)
        self.assertNotIn("`/alfred feature`", self.command)
        self.assertIn("Do NOT offer a general menu if the next step is obvious", self.command)
        self.assertIn("AskUserQuestion", self.command)
        self.assertIn("a real selectable menu", self.command)


if __name__ == "__main__":
    unittest.main()
