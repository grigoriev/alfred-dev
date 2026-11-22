#!/usr/bin/env python3
"""
Session report generator for Alfred Dev.

When a work session ends (Stop event), this module writes a markdown
report that summarizes the activity: flow state, completed phases,
generated artifacts, test evidence and the next operational step.

The report goes to ``docs/alfred-reports/`` and stays there as a
historical record. If persistent memory is active, the report is also
logged as an event in the DB.

Architecture:
    The report is built from modular sections. Each section is a
    function that takes the data and returns a markdown block. The main
    function ``generate_report()`` assembles them in order.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.optional_agents import (
    get_optional_integrations,
    normalize_optional_agent_flags,
    order_optional_agent_names,
)
from core.orchestrator import FLOWS


# --- Report format ---

_REPORT_DIR = "docs/alfred-reports"

_REPORT_TEMPLATE = """# Отчёт о сессии: {comando}

**Дата:** {fecha}
**Примерная длительность:** {duracion}
**Описание:** {descripcion}

---

{secciones}

---

*Создано автоматически Alfred Dev v{version}*
"""

_REPORT_TEMPLATE_INTERRUPTED = """# Сессия прервана: {comando}

**Дата:** {fecha}
**Примерная длительность:** {duracion}
**Описание:** {descripcion}

---

{secciones}

---

*Создано автоматически Alfred Dev v{version}*
"""

_OPTIONAL_INTEGRATIONS = get_optional_integrations()


# --- Report sections ---


def _single_line_text(value: Any, default: str = "") -> str:
    """Normalize free text to one readable line."""
    if value is None:
        return default
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or default


def _markdown_table_cell(value: Any, default: str = "-") -> str:
    """Escape free text for a Markdown table cell."""
    text = _single_line_text(value, default=default)
    return text.replace("|", r"\|")


def _markdown_inline_code(value: Any, default: str = "-") -> str:
    """Render text that is safe to use as inline code."""
    text = _single_line_text(value, default=default)
    text = text.replace("`", "'")
    return f"`{text}`"


def _truncate_text(value: Any, limit: int = 120, default: str = "") -> str:
    """Truncate free text and keep it on one line."""
    text = _single_line_text(value, default=default)
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)].rstrip() + "..."


def _session_team_source_label(session: Dict[str, Any]) -> str:
    """Return a human-readable label for the runtime team source."""
    equipo = session.get("equipo_sesion")
    if not isinstance(equipo, dict):
        return ""

    source = _single_line_text(equipo.get("fuente", ""))
    if source == "config_persistida":
        return "сохранённая конфигурация"
    if source == "composicion_dinamica":
        return "динамический состав"
    return ""


def _session_on_demand_optionals_for_flow(session: Dict[str, Any]) -> List[str]:
    """Return active optional agents that take part in no phase of the flow."""
    command = _single_line_text(session.get("comando", ""))
    flow = FLOWS.get(command, {})
    flow_phases = {
        _single_line_text(phase.get("nombre", ""))
        for phase in (flow.get("fases") or [])
        if _single_line_text(phase.get("nombre", ""))
    }

    equipo = session.get("equipo_sesion")
    if not isinstance(equipo, dict):
        return []
    opcionales = equipo.get("opcionales_activos", {})
    if not isinstance(opcionales, dict):
        return []

    activos = order_optional_agent_names(
        name for name, enabled in normalize_optional_agent_flags(opcionales).items() if enabled
    )
    on_demand: List[str] = []
    for agent_name in activos:
        integrated_phases = {
            _single_line_text(phase_name)
            for phase_name in _OPTIONAL_INTEGRATIONS.get(agent_name, {}).get("fases", [])
            if _single_line_text(phase_name)
        }
        if not flow_phases.intersection(integrated_phases):
            on_demand.append(agent_name)
    return on_demand


def _last_completed_at(session: Dict[str, Any]) -> str:
    """Get the timestamp of the last phase or session close."""
    completed = session.get("fases_completadas") or []
    if completed and isinstance(completed[-1], dict):
        completed_at = _single_line_text(completed[-1].get("completada_en", ""))
        if completed_at:
            return completed_at

    for key in ("actualizado_en", "creado_en"):
        value = _single_line_text(session.get(key, ""))
        if value:
            return value

    return ""


def _load_matching_session_uat(
    project_dir: Optional[str], session: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Load the UAT that belongs exactly to this completed session."""
    if not project_dir or session.get("fase_actual") != "completado":
        return None

    try:
        from core.continuity import load_uat  # noqa: PLC0415
    except Exception:
        return None

    uat = load_uat(project_dir)
    if not isinstance(uat, dict):
        return None

    command = _single_line_text(session.get("comando", "desconocido"), default="desconocido")
    target_id = f"session:{command}:{_last_completed_at(session)}"
    if uat.get("target_id") == target_id:
        return uat
    return None


