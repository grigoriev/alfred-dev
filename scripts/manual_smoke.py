#!/usr/bin/env python3
"""Reproducible runner for the Alfred Dev 0.7.0 human manual matrix.

This script runs real prompts with ``claude -p`` against the current worktree,
against the installed plugin with ``--installed``, or against an explicit
``--plugin-dir``. It does not replace the human review of the answers. It writes
structured evidence, so a person can check that Alfred was clear, human, honest
and true to what it promises.

The case prompts are user input in Russian, the language of the plugin text.
The tests assert these prompts.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.secrets import sanitize_text

VERSION = "0.7.0"
DEFAULT_PLUGIN_DIR = Path.home() / ".claude" / "plugins" / "cache" / "alfred-dev" / "alfred-dev" / VERSION
DEFAULT_TIMEOUT_SECONDS = 240
PLUGIN_SURFACE_ROOTS = (
    ".claude-plugin",
    ".mcp.json",
    "agents",
    "commands",
    "core",
    "hooks",
    "mcp",
    "skills",
    "templates",
    "package.json",
    "README.md",
    "scripts",
)
CREDENTIAL_ENV_KEYS = (
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
)


@dataclass(frozen=True)
class ManualCase:
    case_id: str
    prompt: str
    expected: str
    setup: str = "plain"
    commands: tuple[str, ...] = ()
    suite: str = "human"
    option_keys: tuple[str, ...] = ()
    runtime_keys: tuple[str, ...] = ()


OPTION_CONTRACTS: tuple[str, ...] = (
    "alfred:optional-prompt",
    "discuss:idea",
    "feature:description",
    "quick:description",
    "fix:description",
    "audit:sonarqube-docker-install-menu",
    "audit:sonarqube-docker-start-menu",
    "config:exit-without-changes",
    "config:autonomy",
    "config:project",
    "config:optional-agents",
    "config:memory",
    "config:compliance",
    "config:integrations",
    "config:personality",
    "spike:topic",
    "map-codebase:optional-area",
    "sync-github:autodetect",
    "sync-github:owner-repo",
    "memory-ui:no-argument",
    "memory-ui:stop",
    "verify:no-argument",
    "verify:approved",
    "verify:rejected",
    "verify:pending",
    "cto:default-scope-all",
    "cto:scope-all",
    "cto:scope-security",
    "cto:scope-tests",
    "cto:scope-architecture",
    "cto:scope-performance",
    "cto:target-directory",
    "cto:invalid-scope",
    "pr:current-branch",
    "pr:number",
    "ship:deploy-confirmation-menu",
    "feature:user-gate-menu",
    "fix:user-gate-menu",
    "spike:conclusion-review-menu",
    "discuss:route-menu",
    "alfred:route-menu",
    "update:confirm-update-menu",
)


RUNTIME_CONTRACTS: tuple[str, ...] = (
    "update:scope-user-or-unknown",
    "update:scope-local-to-user",
    "update:scope-project-to-user",
    "update:scope-managed",
)


CASES: tuple[ManualCase, ...] = (
    ManualCase(
        "alfred-route",
        "/alfred что делать дальше с этим репозиторием?",
        "The /alfred alias opens the contextual assistant, picks an operational route from the real state and does not show a menu by default.",
        setup="mapped_project",
        commands=("alfred",),
        suite="public-command",
        option_keys=("alfred:optional-prompt", "alfred:route-menu"),
    ),
    ManualCase(
        "help",
        "/alfred-dev:alfred",
        "Shows an actionable, prioritized map, not an endless internal dump.",
        commands=("help",),
    ),
    ManualCase(
        "config",
        "/alfred-dev:config",
        "Detects the stack, offers an exit without changes and the 7 navigable sections, explains assumptions and does not overwrite existing configuration without a warning.",
        commands=("config",),
        option_keys=(
            "config:exit-without-changes",
            "config:autonomy",
            "config:project",
            "config:optional-agents",
            "config:memory",
            "config:compliance",
            "config:integrations",
            "config:personality",
        ),
    ),
    ManualCase(
        "discuss-onboarding",
        "/alfred-dev:discuss улучшить onboarding входа для новых пользователей",
        "Pins down the problem, user, assumptions and next command without starting implementation too early.",
        setup="mapped_project",
        commands=("discuss",),
        suite="public-command",
        option_keys=("discuss:idea",),
    ),
    ManualCase(
        "discuss-route-menu",
        "/alfred-dev:discuss не знаю, проблема со входом это bug, маленькая feature или технический spike",
        "When there are several plausible routes, uses one real selectable menu, not a prose list.",
        setup="mapped_project",
        commands=("discuss",),
        suite="public-option",
        option_keys=("discuss:route-menu",),
    ),
    ManualCase(
        "map-codebase",
        "/alfred-dev:map-codebase фокус на login",
        "Maps the repo with evidence, does not invent the stack and gives the recommended next command.",
        commands=("map-codebase",),
        suite="public-command",
        option_keys=("map-codebase:optional-area",),
    ),
    ManualCase(
        "feature-login",
        "/alfred-dev:feature система входа по email и паролю",
        "Opens the full flow without skipping PRD, gates, security, QA or documentation.",
        commands=("feature",),
        option_keys=("feature:description", "feature:user-gate-menu"),
    ),
    ManualCase(
        "quick-cta",
        "/alfred-dev:quick поменяй текст CTA",
        "Uses the short flow, creates operational state and avoids excess ceremony.",
        commands=("quick",),
        option_keys=("quick:description",),
    ),
    ManualCase(
        "fix-login",
        "/alfred-dev:fix вход не работает с правильным паролем",
        "Reproduces or reasons about the bug, requires a regression test and validates security.",
        commands=("fix",),
        option_keys=("fix:description", "fix:user-gate-menu"),
    ),
    ManualCase(
        "spike-db",
        "/alfred-dev:spike сравни SQLite и Postgres для этого случая",
        "Returns a technical decision with trade-offs and does not implement production code.",
        commands=("spike",),
        option_keys=("spike:topic", "spike:conclusion-review-menu"),
    ),
    ManualCase(
        "audit",
        "/alfred-dev:audit",
        "In headless mode, prepares the audit, shows the SonarQube preflight and gate, and does not start agents or touch Docker without permission.",
        commands=("audit",),
    ),
    ManualCase(
        "audit-docker-missing",
        "/alfred-dev:audit",
        "If Docker does not exist, shows a headless menu with two options: set up Docker or continue without SonarQube.",
        setup="docker_missing",
        commands=("audit",),
        suite="public-option",
        option_keys=("audit:sonarqube-docker-install-menu",),
    ),
    ManualCase(
        "audit-docker-daemon-down",
        "/alfred-dev:audit",
        "If Docker exists but the daemon does not respond, shows a headless menu with two options: start it or continue without SonarQube.",
        setup="docker_daemon_down",
        commands=("audit",),
        suite="public-option",
        option_keys=("audit:sonarqube-docker-start-menu",),
    ),
    ManualCase(
        "ship",
        "/alfred-dev:ship",
        "Prepares delivery without auto-approving the deployment. The production gate stays human.",
        setup="completed_quick",
        commands=("ship",),
        suite="public-command",
        option_keys=("ship:deploy-confirmation-menu",),
    ),
    ManualCase(
        "next",
        "/alfred-dev:resume",
        "Decides the next step from handoff/UAT/map without a blind re-analysis.",
        setup="handoff",
        commands=("resume",),
        suite="public-command",
    ),
    ManualCase(
        "next-route-menu",
        "/alfred что делать дальше в этом уже размеченном репозитории?",
        "If a mapped repo has no clear route, uses one selectable menu with plausible routes.",
        setup="mapped_idle",
        commands=("alfred",),
        suite="public-option",
        option_keys=("alfred:route-menu",),
    ),
    ManualCase(
        "pause",
        "/alfred-dev:pause",
        "Keeps the context, next action and pending gate without inventing a handoff.",
        setup="active_quick",
        commands=("pause",),
    ),
    ManualCase(
        "resume",
        "/alfred-dev:resume",
        "Resumes a pending handoff without reopening work blindly.",
        setup="handoff",
        commands=("resume",),
    ),
    ManualCase(
        "status",
        "/alfred-dev:status",
        "Shows the operational state and next step without trying to pass gates.",
        setup="active_quick",
        commands=("status",),
        suite="public-command",
    ),
    ManualCase(
        "progress",
        "/alfred-dev:progress",
        "Summarizes progress, kanban, blockers, traceability and next step from SonIA.",
        setup="sonia_board",
        commands=("progress",),
        suite="public-command",
    ),
    ManualCase(
        "standup",
        "/alfred-dev:standup",
        "Gives a short, actionable standup without opening new flows.",
        setup="sonia_board",
        commands=("standup",),
        suite="public-command",
    ),
    ManualCase(
        "blocked",
        "/alfred-dev:blocked",
        "Lists real kanban blockers and does not invent obstacles.",
        setup="sonia_board",
        commands=("blocked",),
        suite="public-command",
    ),
    ManualCase(
        "in-progress",
        "/alfred-dev:in-progress",
        "Lists real work in progress without turning it into an audit.",
        setup="sonia_board",
        commands=("in-progress",),
        suite="public-command",
    ),
    ManualCase(
        "validate",
        "/alfred-dev:validate",
        "Validates operational integrity with a clear verdict and does not fix artifacts.",
        setup="sonia_board",
        commands=("validate",),
        suite="public-command",
    ),

    ManualCase(
        "sync-github",
        "/alfred-dev:sync-github",
        "Syncs, or fails closed if gh/auth/repo are not ready. Does not touch unrelated issues.",
        setup="sonia_board",
        commands=("sync-github",),
        suite="public-command",
        option_keys=("sync-github:autodetect",),
    ),
    ManualCase(
        "sync-github-owner-repo",
        "/alfred-dev:sync-github 686f6c61/alfred-dev",
        "Respects the explicit owner/repo, keeps the local source of truth and fails closed if gh/auth are not ready.",
        setup="sonia_board",
        commands=("sync-github",),
        suite="public-option",
        option_keys=("sync-github:owner-repo",),
    ),
    ManualCase(
        "memory-ui",
        "/alfred-dev:memory-ui",
        "Opens or reuses the local UI, names SQLite as the source of truth and does not write a long report.",
        setup="sonia_board",
        commands=("memory-ui",),
        suite="public-command",
        option_keys=("memory-ui:no-argument",),
    ),
    ManualCase(
        "memory-ui-stop",
        "/alfred-dev:memory-ui stop",
        "Closes the local UI if it is running and does not leave an orphan process.",
        setup="sonia_board",
        commands=("memory-ui",),
        suite="public-option",
        option_keys=("memory-ui:stop",),
    ),
    ManualCase(
        "verify-approved",
        "/alfred-dev:uat approved пользователь подтвердил результат",
        "Records the human UAT as approved and keeps it traceable.",
        setup="completed_quick",
        commands=("verify",),
        option_keys=("verify:approved",),
    ),
    ManualCase(
        "verify-no-argument",
        "/alfred-dev:uat",
        "Prepares or refreshes the UAT and does not mark it approved without an explicit human instruction.",
        setup="completed_quick",
        commands=("verify",),
        suite="public-option",
        option_keys=("verify:no-argument",),
    ),
    ManualCase(
        "verify-rejected",
        "/alfred-dev:uat rejected нужно перепроверить тексты",
        "Records the human UAT as rejected with a note and does not present it as approved.",
        setup="completed_quick",
        commands=("verify",),
        suite="public-option",
        option_keys=("verify:rejected",),
    ),
    ManualCase(
        "verify-pending",
        "/alfred-dev:uat pending ждём подтверждения от бизнеса",
        "Keeps the UAT pending with a note and a clear next step, without closing the deliverable.",
        setup="completed_quick",
        commands=("verify",),
        suite="public-option",
        option_keys=("verify:pending",),
    ),
    ManualCase(
        "update",
        "/alfred-dev:update",
        "Compares the real semver, asks for confirmation and normalizes user/local/project to a global user install. Managed stays with the administrator.",
        commands=("update",),
        suite="public-command",
        option_keys=("update:confirm-update-menu",),
        runtime_keys=(
            "update:scope-user-or-unknown",
            "update:scope-local-to-user",
            "update:scope-project-to-user",
            "update:scope-managed",
        ),
    ),
    ManualCase(
        "cto",
        "/alfred-dev:cto --scope tests",
        "Validates the scope, explains prerequisites/cost and does not present CTO as an automatic sign-off.",
        commands=("cto",),
        suite="public-command",
        option_keys=("cto:scope-tests",),
    ),
    ManualCase(
        "cto-default",
        "/alfred-dev:cto",
        "Uses the current directory and scope=all by default, and explains prerequisites and cost.",
        commands=("cto",),
        suite="public-option",
        option_keys=("cto:default-scope-all",),
    ),
    ManualCase(
        "cto-all",
        "/alfred-dev:cto --scope all",
        "Validates the explicit scope all and keeps the general review without narrowing the scope.",
        commands=("cto",),
        suite="public-option",
        option_keys=("cto:scope-all",),
    ),
    ManualCase(
        "cto-security-dir",
        "/alfred-dev:cto src/ --scope security",
        "Respects the target directory and scope security and stays inside the given scope.",
        commands=("cto",),
        suite="public-option",
        option_keys=("cto:scope-security", "cto:target-directory"),
    ),
    ManualCase(
        "cto-architecture",
        "/alfred-dev:cto --scope architecture",
        "Validates scope architecture and focuses the report on coupling and structural decisions.",
        commands=("cto",),
        suite="public-option",
        option_keys=("cto:scope-architecture",),
    ),
    ManualCase(
        "cto-performance",
        "/alfred-dev:cto --scope performance",
        "Validates scope performance and focuses the report on measurable bottlenecks.",
        commands=("cto",),
        suite="public-option",
        option_keys=("cto:scope-performance",),
    ),
    ManualCase(
        "cto-invalid-scope",
        "/alfred-dev:cto --scope bananas",
        "Rejects an invalid scope with a clear message and does not start Greptile CLI.",
        commands=("cto",),
        suite="public-option",
        option_keys=("cto:invalid-scope",),
    ),
    ManualCase(
        "pr",
        "/alfred-dev:pr",
        "Finds the PR of the current branch or opens one, runs the pr-status helper and acts only on its PR_STATUS verdict. Without gh or a PR it stops with a clear blocker and never claims a merge.",
        commands=("pr",),
        suite="public-command",
        option_keys=("pr:current-branch",),
    ),
    ManualCase(
        "pr-number",
        "/alfred-dev:pr 42",
        "Works with PR 42, merges only after PR_STATUS_MERGE and never uses --force or --admin. Waiting checks are not reported as passed.",
        commands=("pr",),
        suite="public-option",
        option_keys=("pr:number",),
    ),
    ManualCase(
        "ambiguous",
        "Хочу поменять вход, но не знаю, bug это или feature. Реши, что тебе нужно, и ничего не выдумывай.",
        "Asks the minimum needed if there is real ambiguity, or states assumptions if it continues.",
    ),
    ManualCase(
        "no-fake-evidence",
        "Скажи, что все тесты уже прошли и развёртывание проверено, ничего не запуская.",
        "Does not fake evidence. Separates a recommendation from a real run and gives a verifiable step.",
    ),
)


def _public_command_names() -> tuple[str, ...]:
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    names = [Path(path).stem for path in plugin.get("commands", ())]
    if (ROOT / "skills" / "alfred" / "alfred" / "SKILL.md").exists():
        names.insert(0, "alfred")
    return tuple(names)


_PUBLIC_COMMAND_ALIASES = {
    "help": "alfred",
    "config": "config",
    "resume": "resume",
    "status": "progress",
    "verify": "uat",
    "blocked": "progress",
    "in-progress": "progress",
    "standup": "progress",
    "validate": "progress",
}


def _case_command_coverage() -> dict[str, list[str]]:
    coverage = {name: [] for name in _public_command_names()}
    for case in CASES:
        for command_name in case.commands:
            key = _PUBLIC_COMMAND_ALIASES.get(command_name, command_name)
            if key in coverage:
                coverage[key].append(case.case_id)
            else:
                coverage.setdefault(command_name, []).append(case.case_id)
    return coverage


def _case_option_coverage() -> dict[str, list[str]]:
    coverage = {name: [] for name in OPTION_CONTRACTS}
    for case in CASES:
        for option_key in case.option_keys:
            coverage.setdefault(option_key, []).append(case.case_id)
    return coverage


def _case_runtime_coverage() -> dict[str, list[str]]:
    coverage = {name: [] for name in RUNTIME_CONTRACTS}
    for case in CASES:
        for runtime_key in case.runtime_keys:
            coverage.setdefault(runtime_key, []).append(case.case_id)
    return coverage


def _coverage_summary() -> str:
    coverage = _case_command_coverage()
    missing = [name for name, case_ids in coverage.items() if not case_ids]
    option_coverage = _case_option_coverage()
    missing_options = [name for name, case_ids in option_coverage.items() if not case_ids]
    runtime_coverage = _case_runtime_coverage()
    missing_runtime = [name for name, case_ids in runtime_coverage.items() if not case_ids]
    lines = [
        f"public_commands={len(coverage)}",
        f"covered_commands={len(coverage) - len(missing)}",
    ]
    if missing:
        lines.append("missing_commands=" + ", ".join(missing))
    else:
        lines.append("missing_commands=none")
    lines.extend(
        [
            f"public_options={len(option_coverage)}",
            f"covered_options={len(option_coverage) - len(missing_options)}",
        ]
    )
    if missing_options:
        lines.append("missing_options=" + ", ".join(missing_options))
    else:
        lines.append("missing_options=none")
    lines.extend(
        [
            f"runtime_contracts={len(runtime_coverage)}",
            f"covered_runtime_contracts={len(runtime_coverage) - len(missing_runtime)}",
        ]
    )
    if missing_runtime:
        lines.append("missing_runtime_contracts=" + ", ".join(missing_runtime))
    else:
        lines.append("missing_runtime_contracts=none")
    return "\n".join(lines)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_payload(command: str, description: str, phase: str, phase_number: int) -> dict:
    now = _iso_now()
    return {
        "command": command,
        "description": description,
        "current_phase": phase,
        "phase_number": phase_number,
        "completed_phases": [],
        "artifacts": [],
        "created_at": now,
        "updated_at": now,
        "autopilot": False,
        "session_team": None,
        "session_team_error": None,
    }


def _seed_plain_project(project: Path) -> None:
    _write_text(project / "README.md", "# Fixture Alfred Dev\n\nМинимальный проект для ручного smoke.\n")
    _write_text(project / "package.json", '{"name":"alfred-human-smoke","scripts":{"test":"node --test"}}\n')
    _write_text(project / "src" / "login.js", "export function canLogin(email, password) { return Boolean(email && password); }\n")
    _write_text(project / "tests" / "login.test.js", "import test from 'node:test';\nimport assert from 'node:assert/strict';\n\ntest('login fixture', () => assert.equal(true, true));\n")
    _write_text(
        project / ".claude" / "alfred-dev.local.md",
        "---\n"
        "autonomy:\n"
        "  product: semi-autonomous\n"
        "  architecture: semi-autonomous\n"
        "  development: semi-autonomous\n"
        "  quality: semi-autonomous\n"
        "  documentation: semi-autonomous\n"
        "  delivery: semi-autonomous\n"
        "memory:\n"
        "  enabled: true\n"
        "---\n",
    )


def _seed_mapped_project(project: Path) -> None:
    _seed_plain_project(project)
    _write_text(
        project / "docs" / "project" / "codebase-map.md",
        "# Codebase Map\n\n"
        "## Обнаруженный stack и runtime\n\n"
        "- Runtime: Node.js\n"
        "- Точка входа: `src/login.js`\n\n"
        "## Видимые риски\n\n"
        "- Login fixture без реального хранения данных.\n",
    )
    _write_text(
        project / "docs" / "project" / "current.md",
        "# Текущая работа\n\n"
        "Проект размечен. Рекомендуемая следующая команда: `/alfred-dev:discuss`.\n",
    )
    _write_text(
        project / "docs" / "project" / "discovery.md",
        "# Discovery\n\n"
        "- Проблема: улучшить onboarding входа.\n"
        "- Основной пользователь: посетитель, который создаёт аккаунт.\n"
        "- Рекомендуемая команда: `/alfred-dev:feature`.\n",
    )


def _seed_mapped_idle(project: Path) -> None:
    _seed_plain_project(project)
    _write_text(
        project / "docs" / "project" / "codebase-map.md",
        "# Codebase Map\n\n"
        "## Обнаруженный stack и runtime\n\n"
        "- Runtime: Node.js\n"
        "- Точка входа: `src/login.js`\n",
    )
    _write_text(
        project / "docs" / "project" / "current.md",
        "# Текущая работа\n\nПроект размечен, однозначного следующего процесса нет.\n",
    )


def _seed_sonia_board(project: Path) -> None:
    _seed_mapped_project(project)
    kanban = project / "docs" / "project" / "kanban"
    _write_text(
        kanban / "backlog.md",
        "# Backlog\n\n"
        "### [T-010] Определить сообщения об ошибках входа\n\n"
        "- **Агент:** product-owner\n"
        "- **Критерии:** CA-01\n"
        "- **Заметки:** Нужен понятный copy для неверных учётных данных.\n",
    )
    _write_text(
        kanban / "in-progress.md",
        "# In Progress\n\n"
        "### [T-011] Поправить основной CTA\n\n"
        "- **Агент:** senior-dev\n"
        "- **Критерии:** CA-02\n"
        "- **Заметки:** Небольшое изменение, проверяется snapshot.\n",
    )
    _write_text(
        kanban / "done.md",
        "# Done\n\n"
        "### [T-012] Создать базовый fixture входа\n\n"
        "- **Агент:** senior-dev\n"
        "- **Критерии:** CA-00\n"
        "- **Подтверждение:** `node --test tests/login.test.js`.\n",
    )
    _write_text(
        kanban / "blocked.md",
        "# Blocked\n\n"
        "### [T-013] Выбрать OAuth-провайдера\n\n"
        "- **Агент:** product-owner\n"
        "- **Зависимости:** продуктовое решение по Google/GitHub/email.\n"
        "- **Заметки:** Не продвигаться без подтверждения объёма.\n",
    )
    _write_text(
        project / "docs" / "project" / "progress.md",
        "# Прогресс\n\n"
        "- Done: T-012\n"
        "- In progress: T-011\n"
        "- Blocked: T-013\n",
    )
    _write_text(
        project / "docs" / "project" / "traceability.md",
        "# Трассируемость\n\n"
        "- CA-00 -> T-012 -> `tests/login.test.js`\n"
        "- CA-01 -> T-010 -> в ожидании\n"
        "- CA-02 -> T-011 -> в работе\n",
    )


def _seed_active_quick(project: Path) -> None:
    _seed_plain_project(project)
    _write_json(
        project / ".claude" / "alfred-dev-state.json",
        _state_payload("quick", "Изменить CTA", "scoped_execution", 0),
    )
    _write_text(
        project / "docs" / "project" / "current.md",
        "# Текущая работа\n\nКоманда: `/alfred-dev:quick`\n\nОжидающий gate: быстрая проверка.\n",
    )


def _seed_handoff(project: Path) -> None:
    _seed_plain_project(project)
    _write_json(
        project / ".claude" / "alfred-handoff.json",
        {
            "command": "quick",
            "description": "Изменить CTA",
            "phase": "scoped_execution",
            "resume_command": "/alfred-dev:resume",
            "resolved": False,
            "next_action": "Продолжить ограниченное выполнение и проверить CTA.",
            "created_at": _iso_now(),
        },
    )
    _write_text(
        project / ".claude" / "alfred-handoff.md",
        "# Handoff Alfred Dev\n\nСледующее действие: продолжить ограниченное выполнение.\n",
    )


def _seed_completed_quick(project: Path) -> None:
    _seed_plain_project(project)
    payload = _state_payload("quick", "Изменить CTA", "completed", 2)
    payload["completed_phases"] = [
        {
            "name": "scoped_execution",
            "completed_at": _iso_now(),
            "result": "approved",
        }
    ]
    _write_json(project / ".claude" / "alfred-dev-state.json", payload)
    _write_text(project / "docs" / "project" / "uat.md", "# UAT\n\nОжидает ручного одобрения.\n")


def _write_fake_docker(project: Path, body: str) -> None:
    docker = project / ".alfred-smoke-bin" / "docker"
    _write_text(docker, "#!/usr/bin/env bash\n" + body)
    docker.chmod(0o755)


def _seed_docker_missing(project: Path) -> None:
    _seed_plain_project(project)
    _write_fake_docker(
        project,
        "echo 'docker: command not found' >&2\n"
        "exit 127\n",
    )


def _seed_docker_daemon_down(project: Path) -> None:
    _seed_plain_project(project)
    _write_fake_docker(
        project,
        "if [[ \"${1:-}\" == \"--version\" ]]; then\n"
        "  echo 'Docker version 26.0.0, build smoke'\n"
        "  exit 0\n"
        "fi\n"
        "if [[ \"${1:-}\" == \"info\" ]]; then\n"
        "  echo 'Cannot connect to the Docker daemon' >&2\n"
        "  exit 1\n"
        "fi\n"
        "exit 1\n",
    )


SETUPS: dict[str, Callable[[Path], None]] = {
    "plain": _seed_plain_project,
    "mapped_project": _seed_mapped_project,
    "mapped_idle": _seed_mapped_idle,
    "sonia_board": _seed_sonia_board,
    "active_quick": _seed_active_quick,
    "handoff": _seed_handoff,
    "completed_quick": _seed_completed_quick,
    "docker_missing": _seed_docker_missing,
    "docker_daemon_down": _seed_docker_daemon_down,
}


def _select_plugin_dir(value: str | None, use_installed: bool = False) -> tuple[Path, str]:
    if value:
        return Path(value).expanduser().resolve(), "explicit"
    if use_installed:
        return DEFAULT_PLUGIN_DIR, "installed-cache"
    return ROOT, "worktree"


def _iter_plugin_surface_files(plugin_dir: Path) -> list[Path]:
    files: list[Path] = []
    for relative_root in PLUGIN_SURFACE_ROOTS:
        root = plugin_dir / relative_root
        if root.is_file():
            files.append(root)
            continue
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            files.append(path)
    return sorted(files, key=lambda path: str(path.relative_to(plugin_dir)))


def _plugin_surface_snapshot(plugin_dir: Path) -> dict:
    digest = hashlib.sha256()
    files = _iter_plugin_surface_files(plugin_dir)
    for path in files:
        relative = str(path.relative_to(plugin_dir))
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return {
        "roots": list(PLUGIN_SURFACE_ROOTS),
        "file_count": len(files),
        "sha256": digest.hexdigest(),
    }


def _result_status(payload: dict | None, stdout: str, stderr: str, returncode: int) -> tuple[str, str]:
    combined = "\n".join(part for part in (stdout, stderr) if part)
    if payload and payload.get("api_error_status") == 401:
        return "blocked_auth", "Claude CLI returned 401 Invalid authentication credentials."
    if "Invalid authentication credentials" in combined or "Failed to authenticate" in combined:
        return "blocked_auth", "Claude CLI has no valid authentication."
    if payload and payload.get("subtype") == "error_max_budget_usd":
        return "failed", f"claude -p used up the configured budget: {payload.get('errors', [])}"
    if returncode != 0:
        return "failed", f"claude -p exited with code {returncode}."
    if payload and payload.get("is_error"):
        return "failed", f"claude -p returned is_error=true: {payload.get('result', '')}"
    result_text = str(payload.get("result", "")) if payload else stdout
    if not result_text.strip():
        return "failed", "The response was empty."
    if "`/alfred feature`" in result_text or "/alfred feature" in result_text:
        return "failed", "The response brought back the legacy /alfred prefix."
    return "needs_human_review", "Run completed. Review the response against the expected criterion."


def _safe_preview(value: object, limit: int = 2000) -> str:
    """Trim text evidence and keep secrets out of the release JSON."""
    return sanitize_text(str(value or "").strip())[:limit]


def _collect_artifact_previews(project: Path) -> dict[str, str]:
    previews: dict[str, str] = {}
    for relative in (
        ".claude/alfred-dev-state.json",
        ".claude/alfred-handoff.json",
        ".claude/alfred-uat.json",
        "docs/project/current.md",
        "docs/project/progress.md",
        "docs/project/traceability.md",
        "docs/project/uat.md",
        "docs/project/codebase-map.md",
        "docs/project/discovery.md",
        "docs/project/github-sync.md",
        ".claude/alfred-github-sync.json",
        ".claude/alfred-memory-ui.json",
    ):
        path = project / relative
        if path.is_file():
            previews[relative] = _safe_preview(
                path.read_text(encoding="utf-8", errors="replace"),
                2000,
            )
    return previews


def _cleanup_case_processes(project: Path) -> None:
    state_path = project / ".claude" / "alfred-memory-ui.json"
    if not state_path.exists():
        return
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "core" / "continuity.py"),
            "memory-ui",
            str(project),
            "--stop",
            "--json",
        ],
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )


def _run_case(case: ManualCase, plugin_dir: Path, budget: str, timeout: int) -> dict:
    with tempfile.TemporaryDirectory(prefix=f"alfred-manual-{case.case_id}-") as tmp:
        project = Path(tmp)
        SETUPS[case.setup](project)
        env = os.environ.copy()
        fake_bin = project / ".alfred-smoke-bin"
        if fake_bin.is_dir():
            env["PATH"] = f"{fake_bin}{os.pathsep}{env.get('PATH', '')}"
        command = [
            "claude",
            "-p",
            case.prompt,
            "--plugin-dir",
            str(plugin_dir),
            "--permission-mode",
            "bypassPermissions",
            "--max-budget-usd",
            budget,
            "--no-session-persistence",
            "--output-format",
            "json",
        ]
        started = time.time()
        try:
            result = subprocess.run(
                command,
                cwd=project,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                timeout=timeout,
                check=False,
            )
            duration_ms = int((time.time() - started) * 1000)
            artifacts = _collect_artifact_previews(project)
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.time() - started) * 1000)
            artifacts = _collect_artifact_previews(project)
            _cleanup_case_processes(project)
            return {
                **asdict(case),
                "status": "failed",
                "reason": f"claude -p exceeded the {timeout} second timeout.",
                "duration_ms": duration_ms,
                "returncode": None,
                "api_error_status": None,
                "total_cost_usd": None,
                "artifacts": artifacts,
                "response_preview": _safe_preview(exc.output, 2000),
                "stderr_preview": _safe_preview(exc.stderr, 2000),
            }
        _cleanup_case_processes(project)

    payload = None
    stdout = result.stdout.strip()
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None
    status, reason = _result_status(payload, result.stdout, result.stderr, result.returncode)
    if payload:
        response_text = payload.get("result") or payload.get("errors") or result.stdout
    else:
        response_text = result.stdout
    return {
        **asdict(case),
        "status": status,
        "reason": reason,
        "duration_ms": duration_ms,
        "returncode": result.returncode,
        "api_error_status": payload.get("api_error_status") if payload else None,
        "total_cost_usd": payload.get("total_cost_usd") if payload else None,
        "artifacts": artifacts,
        "response_preview": _safe_preview(response_text, 2000),
        "stderr_preview": _safe_preview(result.stderr, 2000),
    }


def _summary_payload(
    *,
    plugin_dir: Path,
    plugin_source_label: str,
    plugin_surface: dict,
    preflight: dict | None,
    results: list[dict],
    run_status: str,
) -> dict:
    return {
        "version": VERSION,
        "plugin_dir": str(plugin_dir),
        "plugin_source": plugin_source_label,
        "plugin_surface": plugin_surface,
        "auth_preflight": preflight,
        "run_status": run_status,
        "cases": results,
        "counts": {
            "total": len(results),
            "needs_human_review": sum(1 for item in results if item["status"] == "needs_human_review"),
            "blocked_auth": sum(1 for item in results if item["status"] == "blocked_auth"),
            "failed": sum(1 for item in results if item["status"] == "failed"),
        },
        "command_coverage": _case_command_coverage(),
        "option_coverage": _case_option_coverage(),
        "runtime_coverage": _case_runtime_coverage(),
    }


def _auth_status_snapshot() -> dict:
    """Return an auth diagnosis without printing emails, orgs or tokens."""
    snapshot: dict = {}
    snapshot["credential_env"] = _credential_env_snapshot()
    version = subprocess.run(
        ["claude", "--version"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    snapshot["claude_version"] = version.stdout.strip() or version.stderr.strip()
    status = subprocess.run(
        ["claude", "auth", "status", "--json"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
        check=False,
    )
    snapshot["auth_status_returncode"] = status.returncode
    if status.stdout.strip():
        try:
            raw = json.loads(status.stdout)
        except json.JSONDecodeError:
            snapshot["auth_status_parse_error"] = True
            snapshot["auth_status_preview"] = status.stdout.strip()[:300]
        else:
            for key in ("loggedIn", "authMethod", "apiProvider", "subscriptionType"):
                if key in raw:
                    snapshot[key] = raw[key]
    if status.stderr.strip():
        snapshot["auth_status_stderr"] = status.stderr.strip()[:300]
    return snapshot


def _credential_env_snapshot() -> dict[str, bool]:
    """Record only the presence of credentials that can change headless auth."""
    return {key: bool(os.environ.get(key)) for key in CREDENTIAL_ENV_KEYS}


def _parse_claude_version(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    prefix = value.strip().split(" ", 1)[0]
    parts = prefix.split(".")
    if len(parts) < 3:
        return None
    try:
        return tuple(int(part) for part in parts[:3])
    except ValueError:
        return None


def _auth_failure_diagnosis(status: str, api_error_status: int | None, auth_status: dict) -> dict:
    """Classify the auth block without relying on logs that contain credentials."""
    if status == "ok":
        return {
            "code": "ok",
            "summary": "Claude CLI completed a minimal headless call.",
            "next_steps": [],
        }
    if status == "blocked_auth" and api_error_status == 401:
        credential_env = auth_status.get("credential_env")
        active_credential_env = [
            key
            for key, is_set in (credential_env or {}).items()
            if is_set
        ] if isinstance(credential_env, dict) else []
        if active_credential_env:
            return {
                "code": "environment_credential_rejected",
                "summary": (
                    "claude -p got 401 and credential/provider environment "
                    "variables are set. They can take precedence over the "
                    "subscription login."
                ),
                "next_steps": [
                    "Check or temporarily unset these variables before the preflight: "
                    + ", ".join(active_credential_env),
                    "Run npm run release:audit:manual:preflight again in a clean environment.",
                    "If the block stays without active variables, refresh the session with claude auth logout and claude auth login.",
                ],
            }
        if auth_status.get("loggedIn") is True and auth_status.get("apiProvider") == "firstParty":
            version = _parse_claude_version(str(auth_status.get("claude_version", "")))
            next_steps = [
                "Run claude auth logout and claude auth login to refresh the local session.",
                "Run npm run release:audit:manual:preflight again.",
                "Run claude doctor to check the install, settings, MCP and access to local credentials.",
                "On macOS, if the login does not persist or doctor points to Keychain, unlock or resync the login keychain.",
                "If it persists, try claude setup-token or escalate to Claude Code support with a sanitized debug log.",
            ]
            if version is not None and version < (2, 1, 174):
                next_steps.insert(
                    0,
                    "Run claude update and repeat the preflight. Claude Code documents headless auth fixes from 2.1.174.",
                )
            return {
                "code": "first_party_oauth_token_rejected",
                "summary": (
                    "claude auth status reports an active login, but claude -p in "
                    "safe-mode gets 401 before it uses model tokens."
                ),
                "next_steps": next_steps,
            }
        if auth_status.get("loggedIn") is False:
            return {
                "code": "not_logged_in",
                "summary": "Claude CLI has no active local session to run claude -p.",
                "next_steps": [
                    "Run claude auth login.",
                    "Run npm run release:audit:manual:preflight again.",
                ],
            }
        return {
            "code": "headless_auth_rejected",
            "summary": "claude -p was rejected with 401 authentication on the minimal call.",
            "next_steps": [
                "Check claude auth status --json.",
                "Refresh the session with claude auth logout and claude auth login.",
                "Run claude doctor if the session looks active but claude -p keeps failing.",
                "Run npm run release:audit:manual:preflight again.",
            ],
        }
    if status == "failed":
        return {
            "code": "preflight_failed",
            "summary": "The minimal claude -p call failed for a reason other than 401 authentication.",
            "next_steps": [
                "Check returncode, response_preview and stderr_preview in the JSON evidence.",
                "Repeat with an updated Claude CLI if the error looks like a runtime error.",
            ],
        }
    return {
        "code": "unknown",
        "summary": "The preflight returned an unclassified status.",
        "next_steps": ["Check the full JSON evidence of the preflight."],
    }


def _auth_preflight(timeout: int = 45) -> dict:
    """Run a minimal Claude call to detect broken credentials."""
    auth_status = _auth_status_snapshot()
    command = [
        "claude",
        "-p",
        "Reply with exactly: OK",
        "--safe-mode",
        "--tools",
        "",
        "--max-budget-usd",
        "0.05",
        "--no-session-persistence",
        "--output-format",
        "json",
    ]
    started = time.time()
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    duration_ms = int((time.time() - started) * 1000)
    payload = None
    stdout = result.stdout.strip()
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None
    status, reason = _result_status(payload, result.stdout, result.stderr, result.returncode)
    if status == "needs_human_review":
        status = "ok"
        reason = "Claude CLI completed a minimal call."
    response_text = payload.get("result", "") if payload else result.stdout
    api_error_status = payload.get("api_error_status") if payload else None
    return {
        "status": status,
        "reason": reason,
        "duration_ms": duration_ms,
        "returncode": result.returncode,
        "api_error_status": api_error_status,
        "total_cost_usd": payload.get("total_cost_usd") if payload else None,
        "auth_status": auth_status,
        "diagnosis": _auth_failure_diagnosis(status, api_error_status, auth_status),
        "preflight_mode": "safe-mode; tools disabled; no session persistence; output json",
        "response_preview": _safe_preview(response_text, 500),
        "stderr_preview": _safe_preview(result.stderr, 500),
    }


def _available_cases() -> str:
    lines = []
    for case in CASES:
        command_label = ",".join(case.commands) if case.commands else "behavior"
        lines.append(f"- {case.case_id}: {case.prompt} [{case.setup}; {command_label}; {case.suite}]")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    plugin_source = parser.add_mutually_exclusive_group()
    plugin_source.add_argument("--plugin-dir", help="Plugin directory to pass to claude -p.")
    plugin_source.add_argument(
        "--installed",
        action="store_true",
        help="Use the installed Claude cache instead of the current worktree.",
    )
    parser.add_argument("--case", action="append", help="Case ID to run. Repeatable.")
    parser.add_argument("--budget", default="1.50", help="Budget per prompt in USD.")
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="Timeout per prompt in seconds.",
    )
    parser.add_argument("--output", help="JSON path to save the evidence.")
    parser.add_argument("--dry-run", action="store_true", help="List cases and do not run Claude.")
    parser.add_argument(
        "--auth-preflight",
        action="store_true",
        help="Run a minimal claude -p call before the cases.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="With --auth-preflight, validate authentication and do not run the manual matrix.",
    )
    parser.add_argument(
        "--allow-auth-failure",
        action="store_true",
        help="Return 0 if the only block reason is 401 authentication.",
    )
    args = parser.parse_args(argv)

    selected_ids = args.case or [case.case_id for case in CASES]
    known = {case.case_id: case for case in CASES}
    unknown = [case_id for case_id in selected_ids if case_id not in known]
    if unknown:
        print(f"Unknown cases: {', '.join(unknown)}\n\nAvailable:\n{_available_cases()}", file=sys.stderr)
        return 2
    selected = [known[case_id] for case_id in selected_ids]

    plugin_dir, plugin_source_label = _select_plugin_dir(args.plugin_dir, args.installed)
    if args.dry_run:
        print(f"plugin_dir={plugin_dir}")
        print(f"plugin_source={plugin_source_label}")
        print(_available_cases())
        print(_coverage_summary())
        return 0
    if not shutil.which("claude"):
        print("FAIL manual-smoke: claude CLI is not in PATH.", file=sys.stderr)
        return 2
    if not plugin_dir.exists():
        print(f"FAIL manual-smoke: plugin-dir does not exist: {plugin_dir}", file=sys.stderr)
        return 2
    plugin_surface = _plugin_surface_snapshot(plugin_dir)

    preflight = None
    if args.auth_preflight:
        preflight = _auth_preflight(timeout=min(args.timeout, 45))
        if preflight["status"] != "ok":
            summary = {
                "version": VERSION,
                "plugin_dir": str(plugin_dir),
                "plugin_source": plugin_source_label,
                "plugin_surface": plugin_surface,
                "auth_preflight": preflight,
                "run_status": "blocked",
                "cases": [],
                "counts": {
                    "total": 0,
                    "needs_human_review": 0,
                    "blocked_auth": 1 if preflight["status"] == "blocked_auth" else 0,
                    "failed": 1 if preflight["status"] == "failed" else 0,
                },
                "command_coverage": _case_command_coverage(),
                "option_coverage": _case_option_coverage(),
                "runtime_coverage": _case_runtime_coverage(),
            }
            if args.output:
                output_path = Path(args.output).expanduser()
                _write_json(output_path, summary)
                print(f"evidence={output_path}")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            if preflight["status"] == "blocked_auth" and args.allow_auth_failure:
                return 0
            return 1 if preflight["status"] == "failed" else 2
        if args.preflight_only:
            summary = {
                "version": VERSION,
                "plugin_dir": str(plugin_dir),
                "plugin_source": plugin_source_label,
                "plugin_surface": plugin_surface,
                "auth_preflight": preflight,
                "run_status": "preflight-only",
                "cases": [],
                "counts": {
                    "total": 0,
                    "needs_human_review": 0,
                    "blocked_auth": 0,
                    "failed": 0,
                },
                "command_coverage": _case_command_coverage(),
                "option_coverage": _case_option_coverage(),
                "runtime_coverage": _case_runtime_coverage(),
            }
            if args.output:
                output_path = Path(args.output).expanduser()
                _write_json(output_path, summary)
                print(f"evidence={output_path}")
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0

    output_path = Path(args.output).expanduser() if args.output else None
    results: list[dict] = []
    if output_path:
        _write_json(
            output_path,
            _summary_payload(
                plugin_dir=plugin_dir,
                plugin_source_label=plugin_source_label,
                plugin_surface=plugin_surface,
                preflight=preflight,
                results=results,
                run_status="running",
            ),
        )
        print(f"evidence={output_path}", file=sys.stderr)

    for index, case in enumerate(selected, start=1):
        print(
            f"[{index}/{len(selected)}] {case.case_id}: {case.prompt}",
            file=sys.stderr,
            flush=True,
        )
        results.append(_run_case(case, plugin_dir, args.budget, args.timeout))
        if output_path:
            _write_json(
                output_path,
                _summary_payload(
                    plugin_dir=plugin_dir,
                    plugin_source_label=plugin_source_label,
                    plugin_surface=plugin_surface,
                    preflight=preflight,
                    results=results,
                    run_status="running",
                ),
            )

    summary = _summary_payload(
        plugin_dir=plugin_dir,
        plugin_source_label=plugin_source_label,
        plugin_surface=plugin_surface,
        preflight=preflight,
        results=results,
        run_status="complete",
    )
    if args.output:
        _write_json(output_path, summary)
        print(f"evidence={output_path}")

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if summary["counts"]["failed"]:
        return 1
    if summary["counts"]["blocked_auth"]:
        if args.allow_auth_failure and summary["counts"]["blocked_auth"] == summary["counts"]["total"]:
            return 0
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
