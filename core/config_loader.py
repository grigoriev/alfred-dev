#!/usr/bin/env python3
"""
Config loader for the Alfred Dev plugin.

This module reads the user config from a .local.md file with YAML
frontmatter, detects the project tech stack and merges everything with
sensible defaults.

It works without external dependencies: it includes a basic YAML parser as a
fallback for environments without PyYAML.

Public functions:
    - load_config(path): load and merge config from a .local.md file
    - load_project_config(project_dir): load the local config and apply stack detection
    - detect_stack(project_dir): detect runtime, language, framework and ORM
"""

import json
import os
import re
import copy
import sys
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.optional_agents import (
    build_optional_agent_flags,
    get_optional_agent_display_label,
    get_optional_agent_names,
    get_optional_integrations,
    get_static_suggestible_agent_names,
    normalize_optional_agent_flags,
    order_optional_agent_names,
)

# Try to import PyYAML. If it is not available, use the basic parser.
try:
    import yaml

    _HAS_YAML = True
except ImportError:
    _HAS_YAML = False

try:
    from core.memory_config import DEFAULT_MEMORY_CONFIG
except Exception:
    DEFAULT_MEMORY_CONFIG = {
        "enabled": False,
        "sync_to_native": True,
        "sync_commits_limit": 10,
        "capture_decisions": True,
        "capture_commits": True,
        "retention_days": 365,
    }

_CANONICAL_AUTONOMY_DEFAULTS = {
    "product": "autonomous",
    "architecture": "autonomous",
    "development": "autonomous",
    "quality": "autonomous",
    "documentation": "autonomous",
    "delivery": "autonomous",
}

_AUTONOMY_VALUE_ALIASES = {
    "interactive": "interactive",
    "autonomous": "autonomous",
    "semi_autonomous": "semi-autonomous",
}

_LEGACY_AUTONOMY_KEY_ALIASES = {
    "docs": "documentation",
    "refactor": "development",
    "tests": "quality",
    "devops": "delivery",
}

_SECURITY_PHASES = ("architecture", "quality", "delivery")


# --- Default config ---
# These values define the base plugin behavior when the user has set no
# preference. Each section controls a different aspect:
#
# - autonomy: how much the plugin can decide on its own
# - project: project metadata (detect_stack fills it)
# - compliance: compliance and style rules
# - integrations: enabled external services
# - personality: reply language and verbosity
# - notes: free user text with extra preferences

DEFAULT_CONFIG = {
    "autonomy": dict(_CANONICAL_AUTONOMY_DEFAULTS),
    "project": {
        "runtime": "unknown",
        "language": "unknown",
        "framework": "unknown",
        "orm": "none",
        "test_runner": "unknown",
        "bundler": "unknown",
    },
    "compliance": {
        "style": "auto",
        "lint": True,
        "format_on_save": True,
    },
    "integrations": {
        "git": True,
        "ci": False,
        "deploy": False,
    },
    "personality": {
        "verbosity": "normal",
        "language": "ru",
    },
    # Optional agents: predefined agents that the user enables per project.
    # The catalog sets the default per agent (CTO is off).
    # /alfred-dev:config changes them per project.
    "optional_agents": build_optional_agent_flags(),
    "memory": dict(DEFAULT_MEMORY_CONFIG),
    "notes": "",
}

_CONFIG_FRONTMATTER_KEYS = tuple(
    key for key in DEFAULT_CONFIG.keys()
    if key != "notes"
)
_BOOTSTRAP_LOCAL_CONFIG_PATCH = {
    "autonomy": dict(_CANONICAL_AUTONOMY_DEFAULTS),
    "memory": {
        "enabled": True,
        "sync_to_native": True,
        "sync_commits_limit": 10,
        "capture_decisions": True,
        "capture_commits": True,
        "retention_days": 365,
    },
}
_BOOTSTRAP_LOCAL_CONFIG_NOTE = (
    "Этот файл создаётся автоматически в первой сессии.\n"
    "Ты можешь настроить его через `/alfred-dev:config`."
)
_CONFIG_SECTION_ORDER = (
    "autonomy",
    "project",
    "optional_agents",
    "memory",
    "compliance",
    "integrations",
    "personality",
)
_CONFIG_SECTION_LABELS = {
    "autonomy": "Автономность по фазам",
    "project": "Проект",
    "optional_agents": "Опциональные агенты",
    "memory": "Постоянная память",
    "compliance": "Compliance",
    "integrations": "Интеграции",
    "personality": "Личность",
}
_CONFIG_SECTION_MENU_EXIT = {
    "label": "Выйти без изменений",
    "description": "Пока оставить текущую конфигурацию",
}
# Stack dicts store the sentinels "unknown" and "none".
# Map them to Russian only when a summary shows them to the user.
_STACK_SENTINEL_LABELS = {
    "unknown": "не определён",
    "none": "нет",
}


def _render_stack_value(value: Any) -> str:
    """Return a stack value for display. Map stored sentinels to Russian."""
    text = str(value)
    return _STACK_SENTINEL_LABELS.get(text, text)


def load_config(path):
    """
    Load the plugin config from a .local.md file.

    The file uses YAML frontmatter (delimited by ---) for config values and
    the Markdown body for free-text notes. If the file does not exist or
    cannot be read, the defaults are returned.

    The merge is recursive: file values override only the keys they define.
    All other defaults stay intact.

    Args:
        path: absolute or relative path to the config file.

    Returns:
        dict with the merged config. It always contains all DEFAULT_CONFIG
        keys, also when the file defines none.

    Example:
        >>> config = load_config("/project/.claude/alfred-dev.local.md")
        >>> config["autonomy"]["product"]
        'autonomous'
    """
    # Always start from a deep copy of the defaults so that calls do not
    # mutate the global dict
    config = copy.deepcopy(DEFAULT_CONFIG)

    if not os.path.isfile(path):
        return config

    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except (OSError, IOError) as e:
        print(
            f"[Alfred Dev] Предупреждение: не удалось прочитать '{path}': {e}. "
            f"Используются значения по умолчанию.",
            file=sys.stderr,
        )
        return config

    frontmatter, body = _parse_frontmatter(content)

    if frontmatter:
        parsed = _parse_yaml(frontmatter)
        if isinstance(parsed, dict):
            config = _deep_merge(config, _normalize_loaded_config(parsed))
        elif parsed is not None:
            print(
                f"[Alfred Dev] Предупреждение: frontmatter в '{path}' не является словарём. "
                f"Настройки из файла игнорируются.",
                file=sys.stderr,
            )

    # Extract the notes from the Markdown body.
    # Find any section whose heading contains "Заметки" or "Notes" (h1-h6).
    # All content from that heading to the next heading of the same level,
    # or to the end of the document, counts as notes.
    notes = _extract_notes(body)
    if notes:
        config["notes"] = notes

    return config


def load_project_config(project_dir: str) -> Dict[str, Any]:
    """Load the effective config of a project: config plus stack.

    Automatic detection fills the ``project`` section when the user has not
    overridden it explicitly in ``.claude/alfred-dev.local.md``.

    Args:
        project_dir: path to the project root directory.

    Returns:
        Merged config, ready for operational use.
    """
    config_path = os.path.join(project_dir, ".claude", "alfred-dev.local.md")
    config = load_config(config_path)
    detected_stack = detect_stack(project_dir)

    effective_project = dict(detected_stack)
    configured_project = config.get("project", {})
    defaults = DEFAULT_CONFIG["project"]

    if isinstance(configured_project, dict):
        for key, value in configured_project.items():
            default_value = defaults.get(key)
            if key not in effective_project or value != default_value:
                effective_project[key] = value

    config["project"] = effective_project
    return config


