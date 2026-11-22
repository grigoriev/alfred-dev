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
        stack = {"framework": "next", "runtime": "node", "lenguaje": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_react(self):
        stack = {"framework": "react", "runtime": "node", "lenguaje": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_vue(self):
        stack = {"framework": "vue", "runtime": "node", "lenguaje": "javascript"}
        self.assertTrue(has_frontend(stack))

    def test_svelte(self):
        stack = {"framework": "svelte", "runtime": "node", "lenguaje": "javascript"}
        self.assertTrue(has_frontend(stack))

    def test_astro(self):
        stack = {"framework": "astro", "runtime": "node", "lenguaje": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_angular(self):
        stack = {"framework": "angular", "runtime": "node", "lenguaje": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_remix(self):
        stack = {"framework": "remix", "runtime": "node", "lenguaje": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_gatsby(self):
        stack = {"framework": "gatsby", "runtime": "node", "lenguaje": "javascript"}
        self.assertTrue(has_frontend(stack))

    def test_nuxt(self):
        stack = {"framework": "nuxt", "runtime": "node", "lenguaje": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_solid_js(self):
        stack = {"framework": "solid-js", "runtime": "node", "lenguaje": "typescript"}
        self.assertTrue(has_frontend(stack))

    def test_qwik(self):
        stack = {"framework": "qwik", "runtime": "node", "lenguaje": "typescript"}
        self.assertTrue(has_frontend(stack))

    # --- Frameworks without a user interface (must return False) ---

    def test_fastapi(self):
        stack = {"framework": "fastapi", "runtime": "python", "lenguaje": "python"}
        self.assertFalse(has_frontend(stack))

    def test_express(self):
        stack = {"framework": "express", "runtime": "node", "lenguaje": "javascript"}
        self.assertFalse(has_frontend(stack))

    def test_django(self):
        stack = {"framework": "django", "runtime": "python", "lenguaje": "python"}
        self.assertFalse(has_frontend(stack))

    def test_desconocido_sentinel_framework(self):
        stack = {"framework": "desconocido", "runtime": "node", "lenguaje": "javascript"}
        self.assertFalse(has_frontend(stack))

    def test_no_framework(self):
        """A stack without a 'framework' key must return False (default value)."""
        stack = {"runtime": "node", "lenguaje": "javascript"}
        self.assertFalse(has_frontend(stack))


class TestDesignerPhase(unittest.TestCase):
    """Verify that the estilo_visual phase is integrated correctly."""

    def test_feature_flow_has_7_phases(self):
        self.assertEqual(len(FLOWS["feature"]["fases"]), 7)

    def test_estilo_visual_is_phase_1(self):
        fase = FLOWS["feature"]["fases"][1]
        self.assertEqual(fase["nombre"], "estilo_visual")

    def test_estilo_visual_uses_designer(self):
        fase = FLOWS["feature"]["fases"][1]
        self.assertEqual(fase["agentes"], ["designer"])

    def test_estilo_visual_gate_is_usuario(self):
        fase = FLOWS["feature"]["fases"][1]
        self.assertEqual(fase["gate_tipo"], "usuario")

    def test_estilo_visual_has_condicion(self):
        fase = FLOWS["feature"]["fases"][1]
        self.assertEqual(fase.get("condicion"), "tiene_frontend")

    def test_arquitectura_is_now_phase_2(self):
        fase = FLOWS["feature"]["fases"][2]
        self.assertEqual(fase["nombre"], "arquitectura")

    def test_fix_flow_unchanged(self):
        self.assertEqual(len(FLOWS["fix"]["fases"]), 3)

    def test_quick_flow_unchanged(self):
        self.assertEqual(len(FLOWS["quick"]["fases"]), 2)

    def test_session_starts_at_producto(self):
        session = create_session("feature", "App with frontend")
        self.assertEqual(session["fase_actual"], "producto")

    def test_advance_from_producto_goes_to_estilo_visual(self):
        session = create_session("feature", "App with frontend")
        session = advance_phase(session, resultado="aprobado")
        self.assertEqual(session["fase_actual"], "estilo_visual")

    def test_advance_from_estilo_visual_goes_to_arquitectura(self):
        session = create_session("feature", "App with frontend")
        session = advance_phase(session, resultado="aprobado")
        self.assertEqual(session["fase_actual"], "estilo_visual")
        session = advance_phase(session, resultado="aprobado")
        self.assertEqual(session["fase_actual"], "arquitectura")


class TestDesignerFullFlow(unittest.TestCase):
    """Verify the full feature flow with Designer."""

    def test_full_feature_flow_with_designer(self):
        """Walk through the 7 phases of the feature flow."""
        session = create_session("feature", "App with dashboard")

        # Phase 0: producto
        self.assertEqual(session["fase_actual"], "producto")
        session = advance_phase(session, resultado="aprobado")

        # Phase 1: estilo_visual
        self.assertEqual(session["fase_actual"], "estilo_visual")
        session = advance_phase(session, resultado="aprobado")

        # Phase 2: arquitectura
        self.assertEqual(session["fase_actual"], "arquitectura")
        session = advance_phase(session, resultado="aprobado", security_ok=True)

        # Phase 3: desarrollo
        self.assertEqual(session["fase_actual"], "desarrollo")
        session = advance_phase(session, resultado="aprobado", tests_ok=True)

        # Phase 4: calidad
        self.assertEqual(session["fase_actual"], "calidad")
        session = advance_phase(
            session, resultado="aprobado", security_ok=True, tests_ok=True,
        )

        # Phase 5: documentacion
        self.assertEqual(session["fase_actual"], "documentacion")
        session = advance_phase(session, resultado="aprobado")

        # Phase 6: entrega
        self.assertEqual(session["fase_actual"], "entrega")
        session = advance_phase(session, resultado="aprobado", security_ok=True)

        # Completed
        self.assertEqual(session["fase_actual"], "completado")
        self.assertEqual(len(session["fases_completadas"]), 7)

    def test_estilo_visual_gate_rejects_without_approval(self):
        """The estilo_visual gate rejects without approval."""
        session = create_session("feature", "App with UI")
        session = advance_phase(session, resultado="aprobado")
        self.assertEqual(session["fase_actual"], "estilo_visual")

        result = check_gate(session, resultado="rechazado")
        self.assertFalse(result["passed"])


class TestDesignerSkippedWhenNoFrontend(unittest.TestCase):
    """Verify that estilo_visual is skipped in projects without a frontend."""

    def test_skip_estilo_visual_when_no_frontend(self):
        """With a stack without a frontend, estilo_visual is skipped."""
        session = create_session("feature", "API backend")
        session["stack"] = {"framework": "fastapi", "runtime": "python", "lenguaje": "python"}
        session = advance_phase(session, resultado="aprobado")  # producto -> must skip estilo_visual
        self.assertEqual(session["fase_actual"], "arquitectura")
        # Verify that estilo_visual is recorded as skipped
        skipped = [f for f in session["fases_completadas"] if f["nombre"] == "estilo_visual"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["resultado"], "saltada")

    def test_estilo_visual_executes_when_frontend(self):
        """With a stack with a frontend, estilo_visual runs normally."""
        session = create_session("feature", "App Next.js")
        session["stack"] = {"framework": "next", "runtime": "node", "lenguaje": "typescript"}
        session = advance_phase(session, resultado="aprobado")  # producto -> estilo_visual
        self.assertEqual(session["fase_actual"], "estilo_visual")

    def test_skip_when_no_stack_in_session(self):
        """Without a stack in the session, the condition is not evaluated and the phase runs."""
        session = create_session("feature", "New project")
        # No stack: the condition cannot be evaluated, so the phase runs
        session = advance_phase(session, resultado="aprobado")
        self.assertEqual(session["fase_actual"], "estilo_visual")


if __name__ == "__main__":
    unittest.main()
