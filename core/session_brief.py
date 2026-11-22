#!/usr/bin/env python3
"""Session briefing: what is open, what was decided and how to talk to Alfred."""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

from core.continuity import (
    MEMORY_DB_RELATIVE_PATH,
    STATE_RELATIVE_PATH,
    get_pending_gate,
    load_handoff,
    load_state,
    load_uat,
    suggest_verify_action,
)
from core.memory_config import is_memory_enabled
from core.project_docs import ADR_DIR, list_adr_files


CONVERSATION_PROTOCOL = """## Как говорить с Alfred

Если пользователь описывает работу, баг, просит продолжить, сдать результат или спрашивает, что дальше, **без** slash command, действуй как `/alfred-dev:alfred`: выбери маршрут и выполни его. Не предлагай каталог.

Основной маршрут: `/alfred-dev:alfred`. Процессы: `/alfred-dev:feature`, `/alfred-dev:quick`, `/alfred-dev:fix`, `/alfred-dev:spike`, `/alfred-dev:audit`, `/alfred-dev:ship`. Статус: `/alfred-dev:progress`. Продолжить: `/alfred-dev:resume`.

Суждение, а не меню:
- локальное и ограниченное изменение → `quick`, не открывай PRD
- баг или регрессия → `fix`
- решение о стеке, auth или хранении данных → ADR, а не комментарий
- UAT в ожидании или отклонена → не развёртывай

Если в этой сессии активен Agent Teams, используй его для параллельных фаз; если нет, используй инструмент Agent. Не переписывай `.claude/settings.json`.
"""


def _read(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _last_decisions(project_dir: str, limit: int = 2) -> List[Dict[str, str]]:
    if not is_memory_enabled(project_dir):
        return []
    db_path = os.path.join(project_dir, MEMORY_DB_RELATIVE_PATH)
    if not os.path.isfile(db_path):
        return []
    try:
        from core.memory import MemoryDB

        db = MemoryDB(db_path)
        try:
            rows = db.get_decisions(limit=limit)
        finally:
            db.close()
    except Exception:
        return []
    out: List[Dict[str, str]] = []
    for row in rows:
        title = str(row.get("title") or "").strip()
        chosen = str(row.get("chosen") or row.get("choice") or "").strip()
        if title:
            out.append({"title": title, "chosen": chosen})
    return out


def list_accepted_adrs(project_dir: str) -> List[str]:
    titles: List[str] = []
    for name in list_adr_files(project_dir):
        text = _read(os.path.join(project_dir, ADR_DIR, name))
        if not re.search(r"(?im)^\*\*(?:Status|Статус):\*\*\s*(?:accepted\b|принят)", text):
            continue
        heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        titles.append(heading.group(1).strip() if heading else name)
    return titles


def build_session_brief(project_dir: str) -> Dict[str, Any]:
    """Real data for the first message of the session."""
    root = os.path.abspath(project_dir)
    state_path = os.path.join(root, STATE_RELATIVE_PATH)
    state = load_state(state_path) if os.path.isfile(state_path) else None
    if not isinstance(state, dict):
        state = None

    phase = str((state or {}).get("current_phase") or "")
    command = str((state or {}).get("command") or "")
    description = str((state or {}).get("description") or "")
    active = bool(state and phase and phase != "completed")

    handoff = load_handoff(root)
    pending_handoff = bool(handoff and not handoff.get("resolved", False))
    uat = load_uat(root) or {}
    uat_status = str(uat.get("status") or "")
    verify = suggest_verify_action(root)
    decisions = _last_decisions(root)
    adrs = list_accepted_adrs(root)

    next_step = ""
    if active:
        next_step = "/alfred-dev:resume"
    elif pending_handoff:
        next_step = "/alfred-dev:resume"
    elif verify is not None or uat_status in {"pending", "rejected"}:
        next_step = "/alfred-dev:uat"
    else:
        next_step = ""

    return {
        "active": active,
        "command": command,
        "phase": phase,
        "description": description,
        "pending_gate": get_pending_gate(state) if active else None,
        "pending_handoff": pending_handoff,
        "uat_status": uat_status,
        "verify_pending": verify is not None,
        "decisions": decisions,
        "accepted_adrs": adrs,
        "next_step": next_step,
    }


def render_brief_lines(brief: Dict[str, Any]) -> str:
    lines: List[str] = ["## Briefing"]
    if brief.get("active"):
        desc = brief.get("description") or "без описания"
        gate = brief.get("pending_gate") or "нет gate"
        lines.append(
            f"Активная сессия: `{brief.get('command')}` / `{brief.get('phase')}`. "
            f"{desc}. Gate: {gate}."
        )
        lines.append("Дальше: `/alfred-dev:resume`.")
    elif brief.get("pending_handoff"):
        lines.append("Есть незакрытый handoff. Дальше: `/alfred-dev:resume`.")
    elif brief.get("uat_status") == "rejected":
        lines.append("UAT отклонена. Не развёртывай. Проверь `docs/project/uat.md`.")
    elif brief.get("verify_pending") or brief.get("uat_status") == "pending":
        lines.append("UAT последнего результата ещё не пройдена. Дальше: `/alfred-dev:uat`.")
    else:
        lines.append(
            "Открытой сессии нет. Если в репозитории уже есть код, а карты нет, "
            "начни с `/alfred-dev:map-codebase`. Иначе спроси, что пользователь хочет сделать."
        )

    decisions = brief.get("decisions") or []
    if decisions:
        first = decisions[0]
        chosen = f" → {first['chosen']}" if first.get("chosen") else ""
        lines.append(f"Последнее решение: {first['title']}{chosen}.")

    adrs = brief.get("accepted_adrs") or []
    if adrs:
        lines.append("Принятые ADR: " + "; ".join(adrs[:3]) + ".")
        lines.append("Если работа противоречит принятому ADR, скажи об этом до того, как писать код.")
    return "\n".join(lines)


def render_session_start_context(project_dir: str = ".") -> str:
    """Text that SessionStart injects into Claude. The hook fails open."""
    brief = build_session_brief(project_dir)
    return CONVERSATION_PROTOCOL + "\n" + render_brief_lines(brief) + "\n"