def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    """Parse ISO dates leniently."""
    text = _single_line_text(value)
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _normalized_match_key(value: Any) -> str:
    """Normalize text for loose comparisons."""
    return _single_line_text(value).casefold()


def _open_memory_db(project_dir: Optional[str]):
    """Open the memory DB if it exists and is accessible."""
    if not project_dir:
        return None

    db_path = os.path.join(project_dir, ".claude", "alfred-memory.db")
    if not os.path.isfile(db_path):
        return None

    try:
        from core.memory import MemoryDB  # noqa: PLC0415
    except Exception:
        return None

    try:
        return MemoryDB(db_path)
    except Exception:
        return None


def _find_session_iteration(db: Any, session: Dict[str, Any], completed: bool) -> Optional[Dict[str, Any]]:
    """Find the memory iteration that best matches the session."""
    command_key = _normalized_match_key(session.get("comando", ""))
    description_key = _normalized_match_key(session.get("descripcion", ""))
    session_time = _parse_iso_datetime(
        _last_completed_at(session) if completed else session.get("actualizado_en") or session.get("creado_en")
    )
    desired_status = "completed" if completed and session.get("fase_actual") == "completado" else "active"

    best_match: Optional[Dict[str, Any]] = None
    best_score: Optional[Tuple[int, int, int, str, int]] = None

    for iteration in db.get_iterations(limit=100):
        if _normalized_match_key(iteration.get("command", "")) != command_key:
            continue

        iteration_description = _normalized_match_key(iteration.get("description", ""))
        if description_key:
            if iteration_description == description_key:
                description_score = 2
            elif description_key in iteration_description or iteration_description in description_key:
                description_score = 1
            else:
                continue
        else:
            description_score = 0

        status = _single_line_text(iteration.get("status", ""), default="desconocido")
        if status == desired_status:
            status_score = 3
        elif desired_status == "completed" and status == "abandoned":
            status_score = 2
        elif desired_status == "completed" and status == "active":
            status_score = 1
        else:
            status_score = 0

        iteration_time = _parse_iso_datetime(
            iteration.get("completed_at") or iteration.get("started_at")
        )
        if session_time and iteration_time:
            diff = abs(int((iteration_time - session_time).total_seconds()))
            if diff <= 300:
                time_score = 3
            elif diff <= 3600:
                time_score = 2
            else:
                time_score = 1
        elif iteration_time:
            time_score = 1
        else:
            time_score = 0

        candidate_score = (
            description_score,
            status_score,
            time_score,
            _single_line_text(iteration.get("completed_at") or iteration.get("started_at") or ""),
            int(iteration.get("id", 0) or 0),
        )
        if best_score is None or candidate_score > best_score:
            best_score = candidate_score
            best_match = iteration

    return best_match


