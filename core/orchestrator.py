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
    type set in each phase: "usuario" gates require explicit approval;
    "automatico" gates check objective metrics such as green tests or
    a passing pipeline; combined gates (for example
    "automatico+seguridad") require both conditions.

Iterative loop (v0.4.0):
    Inside each phase, agents can iterate until the deliverables are
    complete or the iteration limit is reached. The loop stays inside
    the phase: the flow does not advance until the gate passes. This
    allows TDD cycles (red-green-refactor) and repeated QA passes
    without manual intervention.

Autopilot mode (v0.4.0):
    When ``autopilot=True``, the flow runs through all phases and does
    not ask the user for approval at "usuario" gates. Automatic and
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

GATE_USUARIO = "usuario"
GATE_AUTOMATICO = "automatico"
GATE_LIBRE = "libre"
GATE_USUARIO_SEGURIDAD = "usuario+seguridad"
GATE_AUTOMATICO_SEGURIDAD = "automatico+seguridad"

_KNOWN_GATE_TYPES = {
    GATE_LIBRE, GATE_USUARIO, GATE_AUTOMATICO,
    GATE_USUARIO_SEGURIDAD, GATE_AUTOMATICO_SEGURIDAD,
}

# --- Known optional agents ---------------------------------------------------
# Canonical list of the plugin's optional agents. Used to validate the
# structure of the session team in dynamic composition.

_KNOWN_OPTIONAL_AGENTS = frozenset(get_optional_agent_names())
_KNOWN_EQUIPO_SESSION_SOURCES = frozenset({
    "composicion_dinamica",
    "config_persistida",
})

# --- Flow definitions --------------------------------------------------------
# Each flow describes a sequence of phases that the orchestrator runs.
# The agents listed in each phase are responsible for running it.

