#!/usr/bin/env python3
"""
Flow orchestrator for the Alfred Dev plugin.

This module manages the full lifecycle of the work flows
(feature, fix, quick, spike, ship, audit). Each flow has sequential
phases with control gates. A gate decides if the flow can move to
the next phase.

The orchestrator:
- Defines the available flows and their phases.
- Creates and manages work sessions.
- Evaluates the gate of each phase to approve the advance.
- Saves and loads session state on disk.
- Manages the iterative loop inside each phase (v0.4.0).
- Supports autopilot mode to run without interruption (v0.4.0).

Gate architecture:
    Gates are checkpoints between phases. Their behavior depends on the
    type set in each phase: "user" gates require explicit approval;
    "automatic" gates check objective metrics such as green tests or
    a passing pipeline; combined gates (for example
    "automatic+security") require both conditions.

Iterative loop (v0.4.0):
    Inside each phase, agents can iterate until the deliverables are
    complete or the iteration limit is reached. The loop stays inside
    the phase: the flow does not advance until the gate passes. This
    allows TDD cycles (red-green-refactor) and repeated QA passes
    without manual intervention.

Autopilot mode (v0.4.0):
    When ``autopilot=True``, the flow runs through all phases and does
    not ask the user for approval at "user" gates. Automatic and
    security gates are still evaluated as usual. The flow stops only
    when an automatic or security gate fails.
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from core.optional_agents import (
    get_optional_agent_names,
    get_optional_integrations,
    normalize_optional_agent_flags,
)

# --- Gate type constants ----------------------------------------------------
# Constants prevent duplicate literals and keep validation in one place.

GATE_USER = "user"
GATE_AUTOMATIC = "automatic"
GATE_FREE = "free"
GATE_USER_SECURITY = "user+security"
GATE_AUTOMATIC_SECURITY = "automatic+security"

_KNOWN_GATE_TYPES = {
    GATE_FREE, GATE_USER, GATE_AUTOMATIC,
    GATE_USER_SECURITY, GATE_AUTOMATIC_SECURITY,
}

# --- Known optional agents ---------------------------------------------------
# Canonical list of the plugin's optional agents. Used to validate the
# structure of the session team in dynamic composition.

_KNOWN_OPTIONAL_AGENTS = frozenset(get_optional_agent_names())
_KNOWN_SESSION_TEAM_SOURCES = frozenset({
    "dynamic_composition",
    "persisted_config",
})

# --- Flow definitions --------------------------------------------------------
# Each flow describes a sequence of phases that the orchestrator runs.
# The agents listed in each phase are responsible for running it.

FLOWS: Dict[str, Dict[str, Any]] = {
        "feature": {
        "name": "feature",
        "phases": [
            {
                "name": "product",
                "agents": ["product-owner"],
                "parallel": False,
                "gate": "gate_product",
                "gate_type": GATE_USER,
                "description": (
                    "Анализ требований и определение функционального "
                    "объёма новой feature."
                ),
            },
            {
                "name": "visual_style",
                "agents": ["designer"],
                "parallel": False,
                "gate": "gate_style",
                "gate_type": GATE_USER,
                "condition": "has_frontend",
                "description": (
                    "Определение направления визуального стиля "
                    "продукта на основе трёх сопоставимых предложений."
                ),
            },
            {
                "name": "architecture",
                "agents": ["architect", "security-officer"],
                "parallel": True,
                "gate": "gate_architecture",
                "gate_type": GATE_USER_SECURITY,
                "description": (
                    "Техническое проектирование, выбор паттернов и проверка "
                    "архитектурного решения с threat model."
                ),
            },
            {
                "name": "development",
                "agents": ["senior-dev"],
                "parallel": False,
                "gate": "gate_development",
                "gate_type": GATE_AUTOMATIC,
                "description": (
                    "Реализация кода по строгому TDD "
                    "с циклами red-green-refactor."
                ),
            },
            {
                "name": "quality",
                "agents": ["qa-engineer", "security-officer"],
                "parallel": True,
                "gate": "gate_quality",
                "gate_type": GATE_AUTOMATIC_SECURITY,
                "description": (
                    "Проверка качества, запуск тестов и "
                    "аудит безопасности параллельно."
                ),
            },
            {
                "name": "documentation",
                "agents": ["tech-writer"],
                "parallel": False,
                "gate": "gate_documentation",
                "gate_type": GATE_FREE,
                "description": (
                    "Создание технической и пользовательской "
                    "документации для сообщества."
                ),
            },
            {
                "name": "delivery",
                "agents": ["devops-engineer", "security-officer"],
                "parallel": False,
                "gate": "gate_delivery",
                "gate_type": GATE_USER_SECURITY,
                "description": (
                    "Подготовка поставки, changelog и "
                    "финальная проверка перед merge."
                ),
            },
        ],
    },
    "fix": {
        "name": "fix",
        "phases": [
            {
                "name": "diagnosis",
                "agents": ["senior-dev"],
                "parallel": False,
                "gate": "gate_diagnosis",
                "gate_type": GATE_USER,
                "description": (
                    "Поиск первопричины бага "
                    "через анализ логов, трассировок и воспроизведение."
                ),
            },
            {
                "name": "correction",
                "agents": ["senior-dev"],
                "parallel": False,
                "gate": "gate_correction",
                "gate_type": GATE_AUTOMATIC,
                "description": (
                    "Применение fix с регрессионным тестом, "
                    "который доказывает, что баг устранён."
                ),
            },
            {
                "name": "validation",
                "agents": ["qa-engineer", "security-officer"],
                "parallel": True,
                "gate": "gate_validation",
                "gate_type": GATE_AUTOMATIC_SECURITY,
                "description": (
                    "Полная проверка: регрессионные тесты, "
                    "существующий набор тестов и проверка безопасности."
                ),
            },
        ],
    },
    "quick": {
        "name": "quick",
        "phases": [
            {
                "name": "scoped_execution",
                "agents": ["senior-dev"],
                "parallel": False,
                "gate": "gate_scoped_execution",
                "gate_type": GATE_AUTOMATIC,
                "description": (
                    "Ограниченная реализация для небольших, "
                    "локальных изменений с низким риском и автоматической проверкой."
                ),
            },
            {
                "name": "quick_validation",
                "agents": ["qa-engineer", "security-officer"],
                "parallel": True,
                "gate": "gate_quick_validation",
                "gate_type": GATE_AUTOMATIC_SECURITY,
                "description": (
                    "Быстрая проверка изменения на затронутой области: "
                    "локальная регрессия, тесты и проверка безопасности."
                ),
            },
        ],
    },
    "spike": {
        "name": "spike",
        "phases": [
            {
                "name": "exploration",
                "agents": ["architect", "senior-dev"],
                "parallel": True,
                "gate": "gate_exploration",
                "gate_type": GATE_FREE,
                "description": (
                    "Исследование: proof of concept, "
                    "бенчмарки и оценка альтернатив."
                ),
            },
            {
                "name": "conclusions",
                "agents": ["architect"],
                "parallel": False,
                "gate": "gate_conclusions",
                "gate_type": GATE_USER,
                "description": (
                    "Сведение находок в отчёт "
                    "с практическими рекомендациями."
                ),
            },
        ],
    },
    "ship": {
        "name": "ship",
        "phases": [
            {
                "name": "final_audit",
                "agents": ["qa-engineer", "security-officer"],
                "parallel": True,
                "gate": "gate_final_audit",
                "gate_type": GATE_AUTOMATIC_SECURITY,
                "description": (
                    "Полный аудит качества и безопасности "
                    "перед релизом."
                ),
            },
            {
                "name": "documentation",
                "agents": ["tech-writer"],
                "parallel": False,
                "gate": "gate_documentation_ship",
                "gate_type": GATE_FREE,
                "description": (
                    "Обновление документации релиза, "
                    "changelog и руководств по миграции."
                ),
            },
            {
                "name": "packaging",
                "agents": ["devops-engineer", "security-officer"],
                "parallel": False,
                "gate": "gate_packaging",
                "gate_type": GATE_AUTOMATIC_SECURITY,
                "description": (
                    "Сборка артефакта релиза, "
                    "семантическое версионирование и тегирование."
                ),
            },
            {
                "name": "deployment",
                "agents": ["devops-engineer"],
                "parallel": False,
                "gate": "gate_deployment",
                "gate_type": GATE_USER_SECURITY,
                "autopilot_force_user_confirmation": True,
                "description": (
                    "Развёртывание в production с проверкой "
                    "после deploy и подготовленным rollback."
                ),
            },
        ],
    },
    "audit": {
        "name": "audit",
        "phases": [
            {
                "name": "parallel_audit",
                "agents": [
                    "qa-engineer",
                    "security-officer",
                    "architect",
                    "tech-writer",
                ],
                "parallel": True,
                "gate": "gate_audit",
                "gate_type": GATE_AUTOMATIC_SECURITY,
                "description": (
                    "Полный параллельный аудит кода: "
                    "качество, безопасность, архитектура "
                    "и документация."
                ),
            },
        ],
    },
}


# --- Optional agent integration ----------------------------------------------
# This map defines the phases where each optional agent can support the
# core agents. The position tells if the agent runs in parallel with the
# core agents or sequentially after them.
#
# The Librarian does not take part in active flows: it is advisory (via MCP)
# and does not need a place in any execution phase.

OPTIONAL_INTEGRATIONS: Dict[str, Dict[str, Any]] = get_optional_integrations()

# --- Phase condition evaluators ----------------------------------------------
# Map from declarative conditions to evaluator functions.
# Each condition receives the project stack and returns True if the phase
# must run. The import is lazy, inside the function, to prevent circular
# imports with config_loader.

_PHASE_CONDITIONS: Optional[Dict[str, Any]] = None


def _get_phase_conditions() -> Dict[str, Any]:
    """Return the condition map. Initialize it lazily."""
    global _PHASE_CONDITIONS
    if _PHASE_CONDITIONS is None:
        from core.config_loader import has_frontend  # noqa: PLC0415
        # "has_frontend" calls config_loader.has_frontend(stack) to decide
        # if the visual_style phase must run. The import is lazy to prevent
        # circular imports between orchestrator and config_loader.
        _PHASE_CONDITIONS = {
            "has_frontend": has_frontend,
        }
    return _PHASE_CONDITIONS


def _advance_skipping_phases(
    session: Dict[str, Any],
    phases: List[Dict[str, Any]],
    following: int,
    conditions: Dict[str, Any],
) -> int:
    """Advance the index and skip phases whose condition is not met.

    Records each skipped phase in ``session["completed_phases"]`` with
    result ``"skipped"``. Stops at the first runnable phase (no condition
    or condition met) or when no stack is available to evaluate the
    condition.

    Args:
        session: session state (mutated to record skipped phases).
        phases: list of flow phases.
        following: start index for the search.
        conditions: map from condition name to evaluator function.

    Returns:
        Index of the next runnable phase.
    """
    stack = session.get("stack")
    while following < len(phases):
        next_phase = phases[following]
        condition_name = next_phase.get("condition")
        if not condition_name or condition_name not in conditions:
            break
        if stack is None:
            # Without a stack the condition cannot be evaluated: run the phase
            break
        if conditions[condition_name](stack):
            break
        # Condition not met: record the skipped phase and continue
        session["completed_phases"].append({
            "name": next_phase["name"],
            "result": "skipped",
            "artifacts": [],
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "iterations": 0,
        })
        following += 1
    return following


def get_effective_agents(
    phase_name: str,
    active_optionals: Optional[Dict[str, bool]] = None,
) -> Dict[str, List[str]]:
    """Compute the agents of a phase, including active optional agents.

    Merges the core agents defined in FLOWS with the active optional agents
    that integrate with that phase. The result separates parallel and
    sequential agents so that commands know how to launch them.

    Args:
        phase_name: phase name (for example "architecture", "quality").
        active_optionals: dict of active optional agents.
            Key = agent name, value = True if active.
            If None, no optional agents are added.

    Returns:
        Dict with two keys:
        - "parallel": optional agents that run in parallel with the
          core agents.
        - "sequential": optional agents that run after the core agents.

    Example:
        >>> get_effective_agents("quality", {"ux-reviewer": True, "performance-engineer": True})
        {"parallel": ["ux-reviewer", "performance-engineer"], "sequential": []}
    """
    if active_optionals is None:
        return {"parallel": [], "sequential": []}

    parallel: List[str] = []
    sequential: List[str] = []

    for agent_name, config in OPTIONAL_INTEGRATIONS.items():
        if not active_optionals.get(agent_name, False):
            continue
        if phase_name not in config.get("phases", []):
            continue

        position = config.get("position", "parallel")
        if position == "sequential":
            sequential.append(agent_name)
        elif position == "parallel":
            parallel.append(agent_name)

    return {"parallel": parallel, "sequential": sequential}


def _resolve_current_phase(session: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Resolve and validate the current phase of a session."""
    command = session.get("command")
    if command not in FLOWS:
        return None, f"Процесс '{command}' не определён в FLOWS."

    current_phase = session.get("current_phase")
    if current_phase == "completed":
        return None, "Сессия завершена. Ожидающего gate нет."

    phase_number = session.get("phase_number")
    if not isinstance(phase_number, int):
        return None, "Индекс фазы не является допустимым целым числом."
    if phase_number < 0:
        return None, f"Индекс фазы не может быть отрицательным: {phase_number}."

    phases = FLOWS[command]["phases"]
    if phase_number >= len(phases):
        return None, (
            f"Индекс фазы {phase_number} вне диапазона для процесса "
            f"'{command}' (фаз: {len(phases)})."
        )

    phase = phases[phase_number]
    expected_name = phase["name"]
    if current_phase != expected_name:
        return None, (
            "Состояние сессии противоречиво: "
            f"current_phase='{current_phase}' не совпадает с phase_number={phase_number} "
            f"('{expected_name}')."
        )

    return phase, ""


