#!/usr/bin/env python3
"""
Evidence verification library for Alfred Dev.

Holds the test evidence detection and storage functions, kept apart
from the hook entry point. Other modules (tests, stop-hook, orchestrator)
can import these functions without running the hook.

The ``evidence-guard.py`` hook imports from here and only adds the
``main()`` entry point that reads stdin.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# --- Constants ---

# File that stores the test evidence.
_EVIDENCE_FILENAME = "alfred-evidence.json"

# Maximum age (in seconds) for evidence to count as recent.
EVIDENCE_MAX_AGE_SECONDS = 600  # 10 minutes

# Test runner patterns.
_CMD_POS = r"(?:^|[;&|])\s*"

TEST_RUNNERS = [
    rf"{_CMD_POS}pytest\b",
    r"\bpython3?\s+-m\s+pytest\b",
    rf"{_CMD_POS}vitest\b",
    rf"{_CMD_POS}jest\b",
    rf"{_CMD_POS}mocha\b",
    r"\bcargo\s+test\b",
    r"\bgo\s+test\b",
    r"\bnpm\s+test\b",
    r"\bnpm\s+run\s+test\b",
    r"\bpnpm\s+test\b",
    r"\bpnpm\s+run\s+test\b",
    r"\bbun\s+test\b",
    r"\bbun\s+run\s+test\b",
    r"\byarn\s+test\b",
    r"\byarn\s+run\s+test\b",
    r"\bpython\s+-m\s+unittest\b",
    rf"{_CMD_POS}phpunit\b",
    rf"{_CMD_POS}rspec\b",
    r"\bmix\s+test\b",
    r"\bdotnet\s+test\b",
    r"\bmaven\s+test\b",
    r"\bmvn\s+test\b",
    r"\bgradle\s+test\b",
]

# Failure patterns in test output.
# They are matched against runner output, so the patterns are specific
# to avoid false positives with words such as "fail-safe" or "OK" in
# generic text.
FAILURE_PATTERNS = [
    r"(?<!\d )\bFAIL[ED]*\b(?![-_])",  # FAIL, FAILED but not fail-safe, fail_over or "0 failed"
    r"[1-9]\d*\s+failures?\b",       # "1 failure", "3 failures" (excludes "0 failures")
    r"\bfailing\b",
    r"[Tt]ests?\s+failed",
    r"ERRORS?\s*[:=]",              # "ERRORS:" or "ERROR=" but not a bare "ERROR"
    r"Assertion(?:Error|Failed)",    # AssertionError and AssertionFailed
    r"test\s+result:\s+FAILED",
    r"Build\s+FAILED",
    r"[1-9]\d*\s+failed",            # "1 failed", "3 failed" (excludes "0 failed")
    r"not\s+ok\s+\d+",              # TAP format: "not ok 1 - test name"
]

# Success patterns in test output.
SUCCESS_PATTERNS = [
    r"\d+\s+passed",
    r"[Tt]ests?\s+passed",
    r"test\s+result:\s+ok\b",
    r"All\s+tests\s+passed",
    r"\d+\s+passing\b",
    r"\bPASS(?:ED)?\b",             # PASS or PASSED
    r"\d+\s+tests?\s+complete",
    r"[Tt]ests?\s+run:\s+\d+",      # "Tests run: N": JUnit/Maven/TestNG format
    r"(?m)^ok\s+\S+",               # go test: "ok  github.com/foo/bar 0.003s" (multiline to anchor ^)
]


# --- Detection functions ---

def is_test_command(command: str) -> bool:
    """Check if a command runs tests.

    Args:
        command: the Bash command that ran (full string).

    Returns:
        True if the command matches a test runner.
    """
    return any(re.search(pattern, command) for pattern in TEST_RUNNERS)


def detect_test_result(output: str, exit_code: Optional[Any] = None) -> str:
    """Analyze the output of a test command to find the result.

    Failure patterns take priority over success patterns to cover
    partial runs (3 passed, 1 failed). If the output is not conclusive
    but the runner returned a non-zero exit code, the result is a
    failure.

    Args:
        output: full command output (stdout + stderr).
        exit_code: process exit code, if available.

    Returns:
        ``"pass"``, ``"fail"`` or ``"unknown"``.
    """
    has_fail = any(
        re.search(pattern, output, re.IGNORECASE)
        for pattern in FAILURE_PATTERNS
    )
    has_pass = any(
        re.search(pattern, output, re.IGNORECASE)
        for pattern in SUCCESS_PATTERNS
    )

    if has_fail:
        return "fail"
    if exit_code is not None:
        try:
            if int(exit_code) != 0:
                return "fail"
        except (TypeError, ValueError):
            pass
    if has_pass:
        return "pass"
    return "unknown"


# --- Evidence file management ---

def _evidence_path(project_dir: Optional[str] = None) -> str:
    """Compute the path of the evidence file."""
    base = project_dir or os.getcwd()
    return os.path.join(base, ".claude", _EVIDENCE_FILENAME)


def _load_evidence(project_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load the existing evidence records."""
    path = _evidence_path(project_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        print(
            f"[evidence-guard] Предупреждение: файл evidence не содержит "
            f"список. Содержимое отброшено.",
            file=sys.stderr,
        )
        return []
    except FileNotFoundError:
        return []
    except json.JSONDecodeError as e:
        print(
            f"[evidence-guard] Предупреждение: файл evidence повреждён "
            f"({path}): {e}. Предыдущие подтверждения будут потеряны.",
            file=sys.stderr,
        )
        return []
    except OSError as e:
        print(
            f"[evidence-guard] Предупреждение: не удалось прочитать evidence "
            f"({path}): {e}.",
            file=sys.stderr,
        )
        return []


def _save_evidence(
    records: List[Dict[str, Any]],
    project_dir: Optional[str] = None,
) -> None:
    """Save the evidence records. Keep the last 50 records."""
    path = _evidence_path(project_dir)
    dir_path = os.path.dirname(path)
    os.makedirs(dir_path, exist_ok=True)

    trimmed = records[-50:]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, ensure_ascii=False, indent=2)
    except OSError as e:
        print(
            f"[evidence-guard] Ошибка: не удалось сохранить evidence "
            f"в '{path}': {e}. Результаты тестов этого "
            f"запуска не будут записаны.",
            file=sys.stderr,
        )