def _session_decisions_snapshot(
    project_dir: Optional[str],
    session: Dict[str, Any],
    completed: bool,
    limit: int = 5,
) -> Dict[str, Any]:
    """Get the decisions linked to the iteration of this session."""
    snapshot = {
        "available": False,
        "iteration_id": None,
        "total": 0,
        "items": [],
    }
    db = _open_memory_db(project_dir)
    if db is None:
        return snapshot

    try:
        iteration = _find_session_iteration(db, session, completed)
        if not iteration:
            return snapshot

        iteration_id = int(iteration["id"])
        total = sum(1 for _ in db.iter_decisions(iteration_id=iteration_id, batch_size=200))
        items = db.get_decisions(iteration_id=iteration_id, limit=limit, status="active")
        if not items and total:
            items = db.get_decisions(iteration_id=iteration_id, limit=limit)

        snapshot.update(
            {
                "available": True,
                "iteration_id": iteration_id,
                "total": total,
                "items": items,
            }
        )
        return snapshot
    finally:
        db.close()


def _test_summary(evidence: Optional[Dict[str, Any]]) -> str:
    """Summarize the test evidence in one readable line."""
    if evidence is None:
        return "нет данных о прогонах"
    if not evidence.get("has_evidence", False):
        return "тесты не запускались"

    records = evidence.get("records", []) or []
    passed = sum(1 for record in records if record.get("result") == "pass")
    failed = sum(1 for record in records if record.get("result") == "fail")
    unknown = max(len(records) - passed - failed, 0)

    parts = [f"прогонов: {len(records)}"]
    if passed:
        parts.append(f"OK: {passed}")
    if failed:
        parts.append(f"с ошибкой: {failed}")
    if unknown:
        parts.append(f"без результата: {unknown}")
    return ", ".join(parts)


def _verification_status(
    project_dir: Optional[str], session: Dict[str, Any], completed: bool
) -> Dict[str, str]:
    """Summarize the verify/UAT state and the recommended next step."""
    if not completed or session.get("fase_actual") != "completado":
        current_phase = _single_line_text(
            session.get("fase_actual", "неизвестна"), default="неизвестна"
        )
        return {
            "label": "пока не применяется",
            "detail": f"Процесс ещё активен в фазе '{current_phase}'.",
            "next_command": "/alfred-dev:retomar",
            "next_reason": "Сессия ещё не закрыта: лучше продолжить её с того места, где она остановилась.",
        }

    uat = _load_matching_session_uat(project_dir, session)
    if not uat:
        return {
            "label": "в ожидании",
            "detail": "Процесс отмечен как завершённый, но ручная проверка/UAT ещё не зарегистрирована.",
            "next_command": "/alfred-dev:uat",
            "next_reason": "Нужно проверить итоговый результат, прежде чем считать процесс действительно закрытым.",
        }

    status = _single_line_text(uat.get("status", ""), default="desconocido")
    updated_at = _single_line_text(uat.get("updated_at", ""))
    notes = _single_line_text(uat.get("notes", ""))

    if status == "approved":
        detail = "UAT одобрена."
        if updated_at:
            detail = f"{detail} Зарегистрирована {updated_at}."
        return {
            "label": "одобрена",
            "detail": detail,
            "next_command": "/alfred",
            "next_reason": "Итоговая проверка уже закрыта: переходи к следующей задаче или готовь release.",
        }

    if status == "rejected":
        detail = "UAT отклонена."
        if notes:
            detail = f"{detail} {notes}"
        elif updated_at:
            detail = f"{detail} Зарегистрирована {updated_at}."
        return {
            "label": "отклонена",
            "detail": detail,
            "next_command": "/alfred",
            "next_reason": "Нужно исправить изменение и снова пройти ручную проверку.",
        }

    detail = "Ручная проверка/UAT в ожидании."
    if updated_at:
        detail = f"{detail} Последнее обновление: {updated_at}."
    return {
        "label": "в ожидании",
        "detail": detail,
        "next_command": "/alfred-dev:uat",
        "next_reason": "Итоговая проверка ещё открыта, её нужно закрыть явно.",
    }