def _validate_session_team(session_team: Any) -> bool:
    """Validate the session team structure built by dynamic composition.

    Checks that the dict has the expected keys at each level and that the
    values have the correct type. On failure, prints a descriptive warning
    to stderr and returns False. This lets the orchestrator discard
    malformed teams without breaking the flow.

    Validation rules per level:

        - **Top level**: requires exactly the keys ``"active_optionals"``,
          ``"infra"`` and ``"source"``. Extra or missing keys cause rejection.
        - **``active_optionals``**: requires at least the keys of
          ``_KNOWN_OPTIONAL_AGENTS``. Accepts extra keys with a warning to
          stderr (tolerance for future extensions) but does not validate
          them. All values must be ``bool``.
        - **``infra``**: requires exactly ``"memory"``, of type ``bool``.
        - **``source``**: must be one of the known runtime sources
          (currently ``"dynamic_composition"`` or ``"persisted_config"``).

    Args:
        session_team: value to validate. Expected: a dict with the keys
            ``"active_optionals"``, ``"infra"`` and ``"source"``.

    Returns:
        True if the structure is valid, False otherwise.

    Example:
        >>> _validate_session_team({"active_optionals": {...}, "infra": {...}, "source": "dynamic_composition"})
        True
    """
    # --- 1. Must be a dict ---
    if not isinstance(session_team, dict):
        print(
            "[Alfred Dev] Предупреждение: session_team не является словарём.",
            file=sys.stderr,
        )
        return False

    # --- 2. Top-level keys ---
    expected_top_keys = {"active_optionals", "infra", "source"}
    if set(session_team.keys()) != expected_top_keys:
        print(
            f"[Alfred Dev] Предупреждение: в session_team неожиданные ключи. "
            f"Ожидались: {sorted(expected_top_keys)}, "
            f"получены: {sorted(session_team.keys())}.",
            file=sys.stderr,
        )
        return False

    # --- 3. active_optionals: dict with at least the known keys, bool values ---
    optionals = session_team["active_optionals"]
    if not isinstance(optionals, dict):
        print(
            "[Alfred Dev] Предупреждение: active_optionals не является словарём.",
            file=sys.stderr,
        )
        return False

    # Old states can use legacy names (for example "lucius").
    optionals = normalize_optional_agent_flags(optionals)
    session_team["active_optionals"] = optionals

    # The known keys must be present. Extra keys are accepted with a
    # warning (tolerance for future extensions).
    missing = _KNOWN_OPTIONAL_AGENTS - set(optionals.keys())
    if missing:
        print(
            f"[Alfred Dev] Предупреждение: в active_optionals нет "
            f"обязательных агентов: {sorted(missing)}.",
            file=sys.stderr,
        )
        return False

    extra = set(optionals.keys()) - _KNOWN_OPTIONAL_AGENTS
    if extra:
        print(
            f"[Alfred Dev] Предупреждение: в active_optionals есть "
            f"неизвестные агенты, они будут проигнорированы: {sorted(extra)}.",
            file=sys.stderr,
        )

    for agent_name, value in optionals.items():
        if not isinstance(value, bool):
            print(
                f"[Alfred Dev] Предупреждение: active_optionals['{agent_name}'] не bool "
                f"(тип: {type(value).__name__}, значение: {value!r}).",
                file=sys.stderr,
            )
            return False

    # --- 4. infra: dict with exactly "memory", bool value ---
    infra = session_team["infra"]
    if not isinstance(infra, dict):
        print(
            "[Alfred Dev] Предупреждение: infra не является словарём.",
            file=sys.stderr,
        )
        return False

    expected_infra_keys = {"memory"}
    actual_keys = set(infra.keys())
    # Accept "gui" for compatibility with states from older sessions
    accepted_keys = actual_keys - {"gui"}
    if accepted_keys != expected_infra_keys:
        print(
            f"[Alfred Dev] Предупреждение: в infra неожиданные ключи. "
            f"Ожидались: {sorted(expected_infra_keys)}, "
            f"получены: {sorted(infra.keys())}.",
            file=sys.stderr,
        )
        return False

    for infra_key, value in infra.items():
        if infra_key == "gui":
            continue  # Ignore the obsolete key
        if not isinstance(value, bool):
            print(
                f"[Alfred Dev] Предупреждение: infra['{infra_key}'] не bool "
                f"(тип: {type(value).__name__}, значение: {value!r}).",
                file=sys.stderr,
            )
            return False

    # --- 5. source: must be a known runtime source ---
    if session_team["source"] not in _KNOWN_SESSION_TEAM_SOURCES:
        print(
            f"[Alfred Dev] Предупреждение: source должен быть одним из "
            f"{sorted(_KNOWN_SESSION_TEAM_SOURCES)}, "
            f"получено: {session_team['source']!r}.",
            file=sys.stderr,
        )
        return False

    return True