def get_active_optional_agents(config: Dict[str, Any]) -> List[str]:
    """Return the active optional agents in canonical order."""
    optionals = config.get("optional_agents", {})
    if not isinstance(optionals, dict):
        return []
    optionals = normalize_optional_agent_flags(optionals)

    known = set(get_optional_agent_names())
    return order_optional_agent_names(
        name
        for name, enabled in optionals.items()
        if enabled and name in known
    )


def build_session_team_from_config(
    config: Dict[str, Any],
    *,
    source: str = "persisted_config",
) -> Optional[Dict[str, Any]]:
    """Build the runtime ``session_team`` from the effective config.

    This function maps the persisted project config to the same structural
    contract that dynamic composition uses. This way runtime, hooks and
    operational docs do not keep two different sources of truth about which
    optional agents are active.

    Args:
        config: effective, already merged config.
        source: value of ``source`` to record in the session.

    Returns:
        An ``session_team`` dict ready for runtime, or ``None`` if there is
        nothing operational to inject (no active optional agents and memory
        off).
    """
    flags = build_optional_agent_flags()
    raw_optionals = config.get("optional_agents", {})
    if isinstance(raw_optionals, dict):
        raw_optionals = normalize_optional_agent_flags(raw_optionals)
        for agent_name in flags:
            if agent_name in raw_optionals:
                flags[agent_name] = bool(raw_optionals.get(agent_name, False))

    memory = config.get("memory", {})
    memory_enabled = False
    if isinstance(memory, dict):
        memory_enabled = bool(memory.get("enabled", False))

    if not any(flags.values()) and not memory_enabled:
        return None

    return {
        "active_optionals": flags,
        "infra": {
            "memory": memory_enabled,
        },
        "source": source,
    }


def build_project_session_team(
    project_dir: str,
    *,
    source: str = "persisted_config",
) -> Optional[Dict[str, Any]]:
    """Load the project config and derive its runtime ``session_team``."""
    config = load_project_config(project_dir)
    return build_session_team_from_config(config, source=source)


