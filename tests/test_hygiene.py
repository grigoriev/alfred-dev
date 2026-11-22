#!/usr/bin/env python3
"""Pre-pain hygiene and a shareable wrap-up (closing)."""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.hygiene import build_closing, render_closing_markdown, run_hygiene
from core.project_docs import FILLED_MARKER, SCAFFOLD_MARKER, ensure_project_docs


class TestHygiene(unittest.TestCase):
    def test_ship_blocks_pending_uat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude = os.path.join(tmpdir, ".claude")
            os.makedirs(claude, exist_ok=True)
            with open(os.path.join(claude, "alfred-uat.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "status": "pending",
                        "target_id": "quick-1",
                        "updated_at": "2026-08-15T10:00:00+00:00",
                    },
                    handle,
                )
            # suggest_verify_action needs a completed session
            with open(os.path.join(claude, "alfred-dev-state.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "command": "quick",
                        "description": "CTA",
                        "current_phase": "completed",
                        "phase_number": 1,
                    },
                    handle,
                )
            result = run_hygiene(tmpdir, "ship")
            self.assertFalse(result["passed"])
            self.assertTrue(any("UAT" in item for item in result["blockers"]))

    def test_filled_architecture_with_scaffold_threat_model_blocks_ship(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_project_docs(tmpdir)
            architecture = os.path.join(tmpdir, "docs/project/architecture.md")
            with open(architecture, "w", encoding="utf-8") as handle:
                handle.write(f"# Architecture\n\n{FILLED_MARKER}\n\nReal boxes.\n")
            result = run_hygiene(tmpdir, "ship")
            self.assertFalse(result["passed"])
            self.assertTrue(any("threat-model" in item for item in result["blockers"]))

    def test_closing_is_shareable(self):
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
            with open(os.path.join(claude, "alfred-evidence.json"), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "command": "pytest tests/test_cta.py",
                        "result": "pass",
                    },
                    handle,
                )
            closing = build_closing(tmpdir)
            text = render_closing_markdown(closing)
            self.assertIn("change the CTA", text)
            self.assertIn("pytest tests/test_cta.py", text)
            self.assertIn("Итог Alfred", text)


if __name__ == "__main__":
    unittest.main()