FLOWS: Dict[str, Dict[str, Any]] = {
        "feature": {
        "nombre": "feature",
        "fases": [
            {
                "nombre": "producto",
                "agentes": ["product-owner"],
                "paralelo": False,
                "gate": "gate_producto",
                "gate_tipo": GATE_USUARIO,
                "descripcion": (
                    "Анализ требований и определение функционального "
                    "объёма новой feature."
                ),
            },
            {
                "nombre": "estilo_visual",
                "agentes": ["designer"],
                "paralelo": False,
                "gate": "gate_estilo",
                "gate_tipo": GATE_USUARIO,
                "condicion": "tiene_frontend",
                "descripcion": (
                    "Определение направления визуального стиля "
                    "продукта на основе трёх сопоставимых предложений."
                ),
            },
            {
                "nombre": "arquitectura",
                "agentes": ["architect", "security-officer"],
                "paralelo": True,
                "gate": "gate_arquitectura",
                "gate_tipo": GATE_USUARIO_SEGURIDAD,
                "descripcion": (
                    "Техническое проектирование, выбор паттернов и проверка "
                    "архитектурного решения с threat model."
                ),
            },
            {
                "nombre": "desarrollo",
                "agentes": ["senior-dev"],
                "paralelo": False,
                "gate": "gate_desarrollo",
                "gate_tipo": GATE_AUTOMATICO,
                "descripcion": (
                    "Реализация кода по строгому TDD "
                    "с циклами red-green-refactor."
                ),
            },
            {
                "nombre": "calidad",
                "agentes": ["qa-engineer", "security-officer"],
                "paralelo": True,
                "gate": "gate_calidad",
                "gate_tipo": GATE_AUTOMATICO_SEGURIDAD,
                "descripcion": (
                    "Проверка качества, запуск тестов и "
                    "аудит безопасности параллельно."
                ),
            },
            {
                "nombre": "documentacion",
                "agentes": ["tech-writer"],
                "paralelo": False,
                "gate": "gate_documentacion",
                "gate_tipo": GATE_LIBRE,
                "descripcion": (
                    "Создание технической и пользовательской "
                    "документации для сообщества."
                ),
            },
            {
                "nombre": "entrega",
                "agentes": ["devops-engineer", "security-officer"],
                "paralelo": False,
                "gate": "gate_entrega",
                "gate_tipo": GATE_USUARIO_SEGURIDAD,
                "descripcion": (
                    "Подготовка поставки, changelog и "
                    "финальная проверка перед merge."
                ),
            },
        ],
    },
    "fix": {
        "nombre": "fix",
        "fases": [
            {
                "nombre": "diagnostico",
                "agentes": ["senior-dev"],
                "paralelo": False,
                "gate": "gate_diagnostico",
                "gate_tipo": GATE_USUARIO,
                "descripcion": (
                    "Поиск первопричины бага "
                    "через анализ логов, трассировок и воспроизведение."
                ),
            },
            {
                "nombre": "correccion",
                "agentes": ["senior-dev"],
                "paralelo": False,
                "gate": "gate_correccion",
                "gate_tipo": GATE_AUTOMATICO,
                "descripcion": (
                    "Применение fix с регрессионным тестом, "
                    "который доказывает, что баг устранён."
                ),
            },
            {
                "nombre": "validacion",
                "agentes": ["qa-engineer", "security-officer"],
                "paralelo": True,
                "gate": "gate_validacion",
                "gate_tipo": GATE_AUTOMATICO_SEGURIDAD,
                "descripcion": (
                    "Полная проверка: регрессионные тесты, "
                    "существующий набор тестов и проверка безопасности."
                ),
            },
        ],
    },
    "quick": {
        "nombre": "quick",
        "fases": [
            {
                "nombre": "ejecucion_acotada",
                "agentes": ["senior-dev"],
                "paralelo": False,
                "gate": "gate_ejecucion_acotada",
                "gate_tipo": GATE_AUTOMATICO,
                "descripcion": (
                    "Ограниченная реализация для небольших, "
                    "локальных изменений с низким риском и автоматической проверкой."
                ),
            },
            {
                "nombre": "validacion_rapida",
                "agentes": ["qa-engineer", "security-officer"],
                "paralelo": True,
                "gate": "gate_validacion_rapida",
                "gate_tipo": GATE_AUTOMATICO_SEGURIDAD,
                "descripcion": (
                    "Быстрая проверка изменения на затронутой области: "
                    "локальная регрессия, тесты и проверка безопасности."
                ),
            },
        ],
    },
    "spike": {
        "nombre": "spike",
        "fases": [
            {
                "nombre": "exploracion",
                "agentes": ["architect", "senior-dev"],
                "paralelo": True,
                "gate": "gate_exploracion",
                "gate_tipo": GATE_LIBRE,
                "descripcion": (
                    "Исследование: proof of concept, "
                    "бенчмарки и оценка альтернатив."
                ),
            },
            {
                "nombre": "conclusiones",
                "agentes": ["architect"],
                "paralelo": False,
                "gate": "gate_conclusiones",
                "gate_tipo": GATE_USUARIO,
                "descripcion": (
                    "Сведение находок в отчёт "
                    "с практическими рекомендациями."
                ),
            },
        ],
    },
    "ship": {
        "nombre": "ship",
        "fases": [
            {
                "nombre": "auditoria_final",
                "agentes": ["qa-engineer", "security-officer"],
                "paralelo": True,
                "gate": "gate_auditoria_final",
                "gate_tipo": GATE_AUTOMATICO_SEGURIDAD,
                "descripcion": (
                    "Полный аудит качества и безопасности "
                    "перед релизом."
                ),
            },
            {
                "nombre": "documentacion",
                "agentes": ["tech-writer"],
                "paralelo": False,
                "gate": "gate_documentacion_ship",
                "gate_tipo": GATE_LIBRE,
                "descripcion": (
                    "Обновление документации релиза, "
                    "changelog и руководств по миграции."
                ),
            },
            {
                "nombre": "empaquetado",
                "agentes": ["devops-engineer", "security-officer"],
                "paralelo": False,
                "gate": "gate_empaquetado",
                "gate_tipo": GATE_AUTOMATICO_SEGURIDAD,
                "descripcion": (
                    "Сборка артефакта релиза, "
                    "семантическое версионирование и тегирование."
                ),
            },
            {
                "nombre": "despliegue",
                "agentes": ["devops-engineer"],
                "paralelo": False,
                "gate": "gate_despliegue",
                "gate_tipo": GATE_USUARIO_SEGURIDAD,
                "autopilot_force_user_confirmation": True,
                "descripcion": (
                    "Развёртывание в production с проверкой "
                    "после deploy и подготовленным rollback."
                ),
            },
        ],
    },
    "audit": {
        "nombre": "audit",
        "fases": [
            {
                "nombre": "auditoria_paralela",
                "agentes": [
                    "qa-engineer",
                    "security-officer",
                    "architect",
                    "tech-writer",
                ],
                "paralelo": True,
                "gate": "gate_auditoria",
                "gate_tipo": GATE_AUTOMATICO_SEGURIDAD,
                "descripcion": (
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
        # "tiene_frontend" calls config_loader.has_frontend(stack) to decide
        # if the estilo_visual phase must run. The import is lazy to prevent
        # circular imports between orchestrator and config_loader.
        _PHASE_CONDITIONS = {
            "tiene_frontend": has_frontend,
        }
    return _PHASE_CONDITIONS


def _advance_skipping_phases(
    session: Dict[str, Any],
    fases: List[Dict[str, Any]],
    siguiente: int,
    conditions: Dict[str, Any],
) -> int:
    """Advance the index and skip phases whose condition is not met.

    Records each skipped phase in ``session["fases_completadas"]`` with
    result ``"saltada"``. Stops at the first runnable phase (no condition
    or condition met) or when no stack is available to evaluate the
    condition.

    Args:
        session: session state (mutated to record skipped phases).
        fases: list of flow phases.
        siguiente: start index for the search.
        conditions: map from condition name to evaluator function.

    Returns:
        Index of the next runnable phase.
    """
    stack = session.get("stack")
    while siguiente < len(fases):
        fase_siguiente = fases[siguiente]
        condicion = fase_siguiente.get("condicion")
        if not condicion or condicion not in conditions:
            break
        if stack is None:
            # Without a stack the condition cannot be evaluated: run the phase
            break
        if conditions[condicion](stack):
            break
        # Condition not met: record the skipped phase and continue
        session["fases_completadas"].append({
            "nombre": fase_siguiente["nombre"],
            "resultado": "saltada",
            "artefactos": [],
            "completada_en": datetime.now(timezone.utc).isoformat(),
            "iteraciones": 0,
        })
        siguiente += 1
    return siguiente


def get_effective_agents(
    phase_name: str,
    active_optionals: Optional[Dict[str, bool]] = None,
) -> Dict[str, List[str]]:
    """Compute the agents of a phase, including active optional agents.

    Merges the core agents defined in FLOWS with the active optional agents
    that integrate with that phase. The result separates parallel and
    sequential agents so that commands know how to launch them.

    Args:
        phase_name: phase name (for example "arquitectura", "calidad").
        active_optionals: dict of active optional agents.
            Key = agent name, value = True if active.
            If None, no optional agents are added.

    Returns:
        Dict with two keys:
        - "paralelo": optional agents that run in parallel with the
          core agents.
        - "secuencial": optional agents that run after the core agents.

    Example:
        >>> get_effective_agents("calidad", {"ux-reviewer": True, "performance-engineer": True})
        {"paralelo": ["ux-reviewer", "performance-engineer"], "secuencial": []}
    """
    if active_optionals is None:
        return {"paralelo": [], "secuencial": []}

    paralelo: List[str] = []
    secuencial: List[str] = []

    for agent_name, config in OPTIONAL_INTEGRATIONS.items():
        if not active_optionals.get(agent_name, False):
            continue
        if phase_name not in config.get("fases", []):
            continue

        posicion = config.get("posicion", "paralelo")
        if posicion == "secuencial":
            secuencial.append(agent_name)
        elif posicion == "paralelo":
            paralelo.append(agent_name)

    return {"paralelo": paralelo, "secuencial": secuencial}


def _resolve_current_phase(session: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Resolve and validate the current phase of a session."""
    comando = session.get("comando")
    if comando not in FLOWS:
        return None, f"Процесс '{comando}' не определён в FLOWS."

    fase_actual = session.get("fase_actual")
    if fase_actual == "completado":
        return None, "Сессия завершена. Ожидающего gate нет."

    fase_numero = session.get("fase_numero")
    if not isinstance(fase_numero, int):
        return None, "Индекс фазы не является допустимым целым числом."
    if fase_numero < 0:
        return None, f"Индекс фазы не может быть отрицательным: {fase_numero}."

    fases = FLOWS[comando]["fases"]
    if fase_numero >= len(fases):
        return None, (
            f"Индекс фазы {fase_numero} вне диапазона для процесса "
            f"'{comando}' (фаз: {len(fases)})."
        )

    fase = fases[fase_numero]
    expected_name = fase["nombre"]
    if fase_actual != expected_name:
        return None, (
            "Состояние сессии противоречиво: "
            f"fase_actual='{fase_actual}' не совпадает с fase_numero={fase_numero} "
            f"('{expected_name}')."
        )

    return fase, ""


def _validate_equipo_sesion(equipo_sesion: Any) -> bool:
    """Validate the session team structure built by dynamic composition.

    Checks that the dict has the expected keys at each level and that the
    values have the correct type. On failure, prints a descriptive warning
    to stderr and returns False. This lets the orchestrator discard
    malformed teams without breaking the flow.

    Validation rules per level:

        - **Top level**: requires exactly the keys ``"opcionales_activos"``,
          ``"infra"`` and ``"fuente"``. Extra or missing keys cause rejection.
        - **``opcionales_activos``**: requires at least the keys of
          ``_KNOWN_OPTIONAL_AGENTS``. Accepts extra keys with a warning to
          stderr (tolerance for future extensions) but does not validate
          them. All values must be ``bool``.
        - **``infra``**: requires exactly ``"memoria"``, of type ``bool``.
        - **``fuente``**: must be one of the known runtime sources
          (currently ``"composicion_dinamica"`` or ``"config_persistida"``).

    Args:
        equipo_sesion: value to validate. Expected: a dict with the keys
            ``"opcionales_activos"``, ``"infra"`` and ``"fuente"``.

    Returns:
        True if the structure is valid, False otherwise.

    Example:
        >>> _validate_equipo_sesion({"opcionales_activos": {...}, "infra": {...}, "fuente": "composicion_dinamica"})
        True
    """
    # --- 1. Must be a dict ---
    if not isinstance(equipo_sesion, dict):
        print(
            "[Alfred Dev] Предупреждение: equipo_sesion не является словарём.",
            file=sys.stderr,
        )
        return False

    # --- 2. Top-level keys ---
    expected_top_keys = {"opcionales_activos", "infra", "fuente"}
    if set(equipo_sesion.keys()) != expected_top_keys:
        print(
            f"[Alfred Dev] Предупреждение: в equipo_sesion неожиданные ключи. "
            f"Ожидались: {sorted(expected_top_keys)}, "
            f"получены: {sorted(equipo_sesion.keys())}.",
            file=sys.stderr,
        )
        return False

    # --- 3. opcionales_activos: dict with at least the known keys, bool values ---
    opcionales = equipo_sesion["opcionales_activos"]
    if not isinstance(opcionales, dict):
        print(
            "[Alfred Dev] Предупреждение: opcionales_activos не является словарём.",
            file=sys.stderr,
        )
        return False

    # Old states can use legacy names (for example "lucius").
    opcionales = normalize_optional_agent_flags(opcionales)
    equipo_sesion["opcionales_activos"] = opcionales

    # The known keys must be present. Extra keys are accepted with a
    # warning (tolerance for future extensions).
    missing = _KNOWN_OPTIONAL_AGENTS - set(opcionales.keys())
    if missing:
        print(
            f"[Alfred Dev] Предупреждение: в opcionales_activos нет "
            f"обязательных агентов: {sorted(missing)}.",
            file=sys.stderr,
        )
        return False

    extra = set(opcionales.keys()) - _KNOWN_OPTIONAL_AGENTS
    if extra:
        print(
            f"[Alfred Dev] Предупреждение: в opcionales_activos есть "
            f"неизвестные агенты, они будут проигнорированы: {sorted(extra)}.",
            file=sys.stderr,
        )

    for agent_name, value in opcionales.items():
        if not isinstance(value, bool):
            print(
                f"[Alfred Dev] Предупреждение: opcionales_activos['{agent_name}'] не bool "
                f"(тип: {type(value).__name__}, значение: {value!r}).",
                file=sys.stderr,
            )
            return False

    # --- 4. infra: dict with exactly "memoria", bool value ---
    infra = equipo_sesion["infra"]
    if not isinstance(infra, dict):
        print(
            "[Alfred Dev] Предупреждение: infra не является словарём.",
            file=sys.stderr,
        )
        return False

    expected_infra_keys = {"memoria"}
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

    # --- 5. fuente: must be a known runtime source ---
    if equipo_sesion["fuente"] not in _KNOWN_EQUIPO_SESSION_SOURCES:
        print(
            f"[Alfred Dev] Предупреждение: fuente должен быть одним из "
            f"{sorted(_KNOWN_EQUIPO_SESSION_SOURCES)}, "
            f"получено: {equipo_sesion['fuente']!r}.",
            file=sys.stderr,
        )
        return False

    return True


def _load_persisted_equipo_sesion(
    project_dir: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Load the runtime team derived from the persisted configuration."""
    try:
        from core.config_loader import build_project_equipo_sesion  # noqa: PLC0415

        equipo_sesion = build_project_equipo_sesion(project_dir)
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

    if equipo_sesion is None:
        return None, None

    if not _validate_equipo_sesion(equipo_sesion):
        print(
            "[Alfred Dev] Предупреждение: команда из сохранённой "
            "конфигурации не прошла проверку и будет проигнорирована.",
            file=sys.stderr,
        )
        return None, (
            "Сохранённая конфигурация проекта дала недопустимую команду "
            "сессии и была отброшена."
        )

    return equipo_sesion, None


def run_flow(
    command: str,
    description: str,
    equipo_sesion: Optional[Dict[str, Any]] = None,
    project_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a flow session with an optional dynamically composed team.

    Combines the standard session creation with the injection of the
    session team built by dynamic composition. If the given team fails
    validation, it is discarded with a warning to stderr, and the reason
    is stored in ``session["equipo_sesion_error"]`` so that downstream
    consumers can inform the user.

    This is the main entry point to start a flow when you know which
    optional agents must take part.

    Args:
        command: flow identifier (feature, fix, quick, spike, ship, audit).
        description: natural language description of the task.
        equipo_sesion: dict with the team composition built by the dynamic
            composition module. If None, the session has no team. If
            invalid, it is discarded with a warning and the reason is
            stored in "equipo_sesion_error".
        project_dir: path of the project used to detect the stack and load
            the persisted configuration. Defaults to the current working
            directory.

    Returns:
        Dict with the session state, including the keys:
        - "equipo_sesion" (valid dict or None).
        - "equipo_sesion_error" (str or None): reason for the discard.

    Raises:
        ValueError: if the command does not match a defined flow.

    Example:
        >>> session = run_flow("feature", "Login con OAuth", equipo_sesion={...})
        >>> session["equipo_sesion"]["opcionales_activos"]["github-manager"]
        True
    """
    # --- 1. Validate that the command exists ---
    if command not in FLOWS:
        raise ValueError(
            f"Процесс '{command}' не распознан. "
            f"Доступные процессы: {', '.join(FLOWS.keys())}"
        )

    resolved_project_dir = os.path.abspath(project_dir or os.getcwd())

    # --- 2. Validate equipo_sesion if given ---
    equipo_error = None
    explicit_team_discarded = False
    if equipo_sesion is not None and not _validate_equipo_sesion(equipo_sesion):
        print(
            "[Alfred Dev] Ошибка: команда сессии не прошла проверку. "
            "Сессия будет создана без опциональных агентов. Проверь структуру "
            "словаря equipo_sesion.",
            file=sys.stderr,
        )
        equipo_error = (
            "Переданная команда сессии не прошла проверку "
            "и была отброшена."
        )
        equipo_sesion = None
        explicit_team_discarded = True

    if equipo_sesion is None:
        persisted_team, persisted_error = _load_persisted_equipo_sesion(resolved_project_dir)
        if persisted_team is not None:
            equipo_sesion = persisted_team
            if explicit_team_discarded:
                equipo_error = (
                    f"{equipo_error} Применена сохранённая конфигурация "
                    "опциональных агентов проекта."
                )
        elif persisted_error:
            if explicit_team_discarded:
                equipo_error = f"{equipo_error} {persisted_error}"
            else:
                equipo_error = persisted_error

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

    # --- 5. Inject equipo_sesion and the diagnostic ---
    session["equipo_sesion"] = equipo_sesion
    session["equipo_sesion_error"] = equipo_error

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
            such as ``estilo_visual`` can be evaluated.

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
    primera_fase = flow["fases"][0]["nombre"]

    session = {
        "comando": command,
        "descripcion": description,
        "fase_actual": primera_fase,
        "fase_numero": 0,
        "fases_completadas": [],
        "artefactos": [],
        "creado_en": datetime.now(timezone.utc).isoformat(),
        "actualizado_en": datetime.now(timezone.utc).isoformat(),
    }
    if stack is not None:
        session["stack"] = stack
    return session


def check_gate(
    session: Dict[str, Any],
    resultado: str = "",
    security_ok: bool = True,
    tests_ok: bool = True,
) -> Dict[str, Any]:
    """
    Evaluate the gate of the current phase to decide if the flow can advance.

    The logic depends on the gate type defined in the phase:
    - "usuario": requires result "aprobado".
    - "automatico": requires result "aprobado" and green tests.
    - "usuario+seguridad": requires user approval and a passing security check.
    - "automatico+seguridad": requires tests, security and a passing result.
    - "libre": passes when the result is "aprobado".

    Args:
        session: current session state.
        resultado: reported result (usually "aprobado" or "rechazado").
        security_ok: True if the security audit passed.
        tests_ok: True if the tests pass.

    Returns:
        Dict with the keys "passed" (bool) and "reason" (str).
    """
    comando = session["comando"]
    if comando not in FLOWS:
        return {"passed": False, "reason": f"Процесс '{comando}' не определён в FLOWS."}

    # Session complete: no gate to evaluate.
    if session.get("fase_actual") == "completado":
        return {"passed": True, "reason": "Сессия завершена. Ожидающего gate нет."}

    fase, phase_error = _resolve_current_phase(session)
    if fase is None:
        return {"passed": False, "reason": phase_error}

    gate_tipo = fase["gate_tipo"]

    # Collect the conditions the gate must meet.
    # The check order sets which error is reported first.
    failures = []

    requires_tests = "automatico" in gate_tipo
    requires_security = "seguridad" in gate_tipo
    requires_approval = gate_tipo in (GATE_USUARIO, GATE_USUARIO_SEGURIDAD)
    is_known = gate_tipo in _KNOWN_GATE_TYPES

    if not is_known:
        return {"passed": False, "reason": f"Неизвестный тип gate: {gate_tipo}"}

    if requires_tests and not tests_ok:
        failures.append("Тесты не проходят.")
    if requires_security and not security_ok:
        failures.append("Аудит безопасности не пройден.")
    if resultado != "aprobado":
        if requires_approval:
            failures.append("Требуется одобрение пользователя.")
        else:
            failures.append("Результат неудовлетворительный.")

    passed = len(failures) == 0
    reason = failures[0] if failures else ""

    return {"passed": passed, "reason": reason}


def advance_phase(
    session: Dict[str, Any],
    resultado: str = "aprobado",
    artefactos: Optional[List[str]] = None,
    security_ok: bool = True,
    tests_ok: bool = True,
) -> Dict[str, Any]:
    """
    Try to advance the session to the next phase of the flow.

    First evaluates the gate of the current phase. If the gate passes,
    records the phase as complete and moves the pointer to the next one.
    If no phases remain, marks the session as "completado".

    Args:
        session: current session state.
        resultado: result to evaluate at the gate (default "aprobado").
        artefactos: optional list of artifacts produced in the phase.
        security_ok: True if the security audit passed.
        tests_ok: True if the tests pass.

    Returns:
        Dict with the updated session state.

    Raises:
        RuntimeError: if the gate of the current phase does not pass.
    """
    if artefactos is None:
        artefactos = []

    comando = session["comando"]
    if comando not in FLOWS:
        raise RuntimeError(f"Процесс '{comando}' не определён в FLOWS.")

    flow = FLOWS[comando]
    fases = flow["fases"]

    # If already complete, return without changes
    if session["fase_actual"] == "completado":
        return session

    # Evaluate the gate of the current phase with all parameters
    gate_result = check_gate(
        session, resultado=resultado, security_ok=security_ok, tests_ok=tests_ok
    )
    if not gate_result["passed"]:
        raise RuntimeError(
            f"Нельзя перейти дальше: {gate_result['reason']}"
        )

    # Record the completed phase. Keep the iteration counter so that
    # session reports can show how many cycles the phase needed.
    fase_completada = {
        "nombre": fases[session["fase_numero"]]["nombre"],
        "resultado": resultado,
        "artefactos": artefactos,
        "completada_en": datetime.now(timezone.utc).isoformat(),
        "iteraciones": session.get("iteraciones_fase", 0),
    }
    session["fases_completadas"].append(fase_completada)

    # Add the artifacts to the global session record
    session["artefactos"].extend(artefactos)

    # Move to the next index and skip phases whose condition is not met
    siguiente = _advance_skipping_phases(
        session, fases, session["fase_numero"] + 1, _get_phase_conditions()
    )

    if siguiente < len(fases):
        session["fase_numero"] = siguiente
        session["fase_actual"] = fases[siguiente]["nombre"]
    else:
        # No phases remain: the flow is complete
        session["fase_actual"] = "completado"
        session["fase_numero"] = siguiente

    # Reset the internal iteration counter for the new phase
    session["iteraciones_fase"] = 0

    session["actualizado_en"] = datetime.now(timezone.utc).isoformat()
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
_REQUIRED_STATE_KEYS = {"comando", "fase_actual", "fase_numero"}


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
    # in later comparisons (for example fase_numero >= len(fases))
    if not isinstance(data.get("comando"), str):
        print(
            f"[Alfred Dev] Предупреждение: 'comando' не строка в '{state_path}'. Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None
    if not isinstance(data.get("fase_actual"), str):
        print(
            f"[Alfred Dev] Предупреждение: 'fase_actual' не строка в '{state_path}'. Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None
    if not isinstance(data.get("fase_numero"), int):
        print(
            f"[Alfred Dev] Предупреждение: 'fase_numero' не целое число в '{state_path}'. Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None

    command = data["comando"]
    if command not in FLOWS:
        print(
            f"[Alfred Dev] Предупреждение: 'comando' не соответствует известному процессу в '{state_path}'. "
            f"Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None

    phase_index = data["fase_numero"]
    if phase_index < 0:
        print(
            f"[Alfred Dev] Предупреждение: 'fase_numero' не может быть отрицательным в '{state_path}'. "
            f"Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None

    fases = FLOWS[command]["fases"]
    phase_name = data["fase_actual"]
    if phase_name == "completado":
        if phase_index != len(fases):
            print(
                f"[Alfred Dev] Предупреждение: противоречивое завершённое состояние в '{state_path}' "
                f"(fase_numero={phase_index}, ожидалось={len(fases)}). Файл будет проигнорирован.",
                file=sys.stderr,
            )
            return None
        return data

    if phase_index >= len(fases):
        print(
            f"[Alfred Dev] Предупреждение: 'fase_numero' вне диапазона в '{state_path}'. "
            f"Файл будет проигнорирован.",
            file=sys.stderr,
        )
        return None

    expected_phase_name = fases[phase_index]["nombre"]
    if phase_name != expected_phase_name:
        print(
            f"[Alfred Dev] Предупреждение: fase_actual и fase_numero не совпадают в '{state_path}' "
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
    resultado: str = "",
    security_ok: bool = True,
    tests_ok: bool = True,
) -> Dict[str, Any]:
    """Decide if the current phase must retry or escalate to the user.

    Evaluates the gate of the current phase. If it fails, checks if
    iterations remain. If they do, increments the counter and returns
    retry instructions. If none remain, returns instructions to escalate
    to the user.

    The iteration counter is stored in ``session["iteraciones_fase"]``.

    Args:
        session: current session state.
        resultado: reported result for the gate.
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
    if session.get("fase_actual") == "completado":
        return {
            "action": "advance",
            "reason": "Сессия завершена. Проверять gate не нужно.",
            "iteration": 0,
            "max_iterations": 0,
        }

    _, phase_error = _resolve_current_phase(session)
    if phase_error:
        iteration = session.get("iteraciones_fase", 0)
        max_iter = session.get("max_iteraciones_fase", MAX_PHASE_ITERATIONS)
        return {
            "action": "escalate",
            "reason": f"Недопустимое состояние сессии: {phase_error}",
            "iteration": iteration,
            "max_iterations": max_iter,
        }

    gate_result = check_gate(
        session,
        resultado=resultado,
        security_ok=security_ok,
        tests_ok=tests_ok,
    )

    iteration = session.get("iteraciones_fase", 0)
    max_iter = session.get("max_iteraciones_fase", MAX_PHASE_ITERATIONS)

    if gate_result["passed"]:
        return {
            "action": "advance",
            "reason": "Gate пройден. Можно переходить к следующей фазе.",
            "iteration": iteration,
            "max_iterations": max_iter,
        }

    if iteration < max_iter:
        # Increment the counter
        session["iteraciones_fase"] = iteration + 1
        session["actualizado_en"] = datetime.now(timezone.utc).isoformat()

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
    session["iteraciones_fase"] = 0


# --- Autopilot mode (v0.4.0) ------------------------------------------------
# Runs a full flow without human interruption. "usuario" gates are
# approved automatically. Automatic and security gates are evaluated
# as usual.

def is_autopilot_gate_passable(
    session: Dict[str, Any],
    security_ok: bool = True,
    tests_ok: bool = True,
) -> Dict[str, Any]:
    """Evaluate if a gate can pass in autopilot mode.

    In autopilot, "usuario" gates are approved automatically.
    "automatico" and "seguridad" gates are evaluated with the given
    parameters.

    Args:
        session: session state.
        security_ok: result of the security audit.
        tests_ok: result of the tests.

    Returns:
        Dict with ``"passed"`` (bool) and ``"reason"`` (str).
    """
    comando = session["comando"]
    if comando not in FLOWS:
        return {"passed": False, "reason": f"Процесс '{comando}' не определён."}

    # Session complete: no gate to evaluate.
    if session.get("fase_actual") == "completado":
        return {"passed": True, "reason": "Сессия завершена (autopilot)."}

    fase, phase_error = _resolve_current_phase(session)
    if fase is None:
        return {"passed": False, "reason": phase_error}

    gate_tipo = fase["gate_tipo"]

    if fase.get("autopilot_force_user_confirmation"):
        return {
            "passed": False,
            "reason": (
                "Фаза требует явного подтверждения пользователя даже в autopilot."
            ),
        }

    # In autopilot, user gates are approved automatically
    if gate_tipo == GATE_USUARIO:
        return {"passed": True, "reason": "Автоматическое одобрение (autopilot)."}

    # The rest is evaluated as usual with result "aprobado"
    return check_gate(
        session,
        resultado="aprobado",
        security_ok=security_ok,
        tests_ok=tests_ok,
    )


def run_flow_autopilot(
    command: str,
    description: str,
    equipo_sesion: Optional[Dict[str, Any]] = None,
    project_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a flow session in autopilot mode.

    Same as ``run_flow()``, but marks the session with ``autopilot=True``
    so that the stop hook and the gates know they must act autonomously.

    Args:
        command: flow identifier.
        description: task description.
        equipo_sesion: optional team composition.
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
        equipo_sesion=equipo_sesion,
        project_dir=project_dir,
    )
    session["autopilot"] = True
    session["iteraciones_fase"] = 0
    session["max_iteraciones_fase"] = MAX_PHASE_ITERATIONS
    return session