def _report_next_step_payload(
    project_dir: Optional[str], session: Dict[str, Any], completed: bool
) -> Dict[str, str]:
    """Return structured next-step guidance for the report."""
    verification = _verification_status(project_dir, session, completed)
    next_command = _single_line_text(
        verification.get("next_command", "/alfred"),
        default="/alfred",
    )

    if next_command == "/alfred-dev:retomar":
        return {
            "focus": "Продолжить текущую сессию",
            "source_label": "активная сессия",
            "source": "state",
            "command": next_command,
            "directive": "Продолжи сессию с места остановки и доведи открытую фазу, прежде чем начинать другой процесс.",
            "reason": verification.get("next_reason", "Сессия ещё не закрыта."),
        }

    if next_command == "/alfred-dev:uat":
        return {
            "focus": "Закрыть ожидающую проверку",
            "source_label": "проверка/UAT",
            "source": "verify",
            "command": next_command,
            "directive": "Зарегистрируй или заверши ручную проверку/UAT результата, прежде чем браться за другую задачу.",
            "reason": verification.get("next_reason", "Нужно проверить итоговый результат."),
        }

    return {
        "focus": "Продолжить после закрытия процесса",
        "source_label": "закрытие сессии",
        "source": "report",
        "command": next_command,
        "directive": "Используй Alfred, чтобы выбрать следующий цикл или закрыть поставку, опираясь на уже собранный контекст.",
        "reason": verification.get(
            "next_reason",
            "Процесс уже закрыт, пора выбрать следующий шаг.",
        ),
    }


def _section_summary(
    session: Dict[str, Any],
    evidence: Optional[Dict[str, Any]],
    decisions: Dict[str, Any],
    project_dir: Optional[str],
    completed: bool,
) -> str:
    """Build a short, actionable executive summary."""
    phases = [
        phase for phase in (session.get("fases_completadas") or []) if isinstance(phase, dict)
    ]
    skipped = sum(1 for phase in phases if _single_line_text(phase.get("resultado", "")) == "saltada")
    retried = sum(1 for phase in phases if int(phase.get("iteraciones", 0) or 0) > 0)
    artifacts = [item for item in (session.get("artefactos") or []) if _single_line_text(item)]
    verification = _verification_status(project_dir, session, completed)

    if completed and session.get("fase_actual") == "completado":
        state_label = "процесс завершён по состоянию"
    else:
        current_phase = _single_line_text(
            session.get("fase_actual", "неизвестна"), default="неизвестна"
        )
        state_label = f"сессия прервана в фазе '{current_phase}'"

    lines = ["## Краткое резюме\n"]
    lines.append(f"- Общее состояние: {state_label}.")
    lines.append(
        f"- Зарегистрировано фаз: {len(phases)}"
        f" (пропущено: {skipped}, с повторами: {retried})."
    )
    lines.append(f"- Общих артефактов: {len(artifacts)}.")
    lines.append(f"- Тесты: {_test_summary(evidence)}.")
    if decisions.get("available"):
        lines.append(f"- Решений в памяти, связанных с сессией: {int(decisions.get('total', 0))}.")
    lines.append(f"- Проверка/UAT: {verification['label']}. {verification['detail']}")

    equipo = session.get("equipo_sesion") or {}
    opcionales = equipo.get("opcionales_activos", {}) if isinstance(equipo, dict) else {}
    activos = order_optional_agent_names(
        name for name, enabled in normalize_optional_agent_flags(opcionales).items() if enabled
    )
    team_source = _session_team_source_label(session)
    on_demand = _session_on_demand_optionals_for_flow(session)
    if team_source:
        lines.append(f"- Источник runtime-команды: {team_source}.")
    if activos:
        lines.append(f"- Активные опциональные агенты: {', '.join(activos)}.")
    if on_demand:
        lines.append(f"- Опциональные агенты только по запросу в этом процессе: {', '.join(on_demand)}.")

    return "\n".join(lines) + "\n"


