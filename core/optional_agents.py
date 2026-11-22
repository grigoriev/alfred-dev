#!/usr/bin/env python3
"""Canonical catalog of the optional agents of the Alfred Dev plugin."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


OPTIONAL_AGENT_GROUP_ORDER: Tuple[str, ...] = ("audit",)

OPTIONAL_AGENT_GROUP_LABELS: Dict[str, str] = {
    "audit": "Аудит",
}

OPTIONAL_AGENT_GROUP_QUESTIONS: Dict[str, str] = {
    "audit": "Хочешь активировать CTO как внешнее второе мнение?",
}

OPTIONAL_AGENT_MENU_EXIT = {
    "label": "Продолжить без включения",
    "description": "Перейти к следующей группе",
}

OPTIONAL_AGENT_MENU_DONE = {
    "label": "Готово с этой группой",
    "description": "Сохранить текущий выбор и перейти к следующей группе",
}


OPTIONAL_AGENT_CATALOG: Dict[str, Dict[str, Any]] = {
    "cto": {
        "group": "audit",
        "label": "CTO",
        "specialty": "Внешнее техническое второе мнение и финальный аудит",
        "static_suggestion": False,
        "integration": {
            "fases": [
                "calidad",
                "validacion_rapida",
                "validacion",
                "auditoria_final",
                "auditoria_paralela",
            ],
            "posicion": "secuencial",
        },
    },
}


# Legacy names accepted when reading config or state of existing projects.
LEGACY_OPTIONAL_AGENT_ALIASES: Dict[str, str] = {
    "lucius": "cto",
}


def canonical_optional_agent_name(agent_name: Any) -> str:
    """Map a legacy optional agent name to its canonical name."""
    name = str(agent_name).strip()
    return LEGACY_OPTIONAL_AGENT_ALIASES.get(name, name)


def normalize_optional_agent_flags(raw_flags: Dict[Any, Any]) -> Dict[str, Any]:
    """Rename legacy keys. The canonical key wins if both are present."""
    normalized: Dict[str, Any] = {}
    for raw_name, value in raw_flags.items():
        name = canonical_optional_agent_name(raw_name)
        is_canonical = name == str(raw_name).strip()
        if is_canonical or name not in normalized:
            normalized[name] = value
    return normalized


def get_optional_agent_names() -> Tuple[str, ...]:
    """Return the optional agent names in canonical order."""
    return tuple(OPTIONAL_AGENT_CATALOG.keys())


def get_optional_agent_display_label(agent_name: str) -> str:
    """Return the canonical display label of an optional agent."""
    metadata = OPTIONAL_AGENT_CATALOG.get(agent_name)
    if metadata is None:
        raise KeyError(f"Unknown optional agent: {agent_name}")
    return metadata["label"]


def get_optional_agent_specialty(agent_name: str) -> str:
    """Return the canonical short description of the agent."""
    metadata = OPTIONAL_AGENT_CATALOG.get(agent_name)
    if metadata is None:
        raise KeyError(f"Unknown optional agent: {agent_name}")
    return metadata["specialty"]


def is_optional_agent_on_demand_only(agent_name: str) -> bool:
    """Tell if the agent is not added to phases automatically."""
    metadata = OPTIONAL_AGENT_CATALOG.get(agent_name)
    if metadata is None:
        raise KeyError(f"Unknown optional agent: {agent_name}")
    return metadata.get("runtime_mode") == "on_demand"


def order_optional_agent_names(names: Iterable[str]) -> List[str]:
    """Sort a collection of agents in canonical catalog order."""
    seen = []
    for raw_name in names:
        agent_name = str(raw_name).strip()
        if agent_name and agent_name not in seen:
            seen.append(agent_name)

    ordered = [
        agent_name
        for agent_name in get_optional_agent_names()
        if agent_name in seen
    ]
    extras = sorted(
        agent_name
        for agent_name in seen
        if agent_name not in OPTIONAL_AGENT_CATALOG
    )
    return ordered + extras


def build_optional_agent_flags(default: bool = False) -> Dict[str, bool]:
    """Build the block of bool flags for config/equipo_sesion."""
    return {
        agent_name: bool(default)
        for agent_name in get_optional_agent_names()
    }


def get_optional_agents_by_group() -> Dict[str, List[str]]:
    """Group the optional agents by group and keep the canonical order."""
    grouped: Dict[str, List[str]] = {
        group_name: []
        for group_name in OPTIONAL_AGENT_GROUP_ORDER
    }
    for agent_name, metadata in OPTIONAL_AGENT_CATALOG.items():
        grouped[metadata["group"]].append(agent_name)
    return grouped


def build_optional_agent_menu_option(
    agent_name: str,
    *,
    suggested_reason: Optional[str] = None,
    active: bool = False,
) -> Dict[str, str]:
    """Build a canonical navigable option for AskUserQuestion."""
    label = get_optional_agent_display_label(agent_name)
    description = get_optional_agent_specialty(agent_name)

    if suggested_reason:
        label = f"{label} (Рекомендуется)"
        description = suggested_reason.strip()

    if is_optional_agent_on_demand_only(agent_name):
        description = (
            f"{description}. Только по запросу: автоматически не входит "
            "ни в одну фазу."
        )

    if active:
        description = f"{description}. Сейчас активен."

    return {"label": label, "description": description}


def build_optional_agent_group_menu(
    group_name: str,
    *,
    suggested_reasons: Optional[Dict[str, str]] = None,
    active_names: Optional[Iterable[str]] = None,
    excluded_names: Optional[Iterable[str]] = None,
    include_done_option: bool = False,
) -> Dict[str, Any]:
    """Build the canonical navigable menu for one group of optional agents."""
    if group_name not in OPTIONAL_AGENT_GROUP_LABELS:
        raise KeyError(f"Unknown group: {group_name}")

    suggested_reasons = suggested_reasons or {}
    active_set: Set[str] = set(active_names or ())
    excluded_set: Set[str] = set(excluded_names or ())

    options: List[Dict[str, str]] = [dict(OPTIONAL_AGENT_MENU_EXIT)]
    if include_done_option:
        options.append(dict(OPTIONAL_AGENT_MENU_DONE))

    for agent_name in get_optional_agents_by_group()[group_name]:
        if agent_name in excluded_set:
            continue
        options.append(
            build_optional_agent_menu_option(
                agent_name,
                suggested_reason=suggested_reasons.get(agent_name),
                active=agent_name in active_set,
            )
        )

    header = OPTIONAL_AGENT_GROUP_LABELS[group_name]
    question = OPTIONAL_AGENT_GROUP_QUESTIONS[group_name]

    return {
        "group": group_name,
        "questions": [
            {
                "question": question,
                "header": header,
                "options": options,
                "multiSelect": False,
            }
        ],
        "header": header,
        "question": question,
        "options": options,
    }


def build_optional_agent_group_menus(
    *,
    suggested_reasons: Optional[Dict[str, str]] = None,
    active_names: Optional[Iterable[str]] = None,
    excluded_names_by_group: Optional[Dict[str, Iterable[str]]] = None,
    include_done_option: bool = False,
) -> List[Dict[str, Any]]:
    """Return the canonical navigable menus in the official order."""
    menus: List[Dict[str, Any]] = []
    excluded_names_by_group = excluded_names_by_group or {}

    for group_name in OPTIONAL_AGENT_GROUP_ORDER:
        menus.append(
            build_optional_agent_group_menu(
                group_name,
                suggested_reasons=suggested_reasons,
                active_names=active_names,
                excluded_names=excluded_names_by_group.get(group_name),
                include_done_option=include_done_option,
            )
        )
    return menus


def get_static_suggestible_agent_names() -> Tuple[str, ...]:
    """Return the agents that static project I/O can suggest."""
    return tuple(
        agent_name
        for agent_name, metadata in OPTIONAL_AGENT_CATALOG.items()
        if metadata.get("static_suggestion", False)
    )


def get_optional_integrations() -> Dict[str, Dict[str, Any]]:
    """Return a shallow copy of the per-phase integrations."""
    return {
        agent_name: {
            "fases": list(metadata["integration"]["fases"]),
            "posicion": metadata["integration"]["posicion"],
        }
        for agent_name, metadata in OPTIONAL_AGENT_CATALOG.items()
    }