def build_config_section_summaries(
    config: Dict[str, Any],
    *,
    project_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Describe the current config per section with canonical summaries.

    `/alfred-dev:config` uses this structure to show the current state in a
    navigable menu without building the phrases by hand again.
    """
    effective_config = _deep_merge(
        DEFAULT_CONFIG,
        _normalize_loaded_config(config if isinstance(config, dict) else {}),
    )
    project_stack = detect_stack(project_dir) if project_dir else None

    return [
        _describe_config_section(
            section_name,
            effective_config,
            project_stack=project_stack,
        )
        for section_name in _CONFIG_SECTION_ORDER
    ]


def build_config_section_menu(
    config: Dict[str, Any],
    *,
    project_dir: Optional[str] = None,
    include_exit_option: bool = True,
) -> Dict[str, Any]:
    """Build the main navigable menu of `/alfred-dev:config`."""
    options: List[Dict[str, str]] = []
    if include_exit_option:
        options.append(dict(_CONFIG_SECTION_MENU_EXIT))

    for section in build_config_section_summaries(config, project_dir=project_dir):
        options.append(
            {
                "label": section["label"],
                "description": section["summary"],
            }
        )

    question = "Какую секцию хочешь изменить сейчас?"
    header = "Config"

    return {
        "questions": [
            {
                "question": question,
                "header": header,
                "options": options,
                "multiSelect": False,
            }
        ],
        "header": "Config",
        "question": question,
        "options": options,
    }


def apply_config_section_update(
    config: Dict[str, Any],
    section_name: str,
    values: Any,
) -> Dict[str, Any]:
    """Apply a change to a canonical section and return the final config.

    It uses the same normalization as `load_config()`, so `/alfred-dev:config`
    can update one section without losing order, defaults or aliases.
    """
    if section_name not in _CONFIG_SECTION_ORDER:
        raise KeyError(f"Неизвестная секция конфигурации: {section_name}")

    effective_config = _deep_merge(
        DEFAULT_CONFIG,
        _normalize_loaded_config(config if isinstance(config, dict) else {}),
    )
    patch = _normalize_loaded_config({section_name: values})
    return _deep_merge(effective_config, patch)


def build_config_section_change_preview(
    config: Dict[str, Any],
    section_name: str,
    values: Any,
    *,
    project_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Summarize the effective change of a section before it is saved.

    Return the canonical before/after summary and the updated config, so
    `/alfred-dev:config` can confirm the change without building it by hand
    or implementing the normalization again.
    """
    effective_config = _deep_merge(
        DEFAULT_CONFIG,
        _normalize_loaded_config(config if isinstance(config, dict) else {}),
    )
    updated_config = apply_config_section_update(
        effective_config,
        section_name,
        values,
    )
    project_stack = detect_stack(project_dir) if project_dir else None
    before = _describe_config_section(
        section_name,
        effective_config,
        project_stack=project_stack,
    )
    after = _describe_config_section(
        section_name,
        updated_config,
        project_stack=project_stack,
    )

    return {
        "section": section_name,
        "label": before["label"],
        "changed": before["details"] != after["details"] or before["summary"] != after["summary"],
        "before": before,
        "after": after,
        "updated_config": updated_config,
    }


def update_config_section(
    path: str,
    section_name: str,
    values: Any,
    *,
    notes: Optional[str] = None,
    include_defaults: bool = True,
) -> Dict[str, Any]:
    """Update one section of a `.local.md` file in canonical form.

    The flow is always the same: load, normalize, apply the section patch,
    save and return a structured preview of the change.
    """
    current_config = load_config(path)
    preview = build_config_section_change_preview(
        current_config,
        section_name,
        values,
    )
    save_config(
        path,
        preview["updated_config"],
        notes=current_config.get("notes", "") if notes is None else notes,
        include_defaults=include_defaults,
    )
    return preview


def update_project_config_section(
    project_dir: str,
    section_name: str,
    values: Any,
    *,
    notes: Optional[str] = None,
    include_defaults: bool = True,
) -> Dict[str, Any]:
    """Update one section of the persisted project config."""
    path = os.path.join(project_dir, ".claude", "alfred-dev.local.md")
    return update_config_section(
        path,
        section_name,
        values,
        notes=notes,
        include_defaults=include_defaults,
    )


def render_config_markdown(
    config: Dict[str, Any],
    *,
    notes: Optional[str] = None,
    include_defaults: bool = True,
) -> str:
    """Serialize a config to the canonical ``.local.md`` format.

    The frontmatter uses canonical keys and a stable order, so the runtime,
    the hooks and `/alfred-dev:config` share exactly the same base format.
    """
    normalized_input = _normalize_loaded_config(config)
    if include_defaults:
        normalized = _deep_merge(DEFAULT_CONFIG, normalized_input)
    else:
        normalized = copy.deepcopy(normalized_input)
    notes_body = (
        notes
        if notes is not None
        else normalized.get("notes", "")
    )
    frontmatter_payload = {
        key: copy.deepcopy(normalized[key])
        for key in _CONFIG_FRONTMATTER_KEYS
        if key in normalized
    }
    frontmatter = _render_yaml_mapping(frontmatter_payload, DEFAULT_CONFIG)

    parts = ["---", frontmatter.rstrip(), "---"]
    trimmed_notes = str(notes_body or "").strip()
    if trimmed_notes:
        parts.extend(["", "## Заметки", "", trimmed_notes])
    return "\n".join(parts) + "\n"


def save_config(
    path: str,
    config: Dict[str, Any],
    *,
    notes: Optional[str] = None,
    include_defaults: bool = True,
) -> None:
    """Write a canonical config to disk."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    content = render_config_markdown(
        config,
        notes=notes,
        include_defaults=include_defaults,
    )
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def save_project_config(
    project_dir: str,
    config: Dict[str, Any],
    *,
    notes: Optional[str] = None,
    include_defaults: bool = True,
) -> str:
    """Save the project config to ``.claude/alfred-dev.local.md``."""
    path = os.path.join(project_dir, ".claude", "alfred-dev.local.md")
    save_config(path, config, notes=notes, include_defaults=include_defaults)
    return path


def ensure_bootstrap_local_config(
    path: str,
    *,
    default_note: str = _BOOTSTRAP_LOCAL_CONFIG_NOTE,
) -> bool:
    """Make sure a minimal canonical local config exists for the first start.

    Rules:
    - If the file does not exist, create it with per-phase autonomy and
      memory on.
    - If it exists without frontmatter, wrap the existing content in a minimal
      canonical config and keep the text as notes.
    - If it exists with frontmatter, add only the missing top-level sections
      (`autonomy` and `memory`) and do not overwrite explicit preferences.

    Returns:
        ``True`` if it wrote changes. ``False`` if the file was already ready.
    """
    if not os.path.exists(path):
        save_config(
            path,
            _BOOTSTRAP_LOCAL_CONFIG_PATCH,
            notes=default_note,
            include_defaults=False,
        )
        return True

    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()

    frontmatter, body = _parse_frontmatter(content)
    body_text = body.strip()

    if not frontmatter:
        save_config(
            path,
            _BOOTSTRAP_LOCAL_CONFIG_PATCH,
            notes=body_text or default_note,
            include_defaults=False,
        )
        return True

    parsed = _parse_yaml(frontmatter)
    normalized = _normalize_loaded_config(parsed if isinstance(parsed, dict) else {})
    changed = False

    if not _has_top_level_frontmatter_section(frontmatter, "autonomy"):
        normalized["autonomy"] = copy.deepcopy(_BOOTSTRAP_LOCAL_CONFIG_PATCH["autonomy"])
        changed = True

    if not _has_top_level_frontmatter_section(frontmatter, "memory"):
        normalized["memory"] = copy.deepcopy(_BOOTSTRAP_LOCAL_CONFIG_PATCH["memory"])
        changed = True

    if not changed:
        return False

    save_config(
        path,
        normalized,
        notes=body_text or None,
        include_defaults=False,
    )
    return True


def ensure_bootstrap_project_config(
    project_dir: str,
    *,
    default_note: str = _BOOTSTRAP_LOCAL_CONFIG_NOTE,
) -> str:
    """Apply the canonical bootstrap to `.claude/alfred-dev.local.md`."""
    path = os.path.join(project_dir, ".claude", "alfred-dev.local.md")
    ensure_bootstrap_local_config(path, default_note=default_note)
    return path


def _describe_config_section(
    section_name: str,
    config: Dict[str, Any],
    *,
    project_stack: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a stable, human-readable description of a section."""
    if section_name == "autonomy":
        autonomy = config.get("autonomy", {})
        autonomy_counts = {"interactive": 0, "semi-autonomous": 0, "autonomous": 0}
        for phase_name in _CANONICAL_AUTONOMY_DEFAULTS:
            level = autonomy.get(phase_name, _CANONICAL_AUTONOMY_DEFAULTS[phase_name])
            if level in autonomy_counts:
                autonomy_counts[level] += 1

        if autonomy_counts["autonomous"] == len(_CANONICAL_AUTONOMY_DEFAULTS):
            summary = "Полный autopilot во всех 6 фазах."
        else:
            parts = []
            if autonomy_counts["interactive"]:
                parts.append(f"интерактивных: {autonomy_counts['interactive']}")
            if autonomy_counts["semi-autonomous"]:
                parts.append(f"полуавтономных: {autonomy_counts['semi-autonomous']}")
            if autonomy_counts["autonomous"]:
                parts.append(f"автономных: {autonomy_counts['autonomous']}")
            summary = "Автономность по фазам: " + ", ".join(parts) + "."

        details = [
            {
                "name": phase_name,
                "value": autonomy.get(phase_name, _CANONICAL_AUTONOMY_DEFAULTS[phase_name]),
            }
            for phase_name in _CANONICAL_AUTONOMY_DEFAULTS
        ]
    elif section_name == "project":
        configured_project = config.get("project", {})
        project = dict(project_stack or DEFAULT_CONFIG["project"])
        if isinstance(configured_project, dict):
            for key, value in configured_project.items():
                default_value = DEFAULT_CONFIG["project"].get(key)
                if key not in project or value != default_value:
                    project[key] = value
        fields = [
            project.get("runtime", "unknown"),
            project.get("language", "unknown"),
            project.get("framework", "unknown"),
            project.get("orm", "none"),
            project.get("test_runner", "unknown"),
            project.get("bundler", "unknown"),
        ]
        summary = " / ".join(_render_stack_value(value) for value in fields) + "."
        details = [
            {"name": key, "value": project.get(key, DEFAULT_CONFIG["project"][key])}
            for key in DEFAULT_CONFIG["project"]
        ]
        if project_stack:
            overrides = [
                key
                for key in DEFAULT_CONFIG["project"]
                if project.get(key, DEFAULT_CONFIG["project"][key]) != project_stack.get(key)
                and project.get(key, DEFAULT_CONFIG["project"][key]) != DEFAULT_CONFIG["project"][key]
            ]
            summary += " Определён автоматически." if not overrides else (
                " Задано вручную: " + ", ".join(overrides) + "."
            )
    elif section_name == "optional_agents":
        active_names = get_active_optional_agents(config)
        if active_names:
            active_labels = ", ".join(
                get_optional_agent_display_label(agent_name)
                for agent_name in active_names
            )
            on_demand_names = [
                agent_name
                for agent_name in active_names
                if not get_optional_integrations()[agent_name]["phases"]
            ]
            summary = f"Активных: {len(active_names)} ({active_labels})."
            if on_demand_names:
                on_demand_labels = ", ".join(
                    get_optional_agent_display_label(agent_name)
                    for agent_name in on_demand_names
                )
                summary += f" По запросу: {on_demand_labels}."
        else:
            summary = "Нет активных опциональных агентов."
        details = [
            {"name": agent_name, "value": bool(config["optional_agents"].get(agent_name, False))}
            for agent_name in build_optional_agent_flags()
        ]
    elif section_name == "memory":
        memory = config.get("memory", {})
        if memory.get("enabled"):
            summary = (
                "Активна с нативной синхронизацией "
                f"({memory.get('sync_commits_limit', DEFAULT_MEMORY_CONFIG['sync_commits_limit'])} коммитов), "
                f"решения={'да' if memory.get('capture_decisions', True) else 'нет'}, "
                f"коммиты={'да' if memory.get('capture_commits', True) else 'нет'}."
            )
        else:
            summary = "Неактивна: новые решения и коммиты не записываются."
        details = [
            {"name": key, "value": memory.get(key, DEFAULT_MEMORY_CONFIG.get(key))}
            for key in DEFAULT_MEMORY_CONFIG
        ]
    elif section_name == "compliance":
        compliance = config.get("compliance", {})
        summary = (
            f"стиль={compliance.get('style', 'auto')}, "
            f"lint={'вкл' if compliance.get('lint', True) else 'выкл'}, "
            f"формат при сохранении={'вкл' if compliance.get('format_on_save', True) else 'выкл'}."
        )
        details = [
            {"name": key, "value": compliance.get(key, DEFAULT_CONFIG["compliance"][key])}
            for key in DEFAULT_CONFIG["compliance"]
        ]
    elif section_name == "integrations":
        integrations = config.get("integrations", {})
        summary = ", ".join(
            f"{key}={'вкл' if integrations.get(key, DEFAULT_CONFIG['integrations'][key]) else 'выкл'}"
            for key in DEFAULT_CONFIG["integrations"]
        ) + "."
        details = [
            {"name": key, "value": integrations.get(key, DEFAULT_CONFIG["integrations"][key])}
            for key in DEFAULT_CONFIG["integrations"]
        ]
    elif section_name == "personality":
        personality = config.get("personality", {})
        summary = (
            f"язык={personality.get('language', 'ru')}, "
            f"подробность={personality.get('verbosity', 'normal')}."
        )
        details = [
            {"name": key, "value": personality.get(key, DEFAULT_CONFIG["personality"][key])}
            for key in DEFAULT_CONFIG["personality"]
        ]
    else:
        raise KeyError(f"Неизвестная секция конфигурации: {section_name}")

    return {
        "section": section_name,
        "label": _CONFIG_SECTION_LABELS[section_name],
        "summary": summary,
        "details": details,
    }


def is_autopilot_configured(config: Dict[str, Any]) -> bool:
    """Tell if the per-phase autonomy config turns on autopilot."""
    autonomy = config.get("autonomy", {})
    if not isinstance(autonomy, dict):
        return False

    return all(
        autonomy.get(phase_name) == "autonomous"
        for phase_name in _CANONICAL_AUTONOMY_DEFAULTS
    )


def is_autopilot_enabled_for_project(
    project_dir: str,
    state_path: Optional[str] = None,
) -> bool:
    """Decide if the project must run in autopilot by config or state.

    Args:
        project_dir: path to the project root directory.
        state_path: optional path to the state file. If not given, use
            ``.claude/alfred-dev-state.json``.

    Returns:
        True if the config enables autopilot or the persisted state marks it.
    """
    config = load_project_config(project_dir)
    if is_autopilot_configured(config):
        return True

    resolved_state_path = state_path or os.path.join(
        project_dir,
        ".claude",
        "alfred-dev-state.json",
    )
    try:
        with open(resolved_state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, IOError, json.JSONDecodeError):
        return False

    if not isinstance(state, dict):
        return False

    return state.get("autopilot") is True


def detect_stack(project_dir):
    """
    Detect the tech stack of a project from its key files.

    Check for files such as package.json, tsconfig.json, pyproject.toml,
    Cargo.toml, go.mod, pom.xml, composer.json, .csproj files or
    Package.swift to infer the runtime, language, framework and ORM of the
    project.

    Framework and ORM detection reads the dependencies declared in the
    project manifests (package.json for Node, pyproject.toml for Python,
    etc.).

    Args:
        project_dir: path to the project root directory.

    Returns:
        dict with the keys: runtime, lenguaje, framework, orm, test_runner,
        bundler. Values that are not detected come back as 'unknown' or
        'none', as applicable.

    Example:
        >>> stack = detect_stack("/my-next-project")
        >>> stack["framework"]
        'next'
    """
    stack = {
        "runtime": "unknown",
        "language": "unknown",
        "framework": "unknown",
        "orm": "none",
        "test_runner": "unknown",
        "bundler": "unknown",
    }

    # --- Runtime and language detection ---
    # Order matters: check the most specific case first.
    # A package.json means a Node project. A tsconfig.json makes it
    # TypeScript.

    has_package_json = os.path.isfile(os.path.join(project_dir, "package.json"))
    has_tsconfig = os.path.isfile(os.path.join(project_dir, "tsconfig.json"))
    has_pyproject = os.path.isfile(os.path.join(project_dir, "pyproject.toml"))
    has_setup_py = os.path.isfile(os.path.join(project_dir, "setup.py"))
    has_requirements = os.path.isfile(os.path.join(project_dir, "requirements.txt"))
    has_cargo = os.path.isfile(os.path.join(project_dir, "Cargo.toml"))
    has_go_mod = os.path.isfile(os.path.join(project_dir, "go.mod"))
    has_gemfile = os.path.isfile(os.path.join(project_dir, "Gemfile"))
    has_mix = os.path.isfile(os.path.join(project_dir, "mix.exs"))
    has_pom = os.path.isfile(os.path.join(project_dir, "pom.xml"))
    has_gradle = any(
        os.path.isfile(os.path.join(project_dir, name))
        for name in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")
    )
    has_composer = os.path.isfile(os.path.join(project_dir, "composer.json"))
    has_dotnet = _has_root_file_with_suffix(project_dir, (".csproj", ".sln"))
    has_package_swift = os.path.isfile(os.path.join(project_dir, "Package.swift"))

    # A package.json next to another strong manifest (pom.xml, go.mod, ...)
    # usually serves only frontend assets. Node defines the stack only if it
    # declares a framework or if there is no other strong manifest.
    has_other_strong_manifest = any((
        has_pyproject, has_setup_py, has_cargo, has_go_mod, has_gemfile,
        has_mix, has_pom, has_gradle, has_composer, has_dotnet, has_package_swift,
    ))
    node_stack = None
    if has_package_json:
        node_stack = dict(stack)
        node_stack["runtime"] = "node"
        node_stack["language"] = "typescript" if has_tsconfig else "javascript"
        _detect_node_details(project_dir, node_stack)
        if has_other_strong_manifest and node_stack["framework"] == "unknown":
            node_stack = None

    if node_stack is not None:
        stack.update(node_stack)
    elif has_pyproject or has_setup_py or has_requirements:
        stack["runtime"] = "python"
        stack["language"] = "python"
        _detect_python_details(project_dir, stack)
    elif has_cargo:
        stack["runtime"] = "rust"
        stack["language"] = "rust"
    elif has_go_mod:
        stack["runtime"] = "go"
        stack["language"] = "go"
    elif has_gemfile:
        stack["runtime"] = "ruby"
        stack["language"] = "ruby"
    elif has_mix:
        stack["runtime"] = "elixir"
        stack["language"] = "elixir"
    elif has_pom or has_gradle:
        stack["runtime"] = "jvm"
        stack["language"] = "kotlin" if _looks_like_kotlin_project(project_dir) else "java"
        _detect_jvm_details(project_dir, stack)
    elif has_composer:
        stack["runtime"] = "php"
        stack["language"] = "php"
        _detect_php_details(project_dir, stack)
    elif has_dotnet:
        stack["runtime"] = "dotnet"
        stack["language"] = "csharp"
        _detect_dotnet_details(project_dir, stack)
    elif has_package_swift:
        stack["runtime"] = "swift"
        stack["language"] = "swift"
        _detect_swift_details(project_dir, stack)

    return stack


# --- Frameworks with a user interface ---

_FRONTEND_FRAMEWORKS = frozenset({
    "next", "nuxt", "astro", "remix", "gatsby",
    "svelte", "solid-js", "qwik",
    "react", "vue", "angular",
})

_FRONTEND_FRAMEWORK_ALIASES = {
    "nextjs": "next",
    "next.js": "next",
    "reactjs": "react",
    "vuejs": "vue",
    "solid": "solid-js",
}


def has_frontend(stack: dict) -> bool:
    """
    Tell if the project stack includes a framework with a user interface.

    This is the activation condition for the Designer agent, which works
    only on projects with a visual layer.

    Args:
        stack: stack dict returned by ``detect_stack``.
               It is expected to contain the ``"framework"`` key.

    Returns:
        ``True`` if the framework is in the set of known frontend
        frameworks. ``False`` otherwise or if the key does not exist.

    Example:
        >>> stack = detect_stack("/path/to/project")
        >>> if has_frontend(stack):
        ...     # Enable the visual style phase
        ...     pass
    """
    raw_framework = str(stack.get("framework", "unknown") or "unknown").strip().lower()
    normalized_framework = _FRONTEND_FRAMEWORK_ALIASES.get(raw_framework, raw_framework)
    return normalized_framework in _FRONTEND_FRAMEWORKS


# --- Internal functions ---


def _find_first_match(candidates, deps):
    """
    Find the first match between a list of candidates and a set of dependencies.

    Walk the candidates in order and return the first one that is a key in
    the dependency dict or set. Used to detect frameworks, ORMs, test
    runners and bundlers by priority.

    Args:
        candidates: list of package names to find, in priority order.
        deps: dict or set of dependencies to search.

    Returns:
        str with the name of the found package, or None if nothing matches.
    """
    for candidate in candidates:
        if candidate in deps:
            return candidate
    return None


def _has_root_file_with_suffix(project_dir, suffixes):
    try:
        return any(
            name.endswith(suffixes)
            for name in os.listdir(project_dir)
            if os.path.isfile(os.path.join(project_dir, name))
        )
    except OSError:
        return False


def _read_text_if_exists(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except (OSError, IOError, UnicodeDecodeError):
        return ""


def _root_file_text(project_dir, names):
    parts = []
    for name in names:
        text = _read_text_if_exists(os.path.join(project_dir, name))
        if text:
            parts.append(text)
    return "\n".join(parts).lower()


def _project_has_source_suffix(project_dir, suffixes, max_depth=3):
    root_depth = len(os.path.abspath(project_dir).split(os.sep))
    ignored = {".git", "node_modules", "vendor", "target", "build", ".build", "bin", "obj"}
    for current, dirs, files in os.walk(project_dir):
        dirs[:] = [name for name in dirs if name not in ignored]
        depth = len(os.path.abspath(current).split(os.sep)) - root_depth
        if depth > max_depth:
            dirs[:] = []
            continue
        if any(name.endswith(suffixes) for name in files):
            return True
    return False


def _looks_like_kotlin_project(project_dir):
    return (
        os.path.isfile(os.path.join(project_dir, "build.gradle.kts"))
        or os.path.isfile(os.path.join(project_dir, "settings.gradle.kts"))
        or _project_has_source_suffix(project_dir, (".kt", ".kts"))
    )


def _extract_python_dependency_names(text):
    """Extract normalized Python dependency names from free text."""
    names = set()
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("["):
            continue

        if line.startswith(('"', "'")):
            match = re.match(r"""^["']([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?""", line)
        else:
            match = re.match(r"""^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?""", line)

        if not match:
            continue

        name = match.group(1).lower().replace("_", "-")
        names.add(name)

    return names


def _normalize_scoped_package(name):
    """
    Normalize a scoped package name (@org/package) to its base form.

    Remove the '@' prefix and keep the scope part (without the sub-package
    name). For example: '@nestjs/core' -> 'nestjs', '@prisma/client' -> 'prisma'.
    Packages without a scope come back unchanged.

    Args:
        name: npm package name.

    Returns:
        str with the normalized name.
    """
    if name.startswith("@"):
        return name.replace("@", "").split("/")[0]
    return name


def _parse_frontmatter(content):
    """
    Extract the YAML frontmatter and the Markdown body from a text.

    Lines that contain exactly '---' must delimit the frontmatter. The first
    delimiter must be the first non-empty line of the document.

    Args:
        content: full file text.

    Returns:
        tuple (frontmatter_str, body_str). If there is no frontmatter,
        frontmatter_str is an empty string.
    """
    # Find the ---\n...\n--- pattern at the start of the content.
    # The middle group uses .*? (lazy) to stop at the first closing ---.
    match = re.match(
        r"\A(?:\ufeff)?(?:[ \t]*\n)*---[ \t]*\n(.*?)\n---[ \t]*\n?(.*)",
        content,
        re.DOTALL,
    )
    if match:
        return match.group(1), match.group(2)
    return "", content


def _has_top_level_frontmatter_section(frontmatter: str, section: str) -> bool:
    """Tell if a raw frontmatter contains a top-level section."""
    target = f"{section}:"
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if not stripped or line.startswith((" ", "\t")):
            continue
        if stripped == target:
            return True
    return False


def _strip_accents(value: str) -> str:
    """Normalize a Unicode string by removing accents, for comparisons."""
    return "".join(
        char
        for char in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(char)
    )


def _normalize_identifier(value: Any) -> Any:
    """Convert human-written keys to a stable identifier for internal aliases."""
    if not isinstance(value, str):
        return value

    normalized = _strip_accents(value).strip().lower()
    normalized = normalized.replace("-", "_").replace(" ", "_")
    return normalized


def _normalize_autonomy_value(value: Any) -> Any:
    """Map variants such as 'Autonomous' or 'semi autonomous' to the canonical format."""
    if not isinstance(value, str):
        return value

    normalized = _normalize_identifier(value)
    return _AUTONOMY_VALUE_ALIASES.get(normalized, value)


def _normalize_autonomy_section(section: Dict[str, Any]) -> Dict[str, Any]:
    """Adapt old autonomy schemas to the per-phase schema."""
    primary: Dict[str, Any] = {}
    legacy: Dict[str, Any] = {}
    security_value: Optional[Any] = None

    for raw_key, raw_value in section.items():
        normalized_key = _normalize_identifier(raw_key)
        normalized_value = _normalize_autonomy_value(raw_value)

        if normalized_key == "security":
            security_value = normalized_value
            continue

        if normalized_key in _CANONICAL_AUTONOMY_DEFAULTS:
            primary[normalized_key] = normalized_value
            continue

        alias_target = _LEGACY_AUTONOMY_KEY_ALIASES.get(normalized_key)
        if alias_target is not None:
            legacy[alias_target] = normalized_value
            continue

        primary[raw_key] = normalized_value

    normalized_section = dict(primary)
    for canonical_key, legacy_value in legacy.items():
        normalized_section.setdefault(canonical_key, legacy_value)

    if security_value is not None:
        for phase_name in _SECURITY_PHASES:
            normalized_section.setdefault(phase_name, security_value)

    return normalized_section


def _normalize_loaded_config(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize legacy aliases and documented sections to the canonical form."""
    normalized: Dict[str, Any] = {}

    for raw_key, raw_value in parsed.items():
        canonical_key = raw_key
        normalized_key = _normalize_identifier(canonical_key)

        if normalized_key == "autonomy" and isinstance(raw_value, dict):
            normalized["autonomy"] = _normalize_autonomy_section(raw_value)
            continue

        if canonical_key == "optional_agents" and isinstance(raw_value, dict):
            known = set(get_optional_agent_names())
            normalized["optional_agents"] = {
                name: bool(value)
                for name, value in normalize_optional_agent_flags(raw_value).items()
                if name in known
            }
            continue

        normalized[canonical_key] = raw_value

    return normalized


def _deep_merge(base, override):
    """
    Merge two dicts recursively.

    Values from 'override' replace the values from 'base'. When both values
    are dicts, they merge recursively instead of replacing the whole dict.
    This lets the user set only the keys to change and keep the defaults of
    all other keys.

    Args:
        base: base dict (copied, not mutated).
        override: dict with the overriding values.

    Returns:
        new dict with both merged.

    Example:
        >>> _deep_merge({"a": {"x": 1, "y": 2}}, {"a": {"x": 99}})
        {'a': {'x': 99, 'y': 2}}
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _parse_yaml(text):
    """
    Parse a YAML text and return a dict.

    Use PyYAML if it is available. Otherwise fall back to a basic parser
    that supports the YAML subset the plugin config needs: nested dicts
    with scalar values (strings, numbers, booleans).

    The basic parser does not support lists, anchors, aliases or other
    advanced YAML constructs. For complex configs, install PyYAML.

    Args:
        text: string with YAML content.

    Returns:
        dict with the parsed values, or an empty dict if parsing fails.
    """
    if _HAS_YAML:
        try:
            result = yaml.safe_load(text)
            if not isinstance(result, dict):
                print(
                    "[Alfred Dev] Предупреждение: YAML frontmatter не является словарём. "
                    "Настройки из файла игнорируются.",
                    file=sys.stderr,
                )
                return {}
            return result
        except yaml.YAMLError as e:
            print(
                f"[Alfred Dev] Ошибка: синтаксическая ошибка в YAML frontmatter: {e}. "
                f"Настройки из файла игнорируются.",
                file=sys.stderr,
            )
            return {}

    return _basic_yaml_parse(text)


def _basic_yaml_parse(text):
    """
    Minimal YAML parser without external dependencies.

    It supports the subset the plugin config needs:
    - key: value pairs
    - Nesting by indentation (spaces)
    - Scalar values: strings, integers, floats, booleans, null

    It does not support lists, multiline strings, anchors or aliases. It is
    a fallback for environments without PyYAML. In production, install
    PyYAML.

    Args:
        text: string with basic YAML content.

    Returns:
        dict with the parsed values.
    """
    result = {}
    # Stack that tracks the current nesting level.
    # Each item is (indent_level, dict_reference)
    stack = [(0, result)]

    for line in text.split("\n"):
        # Skip empty lines and comments
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Compute the indentation to find the level
        indent = len(line) - len(line.lstrip())

        # Find the key: value pattern
        match = re.match(r"^(\w[\w\-]*):\s*(.*)", stripped)
        if not match:
            continue

        key = match.group(1)
        raw_value = match.group(2).strip()

        # Pop the stack until the correct parent is found
        while len(stack) > 1 and stack[-1][0] >= indent:
            stack.pop()

        parent = stack[-1][1]

        if raw_value:
            # A key: scalar value pair
            parent[key] = _coerce_yaml_value(raw_value)
        else:
            # A key that opens a nested dict
            new_dict = {}
            parent[key] = new_dict
            stack.append((indent, new_dict))

    return result


def _coerce_yaml_value(value):
    """
    Convert a YAML string value to the matching Python type.

    Conversion rules:
    - 'true'/'false' (case insensitive) -> bool
    - 'null'/'~' -> None
    - Integers -> int
    - Decimals -> float
    - Quoted strings -> string without quotes
    - Everything else -> string as is

    Args:
        value: string with the raw YAML value.

    Returns:
        Python value converted to the correct type.
    """
    # Booleans
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False

    # Null
    if value.lower() in ("null", "~"):
        return None

    # Quoted strings: remove the outer quotes
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]

    # Integers
    try:
        return int(value)
    except ValueError:
        pass

    # Floats
    try:
        return float(value)
    except ValueError:
        pass

    return value


def _extract_notes(body):
    """
    Extract the content of the notes section from the Markdown body.

    Find a heading (h1-h6) whose text contains 'Заметки' or 'Notes' and extract all
    content up to the next heading of the same level or to the end of the
    document.

    Args:
        body: Markdown text (without frontmatter).

    Returns:
        str with the content of the notes section, or an empty string if
        no section with that heading exists.
    """
    # Find a line that starts with # and contains "Заметки" or "Notes".
    # Use [^\n]*? (lazy) to prevent excessive backtracking on long lines.
    pattern = re.compile(r"^(#{1,6})\s+[^\n]*?(?:[Зз]аметки|[Nn]otes)[^\n]*$", re.MULTILINE)
    match = pattern.search(body)
    if not match:
        return ""

    header_level = len(match.group(1))
    start = match.end()

    # Find the next heading of the same or a higher level
    next_header = re.compile(
        r"^#{1," + str(header_level) + r"}\s+", re.MULTILINE
    )
    next_match = next_header.search(body, start)

    if next_match:
        notes_text = body[start : next_match.start()]
    else:
        notes_text = body[start:]

    return notes_text.strip()


def _ordered_dict_items(
    data: Dict[str, Any],
    template: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, Any]]:
    """Return items in a stable order that follows a template if one exists."""
    seen = set()
    items: List[Tuple[str, Any]] = []

    if isinstance(template, dict):
        for key in template.keys():
            if key in data:
                items.append((key, data[key]))
                seen.add(key)

    for key in data.keys():
        if key not in seen:
            items.append((key, data[key]))
            seen.add(key)

    return items


def _render_yaml_scalar(value: Any) -> str:
    """Render a Python scalar as simple, stable YAML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)

    text = str(value)
    if not text:
        return '""'

    if re.fullmatch(r"[A-Za-z0-9_./:-]+", text):
        return text

    return json.dumps(text, ensure_ascii=False)


def _render_yaml_mapping(
    data: Dict[str, Any],
    template: Optional[Dict[str, Any]] = None,
    *,
    indent: int = 0,
) -> str:
    """Render a simple dict as stable YAML."""
    lines: List[str] = []
    prefix = " " * indent

    for key, value in _ordered_dict_items(data, template):
        if isinstance(value, dict):
            child_template = template.get(key) if isinstance(template, dict) else None
            rendered_child = _render_yaml_mapping(
                value,
                child_template if isinstance(child_template, dict) else None,
                indent=indent + 2,
            )
            lines.append(f"{prefix}{key}:")
            if rendered_child:
                lines.append(rendered_child)
        else:
            lines.append(f"{prefix}{key}: {_render_yaml_scalar(value)}")

    return "\n".join(lines)


def _detect_node_details(project_dir, stack):
    """
    Detect framework, ORM, test runner and bundler in a Node project.

    Read package.json and check both 'dependencies' and 'devDependencies'
    to identify the project tools.

    Args:
        project_dir: path to the project directory.
        stack: stack dict, modified in place.
    """
    pkg_path = os.path.join(project_dir, "package.json")
    try:
        with open(pkg_path, "r", encoding="utf-8") as f:
            pkg = json.load(f)
    except (OSError, IOError, json.JSONDecodeError) as e:
        print(
            f"[Alfred Dev] Предупреждение: не удалось прочитать '{pkg_path}': {e}. "
            f"Определение framework будет неполным.",
            file=sys.stderr,
        )
        return

    # Merge all dependencies to search in one pass
    all_deps = {
        **pkg.get("dependencies", {}),
        **pkg.get("devDependencies", {}),
    }

    # Frameworks: if frontend and backend coexist, prefer the UI, so that
    # conditional phases and suggestions reflect a real interface.
    frontend_frameworks = [
        "next", "nuxt", "astro", "remix", "gatsby", "svelte",
        "solid-js", "qwik", "vue", "react", "angular", "@angular/core",
    ]
    backend_frameworks = [
        "hono", "express", "fastify", "koa", "nest", "@nestjs/core",
    ]

    found = _find_first_match(frontend_frameworks, all_deps)
    if not found:
        found = _find_first_match(backend_frameworks, all_deps)
    if found:
        stack["framework"] = _normalize_scoped_package(found)

    # ORMs and query builders
    orms = [
        "drizzle-orm", "prisma", "@prisma/client", "typeorm",
        "sequelize", "knex", "mongoose", "mikro-orm", "@mikro-orm/core",
    ]

    found = _find_first_match(orms, all_deps)
    if found:
        # Simplify: @prisma/client -> prisma, drizzle-orm -> drizzle
        name = _normalize_scoped_package(found)
        stack["orm"] = name.replace("-orm", "").replace("-client", "")

    # Test runners
    test_runners = [
        "vitest", "jest", "mocha", "ava", "tap", "playwright", "cypress",
    ]

    found = _find_first_match(test_runners, all_deps)
    if found:
        stack["test_runner"] = found

    # Bundlers
    bundlers = [
        "vite", "webpack", "esbuild", "rollup",
        "parcel", "turbopack", "tsup", "unbuild",
    ]

    found = _find_first_match(bundlers, all_deps)
    if found:
        stack["bundler"] = found


def _detect_python_details(project_dir, stack):
    """
    Detect framework, ORM and test runner in a Python project.

    Read pyproject.toml (basic reading, no full TOML parser) and
    requirements.txt to identify the dependencies.

    Args:
        project_dir: path to the project directory.
        stack: stack dict, modified in place.
    """
    deps_text = ""

    # Try to read pyproject.toml to extract dependencies
    pyproject_path = os.path.join(project_dir, "pyproject.toml")
    if os.path.isfile(pyproject_path):
        try:
            with open(pyproject_path, "r", encoding="utf-8") as f:
                deps_text += f.read()
        except (OSError, IOError) as e:
            print(
                f"[Alfred Dev] Предупреждение: не удалось прочитать '{pyproject_path}': {e}. "
                f"Определение framework будет неполным.",
                file=sys.stderr,
            )

    # Add requirements.txt if it exists
    reqs_path = os.path.join(project_dir, "requirements.txt")
    if os.path.isfile(reqs_path):
        try:
            with open(reqs_path, "r", encoding="utf-8") as f:
                deps_text += "\n" + f.read()
        except (OSError, IOError) as e:
            print(
                f"[Alfred Dev] Предупреждение: не удалось прочитать '{reqs_path}': {e}. "
                f"Определение framework будет неполным.",
                file=sys.stderr,
            )

    dependency_names = _extract_python_dependency_names(deps_text)

    # Python frameworks (order = priority)
    py_frameworks = [
        "fastapi", "django", "flask", "starlette",
        "litestar", "sanic", "tornado", "aiohttp",
    ]

    found = _find_first_match(py_frameworks, dependency_names)
    if found:
        stack["framework"] = found

    # Python ORMs: each tuple maps the search key to the assigned name
    # where they differ (django -> django-orm)
    py_orms = [
        ("sqlalchemy", "sqlalchemy"),
        ("sqlmodel", "sqlmodel"),
        ("django", "django-orm"),
        ("tortoise-orm", "tortoise"),
        ("peewee", "peewee"),
        ("pony", "pony"),
    ]

    for dep_name, orm_name in py_orms:
        if dep_name in dependency_names:
            stack["orm"] = orm_name
            break

    # Python test runners
    py_test_runners = ["pytest", "unittest", "nose"]

    found = _find_first_match(py_test_runners, dependency_names)
    if found:
        stack["test_runner"] = found


def _detect_jvm_details(project_dir, stack):
    """Detect framework and runner in Java/Kotlin projects."""
    text = _root_file_text(
        project_dir,
        (
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "settings.gradle",
            "settings.gradle.kts",
        ),
    )
    if not text:
        return

    framework_markers = (
        ("spring-boot", ("spring-boot", "org.springframework.boot")),
        ("quarkus", ("quarkus", "io.quarkus")),
        ("micronaut", ("micronaut", "io.micronaut")),
    )
    for framework, markers in framework_markers:
        if any(marker in text for marker in markers):
            stack["framework"] = framework
            break

    if "junit" in text:
        stack["test_runner"] = "junit"
    elif "kotest" in text:
        stack["test_runner"] = "kotest"


def _detect_php_details(project_dir, stack):
    """Detect framework, ORM and runner in PHP projects with Composer."""
    composer_path = os.path.join(project_dir, "composer.json")
    try:
        with open(composer_path, "r", encoding="utf-8") as f:
            composer = json.load(f)
    except (OSError, IOError, json.JSONDecodeError):
        return

    deps = {
        **composer.get("require", {}),
        **composer.get("require-dev", {}),
    }

    frameworks = (
        ("laravel", "laravel/framework"),
        ("symfony", "symfony/framework-bundle"),
        ("slim", "slim/slim"),
    )
    for framework, package in frameworks:
        if package in deps:
            stack["framework"] = framework
            break

    if "doctrine/orm" in deps:
        stack["orm"] = "doctrine"
    if "phpunit/phpunit" in deps:
        stack["test_runner"] = "phpunit"
    elif "pestphp/pest" in deps:
        stack["test_runner"] = "pest"


def _detect_dotnet_details(project_dir, stack):
    """Detect framework, ORM and runner in C#/.NET projects."""
    parts = []
    try:
        root_names = os.listdir(project_dir)
    except OSError:
        root_names = []
    for name in root_names:
        if name.endswith((".csproj", ".sln")):
            parts.append(_read_text_if_exists(os.path.join(project_dir, name)))
    text = "\n".join(parts).lower()

    if "microsoft.net.sdk.web" in text:
        stack["framework"] = "aspnet"
    if "microsoft.aspnetcore.components.webassembly" in text or "blazor" in text:
        stack["framework"] = "blazor"
    if "microsoft.entityframeworkcore" in text:
        stack["orm"] = "entity-framework"

    if "xunit" in text:
        stack["test_runner"] = "xunit"
    elif "nunit" in text:
        stack["test_runner"] = "nunit"
    elif "mstest" in text:
        stack["test_runner"] = "mstest"


def _detect_swift_details(project_dir, stack):
    """Detect framework and runner in Swift Package Manager projects."""
    text = _read_text_if_exists(os.path.join(project_dir, "Package.swift")).lower()
    if "vapor" in text:
        stack["framework"] = "vapor"
    if ".testtarget" in text or "swift-testing" in text:
        stack["test_runner"] = "swift-test"


# --- Contextual discovery of optional agents ------------------------------


def _has_github_remote(project_dir):
    """Check if the project has a GitHub remote.

    Read the .git/config file directly to avoid subprocess dependencies.
    Accept only a remote whose URL points to GitHub, so that
    ``github-manager`` is not suggested for GitLab, Bitbucket or other
    forges.

    Args:
        project_dir: path to the project root directory.

    Returns:
        True if there is at least one GitHub remote, False otherwise.
    """
    git_config = os.path.join(project_dir, ".git", "config")
    if not os.path.isfile(git_config):
        return False
    try:
        with open(git_config, "r", encoding="utf-8") as f:
            content = f.read().lower()
            return "github.com:" in content or "github.com/" in content
    except (OSError, IOError) as e:
        print(
            f"[Alfred Dev] Предупреждение: не удалось прочитать .git/config: {e}",
            file=sys.stderr,
        )
        return False


def _has_public_html(project_dir):
    """Detect if the project has public web content.

    Look for common signs of static websites or landing pages: HTML files
    in the root or in typical directories (public/, site/, dist/).

    Args:
        project_dir: path to the project root directory.

    Returns:
        True if public HTML files are found, False otherwise.
    """
    # HTML files directly in the root
    for name in ("index.html", "index.htm"):
        if os.path.isfile(os.path.join(project_dir, name)):
            return True

    # Typical public content directories
    for dirname in ("public", "site", "dist", "docs"):
        dirpath = os.path.join(project_dir, dirname)
        if os.path.isdir(dirpath):
            for entry in os.listdir(dirpath):
                if entry.endswith((".html", ".htm")):
                    return True

    return False


def _scan_dir_for_sources(dirpath, source_extensions, skip_dirs, errors, max_depth, depth=0):
    """Count source files in a directory recursively.

    A depth limit controls the recursion to prevent high latency in
    projects with node_modules or other large dependency directories.

    Args:
        dirpath: directory to scan.
        source_extensions: set of source file extensions.
        skip_dirs: set of directory names to skip.
        errors: mutable list that collects access errors.
        max_depth: maximum recursion depth from the root directory.
        depth: current depth (0 = root directory).

    Returns:
        int with the number of source files found.
    """
    count = 0
    try:
        for entry in os.scandir(dirpath):
            if entry.is_file() and os.path.splitext(entry.name)[1] in source_extensions:
                count += 1
            elif entry.is_dir() and entry.name not in skip_dirs and depth < max_depth:
                count += _scan_dir_for_sources(
                    entry.path, source_extensions, skip_dirs, errors, max_depth, depth + 1
                )
    except (OSError, PermissionError) as e:
        errors.append(str(e))
    return count


def _count_source_files(project_dir):
    """Count source files in the project (up to 2 levels deep).

    Walk at most 2 levels deep to prevent high latency in projects with
    node_modules or large dependency directories. Skip known dependency and
    artifact directories.

    Args:
        project_dir: path to the project root directory.

    Returns:
        int with the number of source files found.
    """
    source_extensions = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".rs", ".go",
        ".rb", ".ex", ".exs", ".java", ".kt", ".swift", ".cs",
        ".vue", ".svelte", ".astro", ".php", ".c", ".cpp", ".h",
    }
    skip_dirs = {
        "node_modules", ".git", "dist", "build", ".next", "__pycache__",
        ".venv", "venv", "vendor", "target", ".cargo",
    }
    scan_errors = []
    count = _scan_dir_for_sources(project_dir, source_extensions, skip_dirs, scan_errors, max_depth=2)
    if scan_errors:
        print(
            f"[Alfred Dev] Предупреждение: не удалось просканировать каталоги "
            f"({len(scan_errors)}). Подсчёт файлов может быть неполным.",
            file=sys.stderr,
        )
    return count