def _section_decisions(decisions: Dict[str, Any]) -> str:
    """Render the key decisions loaded from memory."""
    if not decisions.get("available"):
        return ""

    items = decisions.get("items") or []
    lines = ["## Ключевые решения\n"]
    total = int(decisions.get("total", 0) or 0)

    if not items:
        lines.append("В памяти нет зарегистрированных решений для этой сессии.\n")
        return "\n".join(lines) + "\n"

    lines.append(
        f"Найдено решений, связанных с итерацией памяти: **{total}**.\n"
    )
    for item in items:
        title = _truncate_text(item.get("title", ""), limit=90, default="Решение без названия")
        chosen = _truncate_text(item.get("chosen", ""), limit=120, default="выбор не зарегистрирован")
        phase = _single_line_text(item.get("phase", ""))
        status = _single_line_text(item.get("status", ""), default="active")
        rationale = _truncate_text(item.get("rationale", ""), limit=120)

        meta: List[str] = []
        if phase:
            meta.append(f"фаза: {phase}")
        if status and status != "active":
            meta.append(f"статус: {status}")
        if rationale:
            meta.append(rationale)
        meta_suffix = f" ({'; '.join(meta)})" if meta else ""

        lines.append(f"- **{title}** -> {chosen}{meta_suffix}")

    return "\n".join(lines) + "\n"


def _section_next_step(
    session: Dict[str, Any], project_dir: Optional[str], completed: bool
) -> str:
    """Show the most reasonable next operational step."""
    payload = _report_next_step_payload(project_dir, session, completed)
    return (
        "## Рекомендуемый следующий шаг\n\n"
        f"- Фокус: {payload['focus']}\n"
        f"- Источник: {payload['source_label']} (`{payload['source']}`)\n"
        f"- Команда: `{payload['command']}`\n"
        f"- Что делать сейчас: {payload['directive']}\n"
        f"- Причина: {payload['reason']}\n"
    )

def _section_phases(session: Dict[str, Any]) -> str:
    """Build the completed phases section.

    Walks the phases recorded in the session and builds a table with the
    name of each phase, its result and the generated artifacts.

    Args:
        session: session state.

    Returns:
        Markdown block with the phase table.
    """
    fases = session.get("fases_completadas", [])
    if not fases:
        return "## Фазы\n\nВ этой сессии не завершено ни одной фазы.\n"

    lines = ["## Завершённые фазы\n"]
    lines.append("| Фаза | Результат | Артефакты |")
    lines.append("|------|-----------|------------|")

    for fase in fases:
        nombre = _markdown_table_cell(fase.get("nombre", "неизвестна"))
        resultado = _markdown_table_cell(fase.get("resultado", "нет результата"))
        artefactos = fase.get("artefactos", [])
        artefactos_str = (
            _markdown_table_cell(", ".join(_single_line_text(a) for a in artefactos))
            if artefactos
            else "-"
        )
        lines.append(f"| {nombre} | {resultado} | {artefactos_str} |")

    lines.append("")
    fase_actual = session.get("fase_actual", "неизвестна")
    if fase_actual == "completado":
        lines.append("Итоговое состояние: **процесс завершён**.")
    else:
        lines.append(f"Итоговое состояние: остановлен в фазе **{fase_actual}**.")

    return "\n".join(lines) + "\n"


