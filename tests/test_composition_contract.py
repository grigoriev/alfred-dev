#!/usr/bin/env python3
"""Contract for the dynamic composition protocol."""

import os
import unittest


_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _read(relative_path: str) -> str:
    path = os.path.normpath(os.path.join(_PROJECT_ROOT, relative_path))
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


class TestCompositionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.command = _read("commands/_composition.md")

    def test_missing_autonomy_bootstraps_cli_defaults(self):
        self.assertIn("Do NOT use `AskUserQuestion` in this initial bootstrap", self.command)
        self.assertIn("product: autonomous", self.command)
        self.assertIn("architecture: autonomous", self.command)
        self.assertIn("development: autonomous", self.command)
        self.assertIn("quality: autonomous", self.command)
        self.assertIn("documentation: autonomous", self.command)
        self.assertIn("delivery: autonomous", self.command)

    def test_bootstrap_points_to_current_config_command(self):
        self.assertIn("/alfred-dev:config", self.command)
        self.assertIn("/alfred-dev:quick", self.command)
        self.assertNotIn("/alfred config", self.command)


if __name__ == "__main__":
    unittest.main()