def _is_memory_enabled(project_dir):
    """Check if persistent memory is enabled in the local config.

    Delegate to the canonical parser in ``core.memory_config`` so that
    suggestion detection and the real runtime do not disagree.

    Args:
        project_dir: path to the project root directory.

    Returns:
        True if memory is enabled, False otherwise.
    """
    try:
        from core.memory_config import is_memory_enabled
    except Exception:
        return False

    return is_memory_enabled(project_dir)


def _has_i18n_signals(project_dir):
    """Detect internationalization signals in the project.

    Look for typical i18n directories or files: ``i18n``, ``locales``,
    ``translations`` folders, ``*.po``, ``*.xliff`` files, or i18n config
    files such as ``next-i18next.config.*``, ``vue-i18n``, etc.

    Args:
        project_dir: path to the project root directory.

    Returns:
        True if internationalization signals are found.
    """
    # Typical i18n directories
    i18n_dirs = ("i18n", "locales", "translations", "lang", "langs")
    for d in i18n_dirs:
        if os.path.isdir(os.path.join(project_dir, d)):
            return True
        if os.path.isdir(os.path.join(project_dir, "src", d)):
            return True

    # i18n config files
    i18n_files = (
        "next-i18next.config.js",
        "next-i18next.config.mjs",
        "i18n.config.ts",
        "i18n.config.js",
        ".i18nrc",
        ".i18nrc.json",
    )
    for f in i18n_files:
        if os.path.isfile(os.path.join(project_dir, f)):
            return True

    return False