def _section_evidence(evidence: Optional[Dict[str, Any]] = None) -> str:
    """Build the test evidence section.

    Shows whether tests ran during the session, how many, and the result
    of each run.

    Args:
        evidence: evidence data from ``get_evidence()``. If None, the
            section is skipped.

    Returns:
        Markdown block with the evidence.
    """
    if evidence is None:
        return ""

    if not evidence.get("has_evidence", False):
        return (
            "## Прогоны тестов\n\n"
            "Во время этой сессии тесты не запускались.\n"
        )

    records = evidence.get("records", [])
    all_passing = evidence.get("all_passing", False)

    lines = ["## Прогоны тестов\n"]
    status = "все зелёные" if all_passing else "есть ошибки"
    lines.append(f"Прогонов тестов: **{len(records)}** ({status}).\n")
    lines.append("| Время | Команда | Результат |")
    lines.append("|------|---------|-----------|")

    for record in records:
        ts = record.get("timestamp", "")
        try:
            dt = datetime.fromisoformat(ts)
            hora = dt.strftime("%H:%M:%S")
        except (ValueError, TypeError):
            hora = ts[:19] if ts else "-"

        cmd = _single_line_text(record.get("command", ""))
        cmd_short = cmd[:60] + "..." if len(cmd) > 60 else cmd
        result = record.get("result", "unknown")
        result_display = {
            "pass": "OK",
            "fail": "ОШИБКА",
            "unknown": "не определён",
        }.get(result, result)

        lines.append(
            f"| {_markdown_table_cell(hora)} | "
            f"{_markdown_table_cell(_markdown_inline_code(cmd_short))} | "
            f"{_markdown_table_cell(result_display)} |"
        )

    return "\n".join(lines) + "\n"


def _section_team(session: Dict[str, Any]) -> str:
    """Build the session team section.

    Shows the optional agents that were active during the session, if any.

    Args:
        session: session state.

    Returns:
        Markdown block with the team.
    """
    equipo = session.get("equipo_sesion")
    if not equipo:
        return ""

    opcionales = equipo.get("opcionales_activos", {})
    activos = [name for name, enabled in normalize_optional_agent_flags(opcionales).items() if enabled]

    if not activos:
        return ""

    lines = ["## Команда сессии\n"]
    source = _session_team_source_label(session)
    if source:
        lines.append(f"Источник runtime: **{source}**.\n")
    lines.append("Активные опциональные агенты:\n")
    for agent in order_optional_agent_names(activos):
        lines.append(f"- {agent}")

    on_demand = _session_on_demand_optionals_for_flow(session)
    if on_demand:
        lines.append("")
        lines.append("Опциональные агенты только по запросу в этом процессе:\n")
        for agent in on_demand:
            lines.append(f"- {agent}")

    return "\n".join(lines) + "\n"


def _section_artifacts(session: Dict[str, Any]) -> str:
    """Build the generated artifacts section.

    Lists all artifacts recorded during the flow.

    Args:
        session: session state.

    Returns:
        Markdown block with the artifacts.
    """
    artefactos = session.get("artefactos", [])
    if not artefactos:
        return ""

    lines = ["## Созданные артефакты\n"]
    for artefacto in artefactos:
        lines.append(f"- {_markdown_inline_code(artefacto)}")

    return "\n".join(lines) + "\n"


