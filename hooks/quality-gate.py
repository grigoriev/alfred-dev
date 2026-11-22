#!/usr/bin/env python3
"""
PostToolUse hook for Bash: test quality gate.

Intercepts Bash command output to detect test runs and, if tests ran,
checks if they failed. On failure, it reports to stderr in the voice of
the QA persona (El Rompe-cosas).

Delegates command and result detection to ``evidence_guard_lib`` to keep
one source of truth for the patterns.

Acts only on commands that match known test runners. Other Bash commands
pass without inspection.
"""

import json
import os
import sys

# Add the hooks directory to the path to import the library
_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
if _HOOKS_DIR not in sys.path:
    sys.path.insert(0, _HOOKS_DIR)

from evidence_guard_lib import is_test_command, detect_test_result


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
    """Hook entry point.

    Reads the JSON from stdin, extracts the command and its output, and
    checks for failed tests. If tests failed, writes a warning to stderr
    in the voice of El Rompe-cosas.
    """
    try:
        data = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError) as e:
        print(
            f"[quality-gate] Предупреждение: не удалось прочитать вход hook: {e}. "
            f"Мониторинг тестов для этой команды отключён.",
            file=sys.stderr,
        )
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    tool_result = _get_tool_result(data)

    command = tool_input.get("command", "")

    if not command or not is_test_command(command):
        sys.exit(0)

    stdout = tool_result.get("stdout", "") or tool_result.get("output", "")
    stderr_out = tool_result.get("stderr", "")
    exit_code = tool_result.get("exit_code")
    output = f"{stdout}\n{stderr_out}"

    if detect_test_result(output, exit_code=exit_code) == "fail":
        print(
            "\n"
            "[Ломатель] Поймал сломанные тесты\n"
            "\n"
            "Тесты не проходят. Сюрприз: никакого.\n"
            "С красными тестами дальше не идём. Так здесь заведено.\n"
            "\n"
            "Просмотри вывод, исправь ошибки и запусти снова.\n"
            "Тот edge case, который ты не учёл? Я его нашёл.\n",
            file=sys.stderr,
        )

    sys.exit(0)


if __name__ == "__main__":
    main()