def _build_suggestion_checks(stack, project_dir):
    """Evaluate the project signals and return the suggestion checks.

    Each item describes a candidate optional agent with its activation
    condition and a reason the user can read. The order sets the display
    priority in the config UI.

    Args:
        stack: stack dict detected by ``detect_stack``.
        project_dir: path to the project root directory.

    Returns:
        List of ``(agent_name, condition_bool, reason)`` tuples, ready to
        filter against the active config.
    """
    checks = {}
    return [
        (agent_name, *checks[agent_name])
        for agent_name in get_static_suggestible_agent_names()
    ]


def suggest_optional_agents(project_dir, current_config=None):
    """Analyze the project and suggest relevant optional agents.

    Check the tech stack, database, frontend, public web content, GitHub
    remote and project size to recommend which optional agents can help.

    Suggest only agents that are not already enabled in the current config.

    Args:
        project_dir: path to the project root directory.
        current_config: current config dict (optional).
            If given, already active agents are filtered out.

    Returns:
        List of (agent_name, reason) tuples with the suggestions.
        Each tuple contains the agent identifier and a string that explains
        why it is suggested.

    Example:
        >>> suggestions = suggest_optional_agents("/my-next-project")
        >>> suggestions
        [('ux-reviewer', 'Проект с frontend на Next.js'),
         ('github-manager', 'Репозиторий с remote на GitHub')]
    """
    if current_config is None:
        current_config = copy.deepcopy(DEFAULT_CONFIG)

    active = current_config.get("optional_agents", {})
    stack = detect_stack(project_dir)
    checks = _build_suggestion_checks(stack, project_dir)

    return [
        (agent, reason)
        for agent, condition, reason in checks
        if condition and not active.get(agent)
    ]