def _load_persisted_session_team(
    project_dir: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load the runtime team derived from the persisted configuration."""
    try:
        from core.config_loader import build_project_session_team  # noqa: PLC0415

        session_team = build_project_session_team(project_dir)
    except Exception as exc:
        print(
            "[Alfred Dev] Предупреждение: не удалось загрузить сохранённую команду "
            f"проекта '{project_dir}': {exc}",
            file=sys.stderr,
        )
        return None, (
            "Не удалось загрузить сохранённую конфигурацию проекта; "
            "сессия продолжится без опциональных агентов."
        )

    if session_team is None:
        return None, None

    if not _validate_session_team(session_team):
        print(
            "[Alfred Dev] Предупреждение: команда из сохранённой "
            "конфигурации не прошла проверку и будет проигнорирована.",
            file=sys.stderr,
        )
        return None, (
            "Сохранённая конфигурация проекта дала недопустимую команду "
            "сессии и была отброшена."
        )

    return session_team, None


def run_flow(
    command: str,
    description: str,
    session_team: Optional[Dict[str, Any]] = None,
    project_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a flow session with an optional dynamically composed team.

    Combines the standard session creation with the injection of the
    session team built by dynamic composition. If the given team fails
    validation, it is discarded with a warning to stderr, and the reason
    is stored in ``session["session_team_error"]`` so that downstream
    consumers can inform the user.

    This is the main entry point to start a flow when you know which
    optional agents must take part.

    Args:
        command: flow identifier (feature, fix, quick, spike, ship, audit).
        description: natural language description of the task.
        session_team: dict with the team composition built by the dynamic
            composition module. If None, the session has no team. If
            invalid, it is discarded with a warning and the reason is
            stored in "session_team_error".
        project_dir: path of the project used to detect the stack and load
            the persisted configuration. Defaults to the current working
            directory.

    Returns:
        Dict with the session state, including the keys:
        - "session_team" (valid dict or None).
        - "session_team_error" (str or None): reason for the discard.

    Raises:
        ValueError: if the command does not match a defined flow.

    Example:
        >>> session = run_flow("feature", "Login with OAuth", session_team={...})
        >>> session["session_team"]["active_optionals"]["cto"]
        True
    """
    # --- 1. Validate that the command exists ---
    if command not in FLOWS:
        raise ValueError(
            f"Процесс '{command}' не распознан. "
            f"Доступные процессы: {', '.join(FLOWS.keys())}"
        )

    resolved_project_dir = os.path.abspath(project_dir or os.getcwd())

    # --- 2. Validate session_team if given ---
    team_error = None
    explicit_team_discarded = False
    if session_team is not None and not _validate_session_team(session_team):
        print(
            "[Alfred Dev] Ошибка: команда сессии не прошла проверку. "
            "Сессия будет создана без опциональных агентов. Проверь структуру "
            "словаря session_team.",
            file=sys.stderr,
        )
        team_error = (
            "Переданная команда сессии не прошла проверку "
            "и была отброшена."
        )
        session_team = None
        explicit_team_discarded = True

    if session_team is None:
        persisted_team, persisted_error = _load_persisted_session_team(resolved_project_dir)
        if persisted_team is not None:
            session_team = persisted_team
            if explicit_team_discarded:
                team_error = (
                    f"{team_error} Применена сохранённая конфигурация "
                    "опциональных агентов проекта."
                )
        elif persisted_error:
            if explicit_team_discarded:
                team_error = f"{team_error} {persisted_error}"
            else:
                team_error = persisted_error

    # --- 3. Detect the project stack for conditional phases ---
    stack = None
    try:
        from core.config_loader import detect_stack  # noqa: PLC0415
        stack = detect_stack(resolved_project_dir)
    except Exception as exc:
        print(
            f"[Alfred Dev] Предупреждение: не удалось определить stack проекта: {exc}",
            file=sys.stderr,
        )

    # --- 4. Create the base session ---
    session = create_session(command, description, stack=stack)

    # --- 5. Inject session_team and the diagnostic ---
    session["session_team"] = session_team
    session["session_team_error"] = team_error

    return session


def create_session(
    command: str,
    description: str,
    stack: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Create a new work session for the given flow.

    The session holds all the state the orchestrator needs to know where
    the user is in the flow and which phases are complete.

    Args:
        command: flow identifier (feature, fix, quick, spike, ship, audit).
        description: natural language description of the task.
        stack: detected project metadata. If given, conditional phases
            such as ``visual_style`` can be evaluated.

    Returns:
        Dict with the initial session state.

    Raises:
        ValueError: if the command does not match a defined flow.
    """
    if command not in FLOWS:
        raise ValueError(
            f"Процесс '{command}' не распознан. "
            f"Доступные процессы: {', '.join(FLOWS.keys())}"
        )

    flow = FLOWS[command]
    first_phase = flow["phases"][0]["name"]

    session = {
        "command": command,
        "description": description,
        "current_phase": first_phase,
        "phase_number": 0,
        "completed_phases": [],
        "artifacts": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if stack is not None:
        session["stack"] = stack
    return session


def check_gate(
    session: Dict[str, Any],
    result: str = "",
    security_ok: bool = True,
    tests_ok: bool = True,
) -> Dict[str, Any]:
    """
    Evaluate the gate of the current phase to decide if the flow can advance.

    The logic depends on the gate type defined in the phase:
    - "user": requires result "approved".
    - "automatic": requires result "approved" and green tests.
    - "user+security": requires user approval and a passing security check.
    - "automatic+security": requires tests, security and a passing result.
    - "free": passes when the result is "approved".

    Args:
        session: current session state.
        result: reported result (usually "approved" or "rejected").
        security_ok: True if the security audit passed.
        tests_ok: True if the tests pass.

    Returns:
        Dict with the keys "passed" (bool) and "reason" (str).
    """
    command = session["command"]
    if command not in FLOWS:
        return {"passed": False, "reason": f"Процесс '{command}' не определён в FLOWS."}

    # Session complete: no gate to evaluate.
    if session.get("current_phase") == "completed":
        return {"passed": True, "reason": "Сессия завершена. Ожидающего gate нет."}

    phase, phase_error = _resolve_current_phase(session)
    if phase is None:
        return {"passed": False, "reason": phase_error}

    gate_type = phase["gate_type"]

    # Collect the conditions the gate must meet.
    # The check order sets which error is reported first.
    failures = []

    requires_tests = "automatic" in gate_type
    requires_security = "security" in gate_type
    requires_approval = gate_type in (GATE_USER, GATE_USER_SECURITY)
    is_known = gate_type in _KNOWN_GATE_TYPES

    if not is_known:
        return {"passed": False, "reason": f"Неизвестный тип gate: {gate_type}"}

    if requires_tests and not tests_ok:
        failures.append("Тесты не проходят.")
    if requires_security and not security_ok:
        failures.append("Аудит безопасности не пройден.")
    if result != "approved":
        if requires_approval:
            failures.append("Требуется одобрение пользователя.")
        else:
            failures.append("Результат неудовлетворительный.")

    passed = len(failures) == 0
    reason = failures[0] if failures else ""

    return {"passed": passed, "reason": reason}


def advance_phase(
    session: Dict[str, Any],
    result: str = "approved",
    artifacts: Optional[List[str]] = None,
    security_ok: bool = True,
    tests_ok: bool = True,
) -> Dict[str, Any]:
    """
    Try to advance the session to the next phase of the flow.

    First evaluates the gate of the current phase. If the gate passes,
    records the phase as complete and moves the pointer to the next one.
    If no phases remain, marks the session as "completed".

    Args:
        session: current session state.
        result: result to evaluate at the gate (default "approved").
        artifacts: optional list of artifacts produced in the phase.
        security_ok: True if the security audit passed.
        tests_ok: True if the tests pass.

    Returns:
        Dict with the updated session state.

    Raises:
        RuntimeError: if the gate of the current phase does not pass.
    """
    if artifacts is None:
        artifacts = []

    command = session["command"]
    if command not in FLOWS:
        raise RuntimeError(f"Процесс '{command}' не определён в FLOWS.")

    flow = FLOWS[command]
    phases = flow["phases"]

    # If already complete, return without changes
    if session["current_phase"] == "completed":
        return session

    # Evaluate the gate of the current phase with all parameters
    gate_result = check_gate(
        session, result=result, security_ok=security_ok, tests_ok=tests_ok
    )
    if not gate_result["passed"]:
        raise RuntimeError(
            f"Нельзя перейти дальше: {gate_result['reason']}"
        )

    # Record the completed phase. Keep the iteration counter so that
    # session reports can show how many cycles the phase needed.
    completed_phase = {
        "name": phases[session["phase_number"]]["name"],
        "result": result,
        "artifacts": artifacts,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "iterations": session.get("phase_iterations", 0),
    }
    session["completed_phases"].append(completed_phase)

    # Add the artifacts to the global session record
    session["artifacts"].extend(artifacts)

    # Move to the next index and skip phases whose condition is not met
    following = _advance_skipping_phases(
        session, phases, session["phase_number"] + 1, _get_phase_conditions()
    )

    if following < len(phases):
        session["phase_number"] = following
        session["current_phase"] = phases[following]["name"]
    else:
        # No phases remain: the flow is complete
        session["current_phase"] = "completed"
        session["phase_number"] = following

    # Reset the internal iteration counter for the new phase
    session["phase_iterations"] = 0

    session["updated_at"] = datetime.now(timezone.utc).isoformat()
    return session


def save_state(session: Dict[str, Any], state_path: str) -> None:
    """
    Save the session state to a JSON file.

    Uses an atomic write (write + rename) to prevent corruption if the
    process stops in the middle of the write. On failure, removes the
    temporary file and raises the error again as RuntimeError so that the
    caller knows the state was not saved.

    Args:
        session: session state to save.
        state_path: absolute path of the target file.

    Raises:
        RuntimeError: if the state cannot be saved for any reason.
    """
    persisted = session
    sync_session_state_to_operational_docs = None
    canonical_project_dir = os.path.dirname(os.path.dirname(os.path.abspath(state_path)))
    is_canonical_state_path = (
        os.path.basename(state_path) == "alfred-dev-state.json"
        and os.path.basename(os.path.dirname(os.path.abspath(state_path))) == ".claude"
    )
    if is_canonical_state_path:
        try:
            from core.continuity import (  # noqa: PLC0415
                sync_session_state_to_kanban,
                sync_session_state_to_operational_docs,
            )
        except Exception:
            sync_session_state_to_kanban = None
            sync_session_state_to_operational_docs = None

        if sync_session_state_to_kanban is not None:
            try:
                persisted = sync_session_state_to_kanban(state_path, session)
            except Exception as exc:  # pragma: no cover - operational best effort
                print(
                    f"[Alfred Dev] Предупреждение: не удалось синхронизировать kanban из save_state: {exc}",
                    file=sys.stderr,
                )
                persisted = session

    tmp_path = state_path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(persisted, f, indent=2, ensure_ascii=False)
        # Atomic rename on POSIX systems
        os.replace(tmp_path, state_path)
        if is_canonical_state_path and sync_session_state_to_operational_docs is not None:
            try:
                persisted = sync_session_state_to_operational_docs(
                    canonical_project_dir,
                    persisted,
                )
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(persisted, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, state_path)
            except Exception as exc:  # pragma: no cover - operational best effort
                if os.path.exists(tmp_path):
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                print(
                    f"[Alfred Dev] Предупреждение: не удалось синхронизировать операционную документацию из save_state: {exc}",
                    file=sys.stderr,
                )
    except (OSError, TypeError) as e:
        # Remove the temporary file if it was left behind
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError as cleanup_err:
                print(
                    f"[Alfred Dev] Предупреждение: не удалось удалить временный файл "
                    f"'{tmp_path}': {cleanup_err}",
                    file=sys.stderr,
                )
        raise RuntimeError(
            f"Не удалось сохранить состояние сессии в '{state_path}': {e}"
        ) from e


# Minimum keys of a valid session state
_REQUIRED_STATE_KEYS = {"command", "current_phase", "phase_number"}


def load_state(state_path: str) -> Optional[Dict[str, Any]]:
    """
    Load the session state from a JSON file.

    Handles three cases:
    - Missing file: returns None silently (normal case).
    - Corrupt or unreadable file: returns None and warns on stderr.
    - File with an invalid structure: returns None and warns on stderr.

    Args:
        state_path: absolute path of the file to read.

    Returns:
        Dict with the session state, or None if the file does not exist,
        is corrupt or has an invalid structure.
    """
    try:
        with open(state_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as e:
        print(
            f"[Alfred Dev] Ошибка: файл состояния '{state_path}' повреждён: {e}. "
            f"Чтобы исправить, удали файл вручную: в следующей сессии "
            f"будет создан новый.",
            file=sys.stderr,
        )
        return None
    except OSError as e:
        print(
            f"[Alfred Dev] Ошибка чтения состояния сессии '{state_path}': {e}",
            file=sys.stderr,
        )
        return None

    # Validate the minimum structure: required keys are present
    if not isinstance(data, dict) or not _REQUIRED_STATE_KEYS.issubset(data.keys()):
        print(
            f"[Alfred Dev] Предупреждение: у файла состояния '{state_path}' "
            f"неожиданная структура (нет обязательных ключей). Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None

    # Validate the types of the required keys to prevent TypeError
    # in later comparisons (for example phase_number >= len(phases))
    if not isinstance(data.get("command"), str):
        print(
            f"[Alfred Dev] Предупреждение: 'comando' не строка в '{state_path}'. Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None
    if not isinstance(data.get("current_phase"), str):
        print(
            f"[Alfred Dev] Предупреждение: 'current_phase' не строка в '{state_path}'. Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None
    if not isinstance(data.get("phase_number"), int):
        print(
            f"[Alfred Dev] Предупреждение: 'phase_number' не целое число в '{state_path}'. Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None

    command = data["command"]
    if command not in FLOWS:
        print(
            f"[Alfred Dev] Предупреждение: 'comando' не соответствует известному процессу в '{state_path}'. "
            f"Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None

    phase_index = data["phase_number"]
    if phase_index < 0:
        print(
            f"[Alfred Dev] Предупреждение: 'phase_number' не может быть отрицательным в '{state_path}'. "
            f"Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None

    phases = FLOWS[command]["phases"]
    phase_name = data["current_phase"]
    if phase_name == "completed":
        if phase_index != len(phases):
            print(
                f"[Alfred Dev] Предупреждение: противоречивое завершённое состояние в '{state_path}' "
                f"(phase_number={phase_index}, ожидалось={len(phases)}). Файл будет проигнорирован.",
                file=sys.stderr,
            )
            return None
        return data

    if phase_index >= len(phases):
        print(
            f"[Alfred Dev] Предупреждение: 'phase_number' вне диапазона в '{state_path}'. "
            f"Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None

    expected_phase_name = phases[phase_index]["name"]
    if phase_name != expected_phase_name:
        print(
            f"[Alfred Dev] Предупреждение: current_phase и phase_number не совпадают в '{state_path}' "
            f"('{phase_name}' != '{expected_phase_name}'). Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None

    return data


# --- Iterative loop (v0.4.0) ------------------------------------------------
# Lets agents iterate inside a phase until the gate passes or the
# iteration limit is reached. This enables TDD cycles, repeated QA
# passes and other iterative patterns.

# Maximum internal iterations per phase before escalating to the user.
MAX_PHASE_ITERATIONS = 5


def should_retry_phase(
    session: Dict[str, Any],
    result: str = "",
    security_ok: bool = True,
    tests_ok: bool = True,
) -> Dict[str, Any]:
    """Decide if the current phase must retry or escalate to the user.

    Evaluates the gate of the current phase. If it fails, checks if
    iterations remain. If they do, increments the counter and returns
    retry instructions. If none remain, returns instructions to escalate
    to the user.

    The iteration counter is stored in ``session["phase_iterations"]``.

    Args:
        session: current session state.
        result: reported result for the gate.
        security_ok: True if the security audit passed.
        tests_ok: True if the tests pass.

    Returns:
        Dict with:
        - ``"action"``: ``"advance"`` (gate passed), ``"retry"``
          or ``"escalate"`` (escalate to the user).
        - ``"reason"``: reason for the decision.
        - ``"iteration"``: current iteration number.
        - ``"max_iterations"``: allowed maximum.
    """
    # Defensive check: if the session is complete or the index is out of
    # range, a retry makes no sense.
    if session.get("current_phase") == "completed":
        return {
            "action": "advance",
            "reason": "Сессия завершена. Проверять gate не нужно.",
            "iteration": 0,
            "max_iterations": 0,
        }

    _, phase_error = _resolve_current_phase(session)
    if phase_error:
        iteration = session.get("phase_iterations", 0)
        max_iter = session.get("max_phase_iterations", MAX_PHASE_ITERATIONS)
        return {
            "action": "escalate",
            "reason": f"Недопустимое состояние сессии: {phase_error}",
            "iteration": iteration,
            "max_iterations": max_iter,
        }

    gate_result = check_gate(
        session,
        result=result,
        security_ok=security_ok,
        tests_ok=tests_ok,
    )

    iteration = session.get("phase_iterations", 0)
    max_iter = session.get("max_phase_iterations", MAX_PHASE_ITERATIONS)

    if gate_result["passed"]:
        return {
            "action": "advance",
            "reason": "Gate пройден. Можно переходить к следующей фазе.",
            "iteration": iteration,
            "max_iterations": max_iter,
        }

    if iteration < max_iter:
        # Increment the counter
        session["phase_iterations"] = iteration + 1
        session["updated_at"] = datetime.now(timezone.utc).isoformat()

        return {
            "action": "retry",
            "reason": (
                f"Gate не пройден: {gate_result['reason']} "
                f"Итерация {iteration + 1}/{max_iter}. "
                f"Исправь проблемы и попробуй снова."
            ),
            "iteration": iteration + 1,
            "max_iterations": max_iter,
        }

    return {
        "action": "escalate",
        "reason": (
            f"Исчерпано {max_iter} итераций, gate не пройден: "
            f"{gate_result['reason']} "
            f"Нужно вмешательство пользователя."
        ),
        "iteration": iteration,
        "max_iterations": max_iter,
    }


def reset_phase_iterations(session: Dict[str, Any]) -> None:
    """Reset the iteration counter of the current phase.

    Called automatically when the flow advances to a new phase so that
    the counter starts at 0.

    Args:
        session: session state to modify in place.
    """
    session["phase_iterations"] = 0


# --- Autopilot mode (v0.4.0) ------------------------------------------------
# Runs a full flow without human interruption. "user" gates are
# approved automatically. Automatic and security gates are evaluated
# as usual.

def is_autopilot_gate_passable(
    session: Dict[str, Any],
    security_ok: bool = True,
    tests_ok: bool = True,
) -> Dict[str, Any]:
    """Evaluate if a gate can pass in autopilot mode.

    In autopilot, "user" gates are approved automatically.
    "automatic" and "security" gates are evaluated with the given
    parameters.

    Args:
        session: session state.
        security_ok: result of the security audit.
        tests_ok: result of the tests.

    Returns:
        Dict with ``"passed"`` (bool) and ``"reason"`` (str).
    """
    command = session["command"]
    if command not in FLOWS:
        return {"passed": False, "reason": f"Процесс '{command}' не определён."}

    # Session complete: no gate to evaluate.
    if session.get("current_phase") == "completed":
        return {"passed": True, "reason": "Сессия завершена (autopilot)."}

    phase, phase_error = _resolve_current_phase(session)
    if phase is None:
        return {"passed": False, "reason": phase_error}

    gate_type = phase["gate_type"]

    if phase.get("autopilot_force_user_confirmation"):
        return {
            "passed": False,
            "reason": (
                "Фаза требует явного подтверждения пользователя даже в autopilot."
            ),
        }

    # In autopilot, user gates are approved automatically
    if gate_type == GATE_USER:
        return {"passed": True, "reason": "Автоматическое одобрение (autopilot)."}

    # The rest is evaluated as usual with result "approved"
    return check_gate(
        session,
        result="approved",
        security_ok=security_ok,
        tests_ok=tests_ok,
    )


def run_flow_autopilot(
    command: str,
    description: str,
    session_team: Optional[Dict[str, Any]] = None,
    project_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a flow session in autopilot mode.

    Same as ``run_flow()``, but marks the session with ``autopilot=True``
    so that the stop hook and the gates know they must act autonomously.

    Args:
        command: flow identifier.
        description: task description.
        session_team: optional team composition.
        project_dir: project path used to resolve the stack and the
            persisted configuration.

    Returns:
        Session state with ``autopilot=True``.

    Raises:
        ValueError: if the command does not match a defined flow.
    """
    session = run_flow(
        command,
        description,
        session_team=session_team,
        project_dir=project_dir,
    )
    session["autopilot"] = True
    session["phase_iterations"] = 0
    session["max_phase_iterations"] = MAX_PHASE_ITERATIONS
    return session
