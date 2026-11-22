#!/usr/bin/env python3
"""
PostToolUse hook for Bash: evidence verification.

Implements the "evidence before claims" pattern, inspired by the Ralph
Loop plugin. Records the test runs detected during the session in a
temporary file, so other plugin components (stop-hook, check_gate) can
verify that tests really ran when an agent claims that they pass.

The detection and storage logic lives in ``evidence_guard_lib.py`` so
other modules can import it without running the hook.

Fail-open policy: never blocks the workflow.
"""

import json
import os
import sys

# Add the hooks directory to the path to import the library
_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from evidence_guard_lib import (
    is_test_command,
    detect_test_result,
    record_evidence,
)

_LOG_PREFIX = "[evidence-guard]"


def _get_tool_result(data: dict) -> dict:
    """Normalize current and legacy payloads of the hook runtime."""
    for key in ("tool_response", "tool_result", "tool_output"):
        value = data.get(key)
        if isinstance(value, dict):
            return value
        if isinstance(value, str) and value:
            return {"output": value}
    return {}


def main():
    """Entry point of the PostToolUse hook for Bash.

    Reads the JSON from stdin, checks if the command is a test runner,
    analyzes its result and records it as evidence.

    Fail-open policy: any unexpected error goes to stderr, but the hook
    always exits with 0 so it does not block the workflow.
    """
    try:
        data = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError) as e:
        print(
            f"{_LOG_PREFIX} Предупреждение: не удалось прочитать вход: {e}",
            file=sys.stderr,
        )
        sys.exit(0)

    try:
        tool_input = data.get("tool_input", {})
        tool_result = _get_tool_result(data)

        command = tool_input.get("command", "")
        if not command or not is_test_command(command):
            sys.exit(0)

        # Extract the command output
        stdout = tool_result.get("stdout", "") or tool_result.get("output", "")
        stderr = tool_result.get("stderr", "")
        exit_code = tool_result.get("exit_code")
        output = f"{stdout}\n{stderr}"

        # Detect the result and record evidence
        result = detect_test_result(output, exit_code=exit_code)
        record_evidence(command, result)

        if result == "unknown":
            print(
                f"{_LOG_PREFIX} Тесты запущены, но результат определить "
                f"не удалось. Команда всё равно записана.",
                file=sys.stderr,
            )
    except Exception as e:
        print(
            f"{_LOG_PREFIX} Непредвиденная ошибка (fail-open, не блокирует): {e}",
            file=sys.stderr,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
