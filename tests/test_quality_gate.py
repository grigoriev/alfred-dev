#!/usr/bin/env python3
"""
Tests for the quality-gate.py hook.

``test_evidence_guard.py`` covers the command and result detection logic.
This file only verifies that the hook imports correctly from
``evidence_guard_lib`` (single source of truth) and that its main flow
works as expected.
"""

import importlib.util
import json
import os
import sys
import unittest
from io import StringIO
from unittest.mock import patch

# Base paths to import modules with a hyphen in the name
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_HOOKS_DIR = os.path.join(_TESTS_DIR, "..", "hooks")
_HOOK_PATH = os.path.join(_HOOKS_DIR, "quality-gate.py")


def _load_quality_gate():
    """Load the quality-gate.py module with importlib."""
    spec = importlib.util.spec_from_file_location("quality_gate", _HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestQualityGateImports(unittest.TestCase):
    """Verify that quality-gate reuses the evidence_guard_lib functions."""

    def test_quality_gate_uses_evidence_guard_lib(self):
        """quality-gate must use the evidence_guard_lib functions."""
        qg = _load_quality_gate()
        # Must use the same function as evidence_guard_lib
        sys.path.insert(0, _HOOKS_DIR)
        from evidence_guard_lib import is_test_command as lib_fn
        self.assertIs(qg.is_test_command, lib_fn)


class TestQualityGateMain(unittest.TestCase):
    """Verify the main() flow for different inputs."""

    def _run_main(self, payload: dict) -> tuple[int, str]:
        """Run main() with the given payload and return (exit_code, stderr)."""
        qg = _load_quality_gate()
        stdin_data = json.dumps(payload)
        stderr_capture = StringIO()

        exit_code = None
        with patch("sys.stdin", StringIO(stdin_data)):
            with patch("sys.stderr", stderr_capture):
                try:
                    qg.main()
                except SystemExit as exc:
                    exit_code = exc.code

        return exit_code, stderr_capture.getvalue()

    def test_non_test_command_exits_0_silently(self):
        """Commands that are not test runners write nothing to stderr."""
        payload = {
            "tool_input": {"command": "ls -la"},
            "tool_output": {"stdout": "", "stderr": ""},
        }
        code, stderr = self._run_main(payload)
        self.assertEqual(code, 0)
        self.assertEqual(stderr, "")

    def test_passing_tests_exits_0_silently(self):
        """Passing tests emit no warning."""
        payload = {
            "tool_input": {"command": "pytest tests/"},
            "tool_output": {"stdout": "5 passed in 0.12s", "stderr": ""},
        }
        code, stderr = self._run_main(payload)
        self.assertEqual(code, 0)
        self.assertNotIn("Ломатель", stderr)

    def test_failing_tests_emits_warning(self):
        """Failing tests emit the Breaker warning to stderr."""
        payload = {
            "tool_input": {"command": "pytest tests/"},
            "tool_output": {"stdout": "1 failed, 4 passed in 0.15s", "stderr": ""},
        }
        code, stderr = self._run_main(payload)
        self.assertEqual(code, 0)
        self.assertIn("Ломатель", stderr)

    def test_nonzero_exit_code_without_output_emits_warning(self):
        """A nonzero exit code must also trigger the warning."""
        payload = {
            "tool_input": {"command": "pytest tests/"},
            "tool_output": {"stdout": "", "stderr": "", "exit_code": 1},
        }
        code, stderr = self._run_main(payload)
        self.assertEqual(code, 0)
        self.assertIn("Ломатель", stderr)

    def test_tool_result_payload_is_supported(self):
        """The hook must accept the current payload with tool_result."""
        payload = {
            "tool_input": {"command": "pytest tests/"},
            "tool_result": {"stdout": "", "stderr": "", "exit_code": 1},
        }
        code, stderr = self._run_main(payload)
        self.assertEqual(code, 0)
        self.assertIn("Ломатель", stderr)

    def test_invalid_json_exits_0_with_warning(self):
        """Invalid JSON input emits a warning but does not block (exit 0)."""
        qg = _load_quality_gate()
        stderr_capture = StringIO()
        exit_code = None
        with patch("sys.stdin", StringIO("this is not json")):
            with patch("sys.stderr", stderr_capture):
                try:
                    qg.main()
                except SystemExit as exc:
                    exit_code = exc.code
        self.assertEqual(exit_code, 0)
        self.assertIn("quality-gate", stderr_capture.getvalue())


if __name__ == "__main__":
    unittest.main()