def record_evidence(
    command: str,
    result: str,
    project_dir: Optional[str] = None,
) -> None:
    """Record a test run as evidence.

    Args:
        command: the test command that ran.
        result: detected result (``"pass"``, ``"fail"``, ``"unknown"``).
        project_dir: project directory.
    """
    records = _load_evidence(project_dir)
    records.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "command": command[:200],
        "result": result,
    })
    _save_evidence(records, project_dir)


def get_evidence(
    max_age_seconds: Optional[int] = EVIDENCE_MAX_AGE_SECONDS,
    project_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Return the current state of the test evidence.

    Args:
        max_age_seconds: time window in seconds. If ``None``, all records
            are returned with no age filter, which is useful for full
            session reports.
        project_dir: project directory.

    Returns:
        Dict with ``has_evidence``, ``all_passing``, ``last_result``,
        ``count`` and ``records``.
    """
    records = _load_evidence(project_dir)
    now = datetime.now(timezone.utc)

    recent = []
    skipped = 0
    for record in records:
        try:
            ts_str = record.get("timestamp", "")
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if max_age_seconds is not None:
                age = (now - ts).total_seconds()
                if age > max_age_seconds:
                    continue
            recent.append(record)
        except (ValueError, TypeError):
            skipped += 1
            continue

    if skipped > 0:
        print(
            f"[evidence-guard] Предупреждение: отброшено записей evidence "
            f"с неверным timestamp: {skipped}.",
            file=sys.stderr,
        )

    if not recent:
        return {
            "has_evidence": False,
            "all_passing": False,
            "last_result": None,
            "count": 0,
            "records": [],
        }

    last = recent[-1]
    all_passing = all(r.get("result") == "pass" for r in recent)

    return {
        "has_evidence": True,
        "all_passing": all_passing,
        "last_result": last.get("result"),
        "count": len(recent),
        "records": recent,
    }


def clear_evidence(project_dir: Optional[str] = None) -> None:
    """Remove the evidence file."""
    path = _evidence_path(project_dir)
    try:
        if os.path.exists(path):
            os.unlink(path)
    except OSError as e:
        print(
            f"[evidence-guard] Предупреждение: не удалось удалить evidence "
            f"({path}): {e}.",
            file=sys.stderr,
        )
