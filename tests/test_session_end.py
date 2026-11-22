#!/usr/bin/env python3
"""SessionEnd writes the closing summary if there was work."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.hygiene import write_session_closing


class TestSessionEndCierre(unittest.TestCase):
    def test_skips_empty_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.assertIsNone(write_session_closing(tmpdir))
            self.assertFalse(
                os.path.exists(os.path.join(tmpdir, ".claude", "alfred-last-closing.md"))
            )

    def test_writes_closing_when_session_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude = os.path.join(tmpdir, ".claude")
            os.makedirs(claude, exist_ok=True)
            with open(os.path.join(claude, "alfred-dev-state.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "command": "quick",
                        "description": "change the CTA",
                        "current_phase": "quick_validation",
                        "phase_number": 1,
                    },
                    handle,
                )
            path = write_session_closing(tmpdir)
            self.assertIsNotNone(path)
            text = open(path, encoding="utf-8").read()
            self.assertIn("Итог Alfred", text)
            self.assertIn("change the CTA", text)

    def test_hook_exits_zero(self):
        script = os.path.join(os.path.dirname(__file__), "..", "hooks", "session-end.py")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [sys.executable, script],
                cwd=tmpdir,
                input="{}",
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
