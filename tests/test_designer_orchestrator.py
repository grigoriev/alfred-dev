#!/usr/bin/env python3
"""Tests for the Designer orchestrator functions (the stylist)."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.config_loader import has_frontend
from core.orchestrator import (
    FLOWS, create_session, advance_phase, check_gate,
)


class TestHasFrontend(unittest.TestCase):
    """Verify that has_frontend correctly identifies frameworks with a UI."""

    # --- Frameworks with a user interface (must return True) ---

    def test_next(self):
        stack = {"framework": "next", "runtime": "node", "language": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_react(self):
        stack = {"framework": "react", "runtime": "node", "language": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_vue(self):
        stack = {"framework": "vue", "runtime": "node", "language": "javascript"}
        self.assertTrue(has_frontend(stack))

    def test_svelte(self):
        stack = {"framework": "svelte", "runtime": "node", "language": "javascript"}
        self.assertTrue(has_frontend(stack))

    def test_astro(self):
        stack = {"framework": "astro", "runtime": "node", "language": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_angular(self):
        stack = {"framework": "angular", "runtime": "node", "language": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_remix(self):
        stack = {"framework": "remix", "runtime": "node", "language": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_gatsby(self):
        stack = {"framework": "gatsby", "runtime": "node", "language": "javascript"}
        self.assertTrue(has_frontend(stack))

    def test_nuxt(self):
        stack = {"framework": "nuxt", "runtime": "node", "language": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_solid_js(self):
        stack = {"framework": "solid-js", "runtime": "node", "language": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_qwik(self):
        stack = {"framework": "qwik", "runtime": "node", "language": "typescript"}
        self.assertTrue(has_frontend(stack))

    # --- Frameworks without a user interface (must return False) ---

    def test_fastapi(self):
        stack = {"framework": "fastapi", "runtime": "python", "language": "python"}
        self.assertFalse(has_frontend(stack))

    def test_express(self):
        stack = {"framework": "express", "runtime": "node", "language": "javascript"}
        self.assertFalse(has_frontend(stack))

    def test_django(self):
        stack = {"framework": "django", "runtime": "python", "language": "python"}
        self.assertFalse(has_frontend(stack))

    def test_unknown_sentinel_framework(self):
        stack = {"framework": "unknown", "runtime": "node", "language": "javascript"}
        self.assertFalse(has_frontend(stack))

    def test_no_framework(self):
        """A stack without a 'framework' key must return False (default value)."""
        stack = {"runtime": "node", "language": "javascript"}
        self.assertFalse(has_frontend(stack))


class TestDesignerPhase(unittest.TestCase):
    """Verify that the visual_style phase is integrated correctly."""

    def test_feature_flow_has_7_phases(self):
        self.assertEqual(len(FLOWS["feature"]["phases"]), 7)

    def test_visual_style_is_phase_1(self):
        phase = FLOWS["feature"]["phases"][1]
        self.assertEqual(phase["name"], "visual_style")

    def test_visual_style_uses_designer(self):
        phase = FLOWS["feature"]["phases"][1]
        self.assertEqual(phase["agents"], ["designer"])

    def test_visual_style_gate_is_user(self):
        phase = FLOWS["feature"]["phases"][1]
        self.assertEqual(phase["gate_type"], "user")

    def test_visual_style_has_condition(self):
        phase = FLOWS["feature"]["phases"][1]
        self.assertEqual(phase.get("condition"), "has_frontend")

    def test_architecture_is_now_phase_2(self):
        phase = FLOWS["feature"]["phases"][2]
        self.assertEqual(phase["name"], "architecture")

    def test_fix_flow_unchanged(self):
        self.assertEqual(len(FLOWS["fix"]["phases"]), 3)

    def test_quick_flow_unchanged(self):
        self.assertEqual(len(FLOWS["quick"]["phases"]), 2)

    def test_session_starts_at_product(self):
        session = create_session("feature", "App with frontend")
        self.assertEqual(session["current_phase"], "product")

    def test_advance_from_product_goes_to_visual_style(self):
        session = create_session("feature", "App with frontend")
        session = advance_phase(session, result="approved")
        self.assertEqual(session["current_phase"], "visual_style")

    def test_advance_from_visual_style_goes_to_architecture(self):
        session = create_session("feature", "App with frontend")
        session = advance_phase(session, result="approved")
        self.assertEqual(session["current_phase"], "visual_style")
        session = advance_phase(session, result="approved")
        self.assertEqual(session["current_phase"], "architecture")


class TestDesignerFullFlow(unittest.TestCase):
    """Verify the full feature flow with Designer."""

    def test_full_feature_flow_with_designer(self):
        """Walk through the 7 phases of the feature flow."""
        session = create_session("feature", "App with dashboard")

        # Phase 0: product
        self.assertEqual(session["current_phase"], "product")
        session = advance_phase(session, result="approved")

        # Phase 1: visual_style
        self.assertEqual(session["current_phase"], "visual_style")
        session = advance_phase(session, result="approved")

        # Phase 2: architecture
        self.assertEqual(session["current_phase"], "architecture")
        session = advance_phase(session, result="approved", security_ok=True)

        # Phase 3: development
        self.assertEqual(session["current_phase"], "development")
        session = advance_phase(session, result="approved", tests_ok=True)

        # Phase 4: quality
        self.assertEqual(session["current_phase"], "quality")
        session = advance_phase(
            session, result="approved", security_ok=True, tests_ok=True,
        )

        # Phase 5: documentation
        self.assertEqual(session["current_phase"], "documentation")
        session = advance_phase(session, result="approved")

        # Phase 6: delivery
        self.assertEqual(session["current_phase"], "delivery")
        session = advance_phase(session, result="approved", security_ok=True)

        # Completed
        self.assertEqual(session["current_phase"], "completed")
        self.assertEqual(len(session["completed_phases"]), 7)

    def test_visual_style_gate_rejects_without_approval(self):
        """The visual_style gate rejects without approval."""
        session = create_session("feature", "App with UI")
        session = advance_phase(session, result="approved")
        self.assertEqual(session["current_phase"], "visual_style")

        result = check_gate(session, result="rejected")
        self.assertFalse(result["passed"])


class TestDesignerSkippedWhenNoFrontend(unittest.TestCase):
    """Verify that visual_style is skipped in projects without a frontend."""

    def test_skip_visual_style_when_no_frontend(self):
        """With a stack without a frontend, visual_style is skipped."""
        session = create_session("feature", "API backend")
        session["stack"] = {"framework": "fastapi", "runtime": "python", "language": "python"}
        session = advance_phase(session, result="approved")  # product -> must skip visual_style
        self.assertEqual(session["current_phase"], "architecture")
        # Verify that visual_style is recorded as skipped
        skipped = [f for f in session["completed_phases"] if f["name"] == "visual_style"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["result"], "skipped")

    def test_visual_style_executes_when_frontend(self):
        """With a stack with a frontend, visual_style runs normally."""
        session = create_session("feature", "App Next.js")
        session["stack"] = {"framework": "next", "runtime": "node", "language": "typescript"}
        session = advance_phase(session, result="approved")  # product -> visual_style
        self.assertEqual(session["current_phase"], "visual_style")

    def test_skip_when_no_stack_in_session(self):
        """Without a stack in the session, the condition is not evaluated and the phase runs."""
        session = create_session("feature", "New project")
        # No stack: the condition cannot be evaluated, so the phase runs
        session = advance_phase(session, result="approved")
        self.assertEqual(session["current_phase"], "visual_style")


if __name__ == "__main__":
    unittest.main()