def _get_plugin_version() -> str:
    """Read the plugin version from plugin.json. Fall back to a hardcoded value."""
    try:
        plugin_path = os.path.join(
            os.path.dirname(__file__), "..", ".claude-plugin", "plugin.json"
        )
        with open(plugin_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("version", "0.7.0")
    except (OSError, json.JSONDecodeError, KeyError):
        return "0.7.0"


def _section_mode(session: Dict[str, Any]) -> str:
    """Build the session mode section (autopilot or interactive).

    Args:
        session: session state.

    Returns:
        Markdown block with the session mode.
    """
    is_autopilot = session.get("autopilot", False)
    modo = "autopilot" if is_autopilot else "интерактивный"
    return f"## Режим сессии\n\nРежим: **{modo}**\n"


def _section_iterations(session: Dict[str, Any]) -> str:
    """Build the per-phase iterations section if any phase had retries.

    Shows only phases with at least one iteration. An iteration means
    the phase gate did not pass on the first try.

    Args:
        session: session state.

    Returns:
        Markdown block with the iteration table, or an empty string if
        no phase had retries.
    """
    fases = session.get("fases_completadas", [])
    fases_con_iteraciones = [
        f for f in fases if f.get("iteraciones", 0) > 0
    ]
    if not fases_con_iteraciones:
        return ""

    lines = ["## Итерации по фазам\n"]
    lines.append("| Фаза | Итерации |")
    lines.append("|------|------------|")
    for fase in fases_con_iteraciones:
        lines.append(
            f"| {_markdown_table_cell(fase['nombre'])} | "
            f"{_markdown_table_cell(fase['iteraciones'])} |"
        )

    return "\n".join(lines) + "\n"


def _estimate_duration(session: Dict[str, Any]) -> str:
    """Estimate the session duration from its timestamps.

    Computes the difference between ``creado_en`` and ``actualizado_en``.

    Args:
        session: session state.

    Returns:
        String with the estimated duration in a readable format.
    """
    creado = session.get("creado_en", "")
    actualizado = session.get("actualizado_en", "")

    if not creado or not actualizado:
        return "нет данных"

    try:
        dt_start = datetime.fromisoformat(creado)
        dt_end = datetime.fromisoformat(actualizado)
        delta = dt_end - dt_start
        total_seconds = int(delta.total_seconds())

        if total_seconds < 0:
            return "нет данных"
        if total_seconds < 60:
            return f"{total_seconds} сек."
        minutes = total_seconds // 60
        if minutes < 60:
            return f"{minutes} мин."
        hours = minutes // 60
        remaining_minutes = minutes % 60
        return f"{hours} ч {remaining_minutes} мин."
    except (ValueError, TypeError):
        return "нет данных"


# --- Main function ---

def generate_report(
    session: Dict[str, Any],
    evidence: Optional[Dict[str, Any]] = None,
    project_dir: Optional[str] = None,
    completed: bool = True,
) -> str:
    """Build a full session report in markdown.

    Assembles the report sections in order: executive summary, next
    step, mode, phases, iterations, test evidence, team and artifacts.
    The report is saved in the project directory
    ``docs/alfred-reports/``.

    If ``completed`` is False, an alternative template marks the session
    as interrupted. This is for partial reports that the stop hook
    writes when it finds a session in progress.

    Args:
        session: session state (orchestrator dict).
        evidence: test evidence data (optional).
        project_dir: project directory. If None, uses cwd.
        completed: True if the session is complete, False if partial.

    Returns:
        Path of the generated file.
    """
    base = project_dir or os.getcwd()

    # Assemble sections
    decisions = _session_decisions_snapshot(base, session, completed)
    secciones = []
    secciones.append(_section_summary(session, evidence, decisions, base, completed))
    secciones.append(_section_next_step(session, base, completed))
    secciones.append(_section_decisions(decisions))
    secciones.append(_section_mode(session))
    secciones.append(_section_phases(session))
    secciones.append(_section_iterations(session))
    secciones.append(_section_evidence(evidence))
    secciones.append(_section_team(session))
    secciones.append(_section_artifacts(session))

    # Drop empty sections
    secciones_text = "\n".join(s for s in secciones if s.strip())

    # Header data
    comando = _single_line_text(session.get("comando", "desconocido"), default="desconocido")
    descripcion = _single_line_text(
        session.get("descripcion", "без описания"), default="без описания"
    )
    duracion = _estimate_duration(session)
    fecha = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    version = _get_plugin_version()

    template = _REPORT_TEMPLATE if completed else _REPORT_TEMPLATE_INTERRUPTED
    report_content = template.format(
        comando=comando,
        fecha=fecha,
        duracion=duracion,
        descripcion=descripcion,
        secciones=secciones_text,
        version=version,
    )

    # Save the report
    report_dir = os.path.join(base, _REPORT_DIR)
    os.makedirs(report_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    # Sanitize the command name to prevent path traversal
    safe_comando = re.sub(r"[^a-zA-Z0-9_-]", "_", comando)
    filename = f"{timestamp}-{safe_comando}.md"
    report_path = os.path.join(report_dir, filename)

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
    except OSError as e:
        raise RuntimeError(
            f"Не удалось сохранить отчёт о сессии в '{report_path}': {e}. "
            f"Проверь, что каталог '{report_dir}' существует и доступен "
            f"для записи."
        ) from e

    return report_path
