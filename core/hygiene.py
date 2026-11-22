#!/usr/bin/env python3
"""Early warnings before it hurts, and a shareable wrap-up for a quick/fix."""

from __future__ import annotations

import json
import os
import subprocess
from typing import Any, Dict, List, Optional

from core.continuity import (
    STATE_RELATIVE_PATH,
    load_state,
    load_uat,
    suggest_verify_action,
)
from core.project_docs import inspect_docs
from core.session_brief import build_session_brief


MANIFEST_NAMES = (
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "requirements.txt",
    "poetry.lock",
    "Pipfile.lock",
    "pyproject.toml",
    "Cargo.toml",
    "Cargo.lock",
    "go.mod",
    "go.sum",
    "composer.json",
    "composer.lock",
)

EVIDENCE_RELATIVE = os.path.join(".claude", "alfred-evidence.json")
CLOSING_RELATIVE = os.path.join(".claude", "alfred-last-closing.md")


def _git_changed_files(project_dir: str) -> List[str]:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    names: List[str] = []
    for line in result.stdout.splitlines():
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path:
            names.append(path.replace("\\", "/"))
    return names


def _latest_evidence(project_dir: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(project_dir, EVIDENCE_RELATIVE)
    if not os.path.isfile(path):
        return None
    try:
        payload = json.loads(open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return None
    if isinstance(payload, list) and payload:
        last = payload[-1]
        return last if isinstance(last, dict) else None
    if isinstance(payload, dict):
        records = payload.get("records") or payload.get("evidence")
        if isinstance(records, list) and records:
            last = records[-1]
            return last if isinstance(last, dict) else None
        if payload.get("command") or payload.get("result"):
            return payload
    return None


def _doc_status_map(project_dir: str) -> Dict[str, str]:
    mapping = {row["key"]: row["status"] for row in inspect_docs(project_dir)}
    return mapping


def run_hygiene(project_dir: str, command: str = "") -> Dict[str, Any]:
    """Check UAT, living docs and touched manifests without an evaluation."""
    root = os.path.abspath(project_dir)
    command = (command or "").strip().lower()
    blockers: List[str] = []
    warnings: List[str] = []

    uat = load_uat(root) or {}
    uat_status = str(uat.get("status") or "")
    verify = suggest_verify_action(root)
    if uat_status == "rejected":
        msg = "UAT отклонена: не выполняй deploy, пока не исправишь замечания из docs/project/uat.md."
        if command in {"ship", "audit"}:
            blockers.append(msg)
        else:
            warnings.append(msg)
    elif verify is not None or uat_status == "pending":
        msg = "UAT последнего результата в ожидании. Закрой `/alfred-dev:uat` перед ship."
        if command == "ship":
            blockers.append(msg)
        else:
            warnings.append(msg)

    statuses = _doc_status_map(root)
    arch = statuses.get("architecture", "missing")
    threat = statuses.get("threat_model", "missing")
    compliance = statuses.get("compliance", "missing")
    deps = statuses.get("dependencies", "missing")

    if arch == "filled" and threat in {"scaffold", "missing", "empty"}:
        msg = (
            "Архитектура заполнена, а threat-model всё ещё скелет. "
            "Обнови `docs/project/threat-model.md`."
        )
        if command in {"ship", "audit", "feature"}:
            blockers.append(msg)
        else:
            warnings.append(msg)

    if command in {"ship", "audit"} and compliance in {"scaffold", "missing", "empty"}:
        blockers.append(
            "Реестр compliance всё ещё скелет. "
            "Заполни `docs/project/compliance.md` с подтверждениями."
        )

    changed = _git_changed_files(root)
    touched_manifests = [
        name for name in changed
        if os.path.basename(name) in MANIFEST_NAMES
    ]
    if touched_manifests and deps in {"scaffold", "missing", "empty"}:
        warnings.append(
            "Манифесты зависимостей изменены ("
            + ", ".join(touched_manifests)
            + "), а в `docs/project/dependencies.md` нет оценки. "
            "Используй skill evaluate-dependency."
        )

    passed = not blockers
    return {
        "passed": passed,
        "command": command,
        "blockers": blockers,
        "warnings": warnings,
        "uat_status": uat_status,
        "docs": statuses,
    }


def render_hygiene_markdown(result: Dict[str, Any]) -> str:
    lines = ["## Гигиена репозитория", ""]
    if result["passed"] and not result["warnings"]:
        lines.append("Ничего срочного. Можно продолжать.")
        return "\n".join(lines)
    if result["blockers"]:
        lines.append("Блокирует:")
        lines.extend(f"- {item}" for item in result["blockers"])
        lines.append("")
    if result["warnings"]:
        lines.append("Предупреждение:")
        lines.extend(f"- {item}" for item in result["warnings"])
    if not result["passed"]:
        lines.append("")
        lines.append("Не объявляй ship и не закрывай gate поставки, пока не устранишь блокеры.")
    return "\n".join(lines)


def build_closing(project_dir: str) -> Dict[str, Any]:
    root = os.path.abspath(project_dir)
    state_path = os.path.join(root, STATE_RELATIVE_PATH)
    state = load_state(state_path) if os.path.isfile(state_path) else {}
    if not isinstance(state, dict):
        state = {}
    evidence = _latest_evidence(root)
    hygiene = run_hygiene(root, str(state.get("command") or ""))
    brief = build_session_brief(root)

    what = str(state.get("description") or "изменение этой сессии")
    command = str(state.get("command") or "quick")
    phase = str(state.get("current_phase") or "")

    verified = "нет подтверждения тестами за последние минуты"
    if evidence:
        command_run = str(evidence.get("command") or "tests")
        result = str(evidence.get("result") or evidence.get("status") or "")
        verified = f"`{command_run}` → {result or 'зарегистрировано'}"

    pending: List[str] = []
    if hygiene["blockers"] or hygiene["warnings"]:
        pending.extend(hygiene["blockers"])
        pending.extend(hygiene["warnings"])
    if brief.get("verify_pending") or brief.get("uat_status") == "pending":
        pending.append("UAT: `/alfred-dev:uat`")
    if not pending:
        pending.append("ничего блокирующего")

    return {
        "command": command,
        "phase": phase,
        "what": what,
        "verified": verified,
        "pending": pending,
        "hygiene_passed": hygiene["passed"],
    }


def write_session_closing(project_dir: str) -> Optional[str]:
    """Save the wrap-up on session exit if there was work."""
    root = os.path.abspath(project_dir)
    state_path = os.path.join(root, STATE_RELATIVE_PATH)
    state = load_state(state_path) if os.path.isfile(state_path) else None
    has_state = isinstance(state, dict) and bool(
        state.get("command") or state.get("description")
    )
    has_evidence = os.path.isfile(os.path.join(root, EVIDENCE_RELATIVE))
    if not has_state and not has_evidence:
        return None
    payload = build_closing(root)
    dest = os.path.join(root, CLOSING_RELATIVE)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as handle:
        handle.write(render_closing_markdown(payload) + "\n")
    return dest


def render_closing_markdown(result: Dict[str, Any]) -> str:
    pending = result.get("pending") or ["ничего блокирующего"]
    lines = [
        "## Итог Alfred",
        "",
        f"- Что: {result.get('what')}",
        f"- Процесс: `{result.get('command')}`"
        + (f" / `{result.get('phase')}`" if result.get("phase") else ""),
        f"- Как проверено: {result.get('verified')}",
        "- Осталось:",
    ]
    lines.extend(f"  - {item}" for item in pending)
    lines.append("")
    lines.append("Этот блок можно вставить в PR или в чат команды.")
    return "\n".join(lines)
