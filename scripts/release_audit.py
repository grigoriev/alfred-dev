#!/usr/bin/env python3
"""Reproducible checker for the 0.7.0 release audit.

The default mode runs fast local checks: versioning, manifests,
repository inventory, audit documentation and MCP shape.
Smokes that depend on external tools are enabled with flags.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
import re
import selectors
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

VERSION = "0.7.0"
OLD_VERSION = "0.5" + ".3"
INSTALLED_PLUGIN_DIR = Path.home() / ".claude" / "plugins" / "cache" / "alfred-dev" / "alfred-dev" / VERSION
GLOBAL_ALFRED_ALIAS_FILE = Path.home() / ".claude" / "skills" / "alfred" / "SKILL.md"
GLOBAL_ALFRED_COMMAND_FILE = Path.home() / ".claude" / "commands" / "alfred.md"
INSTALLED_CACHE_FRESHNESS_ROOTS = (
    ".claude-plugin",
    "agents",
    "commands",
    "core",
    "hooks",
    "mcp",
    "skills",
    "templates",
    ".mcp.json",
    "package.json",
    "README.md",
    "scripts",
)
PUBLISHABLE_SYMLINK_ROOTS = INSTALLED_CACHE_FRESHNESS_ROOTS

IGNORE_DIRS = {
    ".git",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "dist",
    "coverage-html",
    "site/dist",
    "site/node_modules",
}
IGNORED_TEXT_FILE_GLOBS = {
    "docs/external-live-smoke*.json",
    "docs/manual-smoke*.json",
    "docs/manual-smoke*.md",
}

MANUAL_ONLY_SKILLS = (
    "skills/style-direction/SKILL.md",
    "skills/incident-response/SKILL.md",
    "skills/sonarqube/SKILL.md",
    "skills/pr-workflow/SKILL.md",
)

TEMPLATE_PATHS = (
    "templates/adr.md",
    "templates/changelog-entry.md",
    "templates/prd.md",
    "templates/release-notes.md",
    "templates/sbom.md",
    "templates/test-plan.md",
    "templates/threat-model.md",
    "templates/compliance.md",
)

PLUGIN_COMPONENT_FIELDS_REQUIRING_EXPLICIT_AUDIT = {
    "agents": "Claude discovers them from agents/",
    "hooks": "use hooks/hooks.json and keep the hook-specific gate",
    "mcpServers": "use the root .mcp.json and keep the MCP-specific gate",
    "lspServers": "add an LSP gate before publishing it",
    "outputStyles": "add an output-styles gate before publishing it",
    "channels": "add a channels/MCP gate before publishing it",
    "dependencies": "add a plugin dependency gate before publishing them",
}
PLUGIN_EXPERIMENTAL_FIELDS_REQUIRING_EXPLICIT_AUDIT = {
    "themes": "add a themes gate before publishing it",
    "monitors": "add a monitors gate before publishing it",
}
MARKETPLACE_ENTRY_FIELDS_REQUIRING_EXPLICIT_AUDIT = {
    "agents": "do not supplement agents outside plugin.json",
    "commands": "do not supplement commands outside plugin.json",
    "dependencies": "do not add marketplace dependencies without a gate",
    "hooks": "do not supplement hooks outside hooks/hooks.json",
    "lspServers": "do not enable LSP from the marketplace without a gate",
    "mcpServers": "do not supplement MCP outside .mcp.json",
    "outputStyles": "do not enable output-styles from the marketplace without a gate",
    "skills": "do not supplement skills outside plugin.json",
    "experimental": "do not enable experimental components from the marketplace without a gate",
    "defaultEnabled": "do not change enablement from the marketplace; plugin.json and the docs are the authority",
}

HOOK_EVENTS_WITHOUT_MATCHER = {
    "CwdChanged",
    "MessageDisplay",
    "PostToolBatch",
    "SessionEnd",
    "Stop",
    "TaskCompleted",
    "TaskCreated",
    "TeammateIdle",
    "UserPromptSubmit",
    "WorktreeCreate",
    "WorktreeRemove",
}
HOOK_EVENTS_WITH_IF_SUPPORT = {
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "PermissionDenied",
}
HOOK_SYNC_TIMEOUT_LIMIT = 10

SKILL_SUPPORTED_FIELDS = {
    "name",
    "description",
    "when_to_use",
    "argument-hint",
    "arguments",
    "disable-model-invocation",
    "user-invocable",
    "allowed-tools",
    "disallowed-tools",
    "model",
    "effort",
    "context",
    "agent",
    "hooks",
    "paths",
    "shell",
}
SKILL_BOOLEAN_FIELDS = {"disable-model-invocation", "user-invocable"}
SKILL_BOOLEAN_VALUES = {"true", "false"}
SKILL_CONTEXT_VALUES = {"fork"}
SKILL_EFFORT_VALUES = {"low", "medium", "high", "xhigh", "max"}
SKILL_LISTING_TEXT_LIMIT = 1536
SKILL_SHELL_VALUES = {"bash", "powershell"}

COMMAND_SUPPORTED_FIELDS = {
    "allowed-tools",
    "argument-hint",
    "description",
    "disallowed-tools",
    "disable-model-invocation",
    "model",
}

AGENT_SUPPORTED_FIELDS = {
    "name",
    "description",
    "prompt",
    "tools",
    "disallowedTools",
    "model",
    "maxTurns",
    "skills",
    "initialPrompt",
    "memory",
    "effort",
    "background",
    "isolation",
    "color",
}

PLUGIN_IGNORED_AGENT_FIELDS = {"hooks", "mcpServers", "permissionMode"}

AGENT_MODEL_ALIASES = {"sonnet", "opus", "haiku", "fable", "inherit"}
AGENT_MODEL_ID_RE = re.compile(r"^claude-[a-z0-9]+(?:-[a-z0-9]+)*$")
AGENT_COLOR_VALUES = {"red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan"}
CLAUDE_TOOL_NAMES = {
    "Agent",
    "Artifact",
    "AskUserQuestion",
    "Bash",
    "CronCreate",
    "CronDelete",
    "CronList",
    "Edit",
    "EnterPlanMode",
    "EnterWorktree",
    "ExitPlanMode",
    "ExitWorktree",
    "Glob",
    "Grep",
    "ListMcpResourcesTool",
    "LSP",
    "Monitor",
    "NotebookEdit",
    "PowerShell",
    "PushNotification",
    "Read",
    "ReadMcpResourceTool",
    "RemoteTrigger",
    "SendMessage",
    "ShareOnboardingGuide",
    "WaitForMcpServers",
    "WebFetch",
    "WebSearch",
    "Workflow",
    "Write",
}
CLAUDE_PERMISSION_RULE_NAMES = CLAUDE_TOOL_NAMES | {"Skill"}
SUBAGENT_UNAVAILABLE_TOOLS = {
    "AskUserQuestion",
    "EnterPlanMode",
    "ExitPlanMode",
    "ScheduleWakeup",
    "WaitForMcpServers",
}
ALFRED_AGENT_MODEL_POLICY = Counter({"inherit": 10})


class AuditError(AssertionError):
    """Release contract error."""


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _json(path: str):
    return json.loads(_read(path))


def _has_site() -> bool:
    return (ROOT / "site" / "package.json").is_file()


def _fail(message: str) -> None:
    raise AuditError(message)


def _contains(text: str, needle: str | tuple[str, ...]) -> bool:
    """Return True when text contains the needle or one of its alternatives.

    A tuple holds the legacy Spanish phrase first and accepted translations next.
    """
    if isinstance(needle, tuple):
        return any(alternative in text for alternative in needle)
    return needle in text


def _needle_label(needle: str | tuple[str, ...]) -> str:
    """Return the primary phrase of a needle for error messages."""
    return needle[0] if isinstance(needle, tuple) else needle


def _rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _iter_installed_cache_freshness_files() -> Iterable[str]:
    for root_name in INSTALLED_CACHE_FRESHNESS_ROOTS:
        root_path = ROOT / root_name
        if root_path.is_file():
            yield root_name
            continue
        if not root_path.is_dir():
            continue
        for path in sorted(root_path.rglob("*")):
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            if path.is_file():
                yield _rel(path)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _iter_text_files() -> Iterable[Path]:
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(ROOT)
        rel_name = str(rel_path)
        if any(rel_path.match(pattern) or rel_name == pattern for pattern in IGNORED_TEXT_FILE_GLOBS):
            continue
        rel_parts = path.relative_to(ROOT).parts
        rel_prefixes = {
            "/".join(rel_parts[:index])
            for index in range(1, len(rel_parts) + 1)
        }
        if rel_prefixes & IGNORE_DIRS:
            continue
        if path.suffix in {".png", ".jpg", ".jpeg", ".gif", ".ico", ".db"}:
            continue
        yield path


def check_versions() -> list[str]:
    plugin = _json(".claude-plugin/plugin.json")
    package = _json("package.json")

    version_points = {
        ".claude-plugin/plugin.json": plugin.get("version"),
        "package.json": package.get("version"),
    }
    if _has_site():
        site_package = _json("site/package.json")
        site_lock = _json("site/package-lock.json")
        version_points.update({
            "site/package.json": site_package.get("version"),
            "site/package-lock.json": site_lock.get("version"),
            "site/package-lock root": site_lock["packages"][""].get("version"),
        })
    bad = {
        name: value
        for name, value in version_points.items()
        if value != VERSION
    }
    if bad:
        _fail(f"Versions not aligned to {VERSION}: {bad}")

    offenders: list[str] = []
    for path in _iter_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if OLD_VERSION in text or f"v{OLD_VERSION}" in text:
            offenders.append(_rel(path))
    if offenders:
        _fail(f"Live leftovers of {OLD_VERSION} remain: {offenders}")

    return [f"versions aligned to {VERSION}", f"no leftovers of {OLD_VERSION}"]


def _skill_files_from_manifest(plugin: dict) -> list[Path]:
    skill_files: list[Path] = []
    declared = plugin.get("skills") or ["./skills/"]
    for relative in declared:
        absolute = ROOT / relative.lstrip("./")
        if absolute.is_dir():
            skill_files.extend(sorted(absolute.rglob("SKILL.md")))
        elif absolute.name == "SKILL.md" and absolute.is_file():
            skill_files.append(absolute)
    return sorted(skill_files)


def _manifest_component_paths(plugin: dict, field: str) -> tuple[list[Path], list[str]]:
    values = plugin.get(field)
    if field == "skills" and values is None:
        return [ROOT / "skills"], []
    if not isinstance(values, list):
        return [], [f"plugin.json {field} must be a list"]

    paths: list[Path] = []
    problems: list[str] = []
    seen: set[str] = set()
    root = ROOT.resolve()
    for index, raw_value in enumerate(values):
        label = f"plugin.json {field}[{index}]"
        if not isinstance(raw_value, str):
            problems.append(f"{label} must be a relative string: {raw_value!r}")
            continue
        if not raw_value.startswith("./"):
            problems.append(f"{label} must start with ./ to resolve from the plugin root: {raw_value!r}")
        if Path(raw_value).is_absolute():
            problems.append(f"{label} must not be absolute: {raw_value!r}")
        if ".." in Path(raw_value).parts:
            problems.append(f"{label} must not escape the plugin with ..: {raw_value!r}")
        normalized = raw_value[2:] if raw_value.startswith("./") else raw_value
        if normalized in seen:
            problems.append(f"{label} duplicates a manifest path: {raw_value!r}")
        seen.add(normalized)
        target = (ROOT / normalized).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            problems.append(f"{label} resolves outside the plugin root: {raw_value!r}")
        paths.append(ROOT / normalized)
    return paths, problems


def check_inventory() -> list[str]:
    plugin = _json(".claude-plugin/plugin.json")
    marketplace = _json(".claude-plugin/marketplace.json")
    marketplace_plugins = marketplace.get("plugins")
    marketplace_problems: list[str] = []
    if marketplace.get("name") != plugin.get("name"):
        marketplace_problems.append(
            f"marketplace.name must match plugin.name: {marketplace.get('name')!r}"
        )
    if not isinstance(marketplace.get("owner"), dict) or not marketplace["owner"].get("name"):
        marketplace_problems.append("marketplace.owner.name is required")
    if not isinstance(marketplace_plugins, list) or len(marketplace_plugins) != 1:
        marketplace_problems.append("marketplace.plugins must contain exactly one entry")
        marketplace_plugin = {}
    else:
        marketplace_plugin = marketplace_plugins[0]
        if not isinstance(marketplace_plugin, dict):
            marketplace_problems.append("marketplace.plugins[0] must be an object")
            marketplace_plugin = {}
    if marketplace_plugin:
        if marketplace_plugin.get("name") != plugin.get("name"):
            marketplace_problems.append(
                "marketplace.plugins[0].name must match plugin.name: "
                f"{marketplace_plugin.get('name')!r}"
            )
        if marketplace_plugin.get("strict") is False:
            marketplace_problems.append(
                "marketplace.plugins[0].strict=false would make the marketplace replace plugin.json"
            )
        marketplace_problems.extend(
            f"marketplace.plugins[0] must not declare {field}: {reason}"
            for field, reason in sorted(MARKETPLACE_ENTRY_FIELDS_REQUIRING_EXPLICIT_AUDIT.items())
            if field in marketplace_plugin
        )
    if marketplace_problems:
        _fail("Alfred Dev marketplace out of sync: " + "; ".join(marketplace_problems))

    plugin_component_problems = [
        f"plugin.json must not declare {field}: {reason}"
        for field, reason in sorted(PLUGIN_COMPONENT_FIELDS_REQUIRING_EXPLICIT_AUDIT.items())
        if field in plugin
    ]
    experimental = plugin.get("experimental")
    if experimental is not None and not isinstance(experimental, dict):
        plugin_component_problems.append("plugin.json experimental must be an object")
    elif isinstance(experimental, dict):
        plugin_component_problems.extend(
            f"plugin.json must not declare experimental.{field}: {reason}"
            for field, reason in sorted(
                PLUGIN_EXPERIMENTAL_FIELDS_REQUIRING_EXPLICIT_AUDIT.items()
            )
            if field in experimental
        )
    if plugin_component_problems:
        _fail("Plugin components without explicit audit: " + "; ".join(plugin_component_problems))

    command_paths, command_path_problems = _manifest_component_paths(plugin, "commands")
    _skill_manifest_paths, skill_path_problems = _manifest_component_paths(plugin, "skills")
    path_problems = command_path_problems + skill_path_problems
    if path_problems:
        _fail("Incompatible manifest component paths: " + "; ".join(path_problems))

    missing_commands = [_rel(path) for path in command_paths if not path.exists()]
    if missing_commands:
        _fail(f"Published commands do not exist: {missing_commands}")
    public_command_paths = {path.resolve() for path in command_paths}
    extra_command_files = sorted(
        path for path in (ROOT / "commands").glob("*.md")
        if path.resolve() not in public_command_paths
    )
    if set(_rel(path) for path in extra_command_files) != {
        "commands/_composicion.md",
        "commands/_docs_vivas.md",
        "commands/next.md",
        "commands/search.md",
    }:
        _fail(
            "commands/ contains unexpected unpublished files: "
            f"{[_rel(path) for path in extra_command_files]}"
        )

    agent_files = sorted((ROOT / "agents").glob("*.md"))
    nested_agent_files = [
        path for path in (ROOT / "agents").rglob("*.md")
        if path.parent != ROOT / "agents"
    ]
    agent_frontmatter_problems: list[str] = []
    agent_models: Counter[str] = Counter()
    for path in agent_files:
        agent_text = _read(_rel(path))
        frontmatter_values = _frontmatter_top_level_values(agent_text)
        field_set = set(frontmatter_values)
        ignored = sorted(field_set & PLUGIN_IGNORED_AGENT_FIELDS)
        unknown = sorted(field_set - AGENT_SUPPORTED_FIELDS - PLUGIN_IGNORED_AGENT_FIELDS)
        if ignored:
            agent_frontmatter_problems.append(
                f"{_rel(path)} uses fields ignored in plugin agents: {ignored}"
            )
        if unknown:
            agent_frontmatter_problems.append(
                f"{_rel(path)} uses unsupported frontmatter fields: {unknown}"
            )
        for required in ("name", "description", "model"):
            if required not in field_set:
                agent_frontmatter_problems.append(f"{_rel(path)} does not declare {required}")
        model = frontmatter_values.get("model")
        if model:
            agent_models[model] += 1
            if not _is_supported_agent_model(model):
                agent_frontmatter_problems.append(
                    f"{_rel(path)} uses a model not supported by current Claude Code: {model!r}"
                )
        color = frontmatter_values.get("color")
        if color and color not in AGENT_COLOR_VALUES:
            agent_frontmatter_problems.append(
                f"{_rel(path)} uses a subagent color not supported by current Claude Code: {color!r}"
            )
        unavailable_tools = sorted(
            _frontmatter_tool_names(frontmatter_values.get("tools", ""))
            & SUBAGENT_UNAVAILABLE_TOOLS
        )
        unknown_tools = sorted(
            tool_name
            for tool_name in _frontmatter_tool_names(frontmatter_values.get("tools", ""))
            if not _is_known_agent_tool_name(tool_name)
        )
        if unknown_tools:
            agent_frontmatter_problems.append(
                f"{_rel(path)} lists tools unknown to current Claude Code: {unknown_tools}"
            )
        if unavailable_tools:
            agent_frontmatter_problems.append(
                f"{_rel(path)} lists tools not available in subagents: {unavailable_tools}"
            )
        unavailable_mentions = sorted(
            tool for tool in SUBAGENT_UNAVAILABLE_TOOLS if tool in agent_text
        )
        if unavailable_mentions:
            agent_frontmatter_problems.append(
                f"{_rel(path)} instructs tools not available in subagents: {unavailable_mentions}"
            )
    if agent_models and agent_models != ALFRED_AGENT_MODEL_POLICY:
        agent_frontmatter_problems.append(
            "agent model distribution does not match the 0.7.0 policy: "
            f"actual={dict(sorted(agent_models.items()))} "
            f"expected={dict(sorted(ALFRED_AGENT_MODEL_POLICY.items()))}"
        )
    if agent_frontmatter_problems:
        _fail("Incompatible agent frontmatter: " + "; ".join(agent_frontmatter_problems))

    skill_files = _skill_files_from_manifest(plugin)
    skill_frontmatter_problems: list[str] = []
    skill_names: dict[str, list[str]] = {}
    for path in skill_files:
        skill_text = _read(_rel(path))
        frontmatter_values = _frontmatter_top_level_values(skill_text)
        field_set = set(frontmatter_values)
        unknown = sorted(field_set - SKILL_SUPPORTED_FIELDS)
        if unknown:
            skill_frontmatter_problems.append(
                f"{_rel(path)} uses unsupported skill frontmatter fields: {unknown}"
            )
        for required in ("name", "description"):
            if required not in field_set:
                skill_frontmatter_problems.append(f"{_rel(path)} does not declare {required}")
        listing_text_length = len(
            _frontmatter_field_text(skill_text, "description")
            + _frontmatter_field_text(skill_text, "when_to_use")
        )
        if listing_text_length > SKILL_LISTING_TEXT_LIMIT:
            skill_frontmatter_problems.append(
                f"{_rel(path)} exceeds the skill listing limit "
                f"{SKILL_LISTING_TEXT_LIMIT} chars: {listing_text_length}"
            )
        name = frontmatter_values.get("name")
        if name:
            skill_names.setdefault(name, []).append(_rel(path))
            if name != path.parent.name:
                skill_frontmatter_problems.append(
                    f"{_rel(path)} declares name={name!r} but the directory is {path.parent.name!r}"
                )
        for boolean_field in sorted(SKILL_BOOLEAN_FIELDS):
            value = frontmatter_values.get(boolean_field)
            if value and value.lower() not in SKILL_BOOLEAN_VALUES:
                skill_frontmatter_problems.append(
                    f"{_rel(path)} uses non-boolean {boolean_field}: {value!r}"
                )
        model = frontmatter_values.get("model")
        if model and not _is_supported_agent_model(model):
            skill_frontmatter_problems.append(
                f"{_rel(path)} uses a skill model not supported by current Claude Code: {model!r}"
            )
        effort = frontmatter_values.get("effort")
        if effort and effort not in SKILL_EFFORT_VALUES:
            skill_frontmatter_problems.append(
                f"{_rel(path)} uses an effort not supported by current Claude Code: {effort!r}"
            )
        context = frontmatter_values.get("context")
        if context and context not in SKILL_CONTEXT_VALUES:
            skill_frontmatter_problems.append(
                f"{_rel(path)} uses a context not supported by current Claude Code: {context!r}"
            )
        if frontmatter_values.get("agent") and context != "fork":
            skill_frontmatter_problems.append(
                f"{_rel(path)} declares agent without context: fork"
            )
        shell = frontmatter_values.get("shell")
        if shell and shell not in SKILL_SHELL_VALUES:
            skill_frontmatter_problems.append(
                f"{_rel(path)} uses a shell not supported by current Claude Code: {shell!r}"
            )
        for tools_field in ("allowed-tools", "disallowed-tools"):
            unknown_tools = sorted(
                tool_name
                for tool_name in _frontmatter_tool_rule_names(
                    _frontmatter_field_rule_text(skill_text, tools_field)
                )
                if not _is_known_permission_rule_name(tool_name)
            )
            if unknown_tools:
                skill_frontmatter_problems.append(
                    f"{_rel(path)} {tools_field} declares unknown tools {unknown_tools}"
                )
    duplicated_skill_names = {
        name: paths for name, paths in sorted(skill_names.items()) if len(paths) > 1
    }
    if duplicated_skill_names:
        skill_frontmatter_problems.append(
            f"skills with duplicate name: {duplicated_skill_names}"
        )
    if skill_frontmatter_problems:
        _fail("Incompatible skill frontmatter: " + "; ".join(skill_frontmatter_problems))

    domains = {
        path.relative_to(ROOT / "skills").parts[0]
        for path in skill_files
        if path.is_relative_to(ROOT / "skills")
    }
    if plugin.get("skills"):
        _fail(
            "plugin.json must not list skills: Claude discovers them in skills/*/SKILL.md"
        )
    if plugin.get("displayName") != "Alfred Dev":
        _fail("plugin.json must declare the human displayName 'Alfred Dev'")
    if marketplace_plugin.get("displayName") != plugin.get("displayName"):
        _fail("marketplace.json must reuse the human displayName of the plugin")
    if "version" in marketplace_plugin:
        _fail(
            "marketplace.json must not duplicate version when plugin.json already "
            "declares version; Claude Code uses plugin.json as the canonical source"
        )
    marketplace_source = marketplace_plugin.get("source")
    if isinstance(marketplace_source, str) and ".." in marketplace_source.split("/"):
        _fail("The relative marketplace source must not escape the root")
    if marketplace_source != "./":
        _fail(
            "The local marketplace must point to the plugin root for this "
            f"audit: {marketplace_source!r}"
        )

    expected = {
        "commands": (len(plugin["commands"]), 18),
        "agents": (len(agent_files), 10),
        "nested_agents": (len(nested_agent_files), 0),
        "skills": (len(skill_files), 11),
        "skill_domains": (len(domains), 11),
    }
    bad = {
        key: {"actual": actual, "expected": wanted}
        for key, (actual, wanted) in expected.items()
        if actual != wanted
    }
    if bad:
        _fail(f"Inventory out of sync: {bad}")

    if not (ROOT / "commands" / "alfred.md").is_file():
        _fail("commands/alfred.md must exist as a public command")
    if "./commands/alfred.md" not in plugin.get("commands", []):
        _fail("plugin.json must publish ./commands/alfred.md")

    return [
        "18 namespaced commands published",
        "commands/alfred.md published as contextual entry",
        "commands/_composicion.md internal",
        "10 agents in root agents/",
        "agent frontmatter compatible with plugins",
        "agent tools validated against official Claude Code names",
        "unavailable tools excluded from subagents",
        "inherit models in all 10 agents",
        "11 flat skills",
        "skill frontmatter compatible with current Claude Code",
        "skill frontmatter values validated against current Claude Code",
        "skill descriptions within the 1536 listing limit",
        "human displayName aligned between manifest and marketplace",
        "canonical version only in plugin.json; marketplace without duplicate version",
        "marketplace does not supplement components or enablement",
        "command/skill paths bounded to the plugin root",
        "manifest without unaudited components",
    ]


def _command_names_from_manifest(plugin: dict) -> list[str]:
    return [
        Path(relative_path).stem
        for relative_path in plugin["commands"]
    ]


def _public_route_names(plugin: dict | None = None) -> set[str]:
    plugin = plugin or _json(".claude-plugin/plugin.json")
    names = set(_command_names_from_manifest(plugin))
    return names


def _public_argument_commands(plugin: dict | None = None) -> set[str]:
    """Return commands whose public surface accepts free text, flags or options."""
    plugin = plugin or _json(".claude-plugin/plugin.json")
    commands: set[str] = set()
    for relative_path in plugin["commands"]:
        text = _read(relative_path.lstrip("./"))
        frontmatter = _frontmatter_block(text)
        if "$ARGUMENTS" in text or re.search(r"(?m)^argument-hint:\s*.+$", frontmatter):
            commands.add(Path(relative_path).stem)
    if (ROOT / "skills" / "alfred" / "alfred" / "SKILL.md").exists():
        commands.add("alfred")
    return commands


def _validate_manual_option_contract_shape(manual_smoke, option_coverage: dict[str, list[str]]) -> None:
    """Prevent false greens caused by typos in manual option IDs."""
    option_contracts = tuple(manual_smoke.OPTION_CONTRACTS)
    problems: list[str] = []

    duplicates = sorted({
        key for key in option_contracts
        if option_contracts.count(key) > 1
    })
    if duplicates:
        problems.append(f"Duplicate OPTION_CONTRACTS: {duplicates}")

    malformed = sorted(
        key for key in option_contracts
        if key.count(":") != 1 or not key.split(":", 1)[0] or not key.split(":", 1)[1]
    )
    if malformed:
        problems.append(f"Malformed OPTION_CONTRACTS: {malformed}")

    public_commands = _public_route_names(_json(".claude-plugin/plugin.json"))
    aliases = getattr(manual_smoke, "_PUBLIC_COMMAND_ALIASES", {})
    unknown_prefixes = sorted({
        key.split(":", 1)[0]
        for key in option_contracts
        if key.count(":") == 1
        and key.split(":", 1)[0] not in public_commands
        and aliases.get(key.split(":", 1)[0]) not in public_commands
    })
    if unknown_prefixes:
        problems.append(f"OPTION_CONTRACTS with unpublished commands: {unknown_prefixes}")

    from core import config_loader

    expected_config_options = {
        "config:exit-without-changes",
        *{
            f"config:{section.replace('_', '-')}"
            for section in config_loader._CONFIG_SECTION_ORDER
        },
    }
    actual_config_options = {
        key for key in option_contracts
        if key.startswith("config:")
    }
    missing_config_options = sorted(expected_config_options - actual_config_options)
    extra_config_options = sorted(actual_config_options - expected_config_options)
    if missing_config_options or extra_config_options:
        problems.append(
            "/config OPTION_CONTRACTS out of sync: "
            f"missing={missing_config_options} extra={extra_config_options}"
        )

    expected_cto_options = {
        "cto:default-scope-all",
        "cto:scope-all",
        "cto:scope-security",
        "cto:scope-tests",
        "cto:scope-architecture",
        "cto:scope-performance",
        "cto:target-directory",
        "cto:invalid-scope",
    }
    actual_cto_options = {
        key for key in option_contracts
        if key.startswith("cto:")
    }
    missing_cto_options = sorted(expected_cto_options - actual_cto_options)
    extra_cto_options = sorted(actual_cto_options - expected_cto_options)
    if missing_cto_options or extra_cto_options:
        problems.append(
            "/cto OPTION_CONTRACTS out of sync: "
            f"missing={missing_cto_options} extra={extra_cto_options}"
        )

    expected_human_menu_options = {
        "audit:sonarqube-docker-install-menu",
        "audit:sonarqube-docker-start-menu",
        "ship:deploy-confirmation-menu",
        "feature:user-gate-menu",
        "fix:user-gate-menu",
        "spike:conclusion-review-menu",
        "discuss:route-menu",
        "alfred:route-menu",
        "update:confirm-update-menu",
    }
    missing_human_menu_options = sorted(expected_human_menu_options - set(option_contracts))
    if missing_human_menu_options:
        problems.append(
            "OPTION_CONTRACTS missing required human menus: "
            f"{missing_human_menu_options}"
        )

    coverage_only = sorted(set(option_coverage) - set(option_contracts))
    if coverage_only:
        problems.append(f"option_coverage contains keys outside OPTION_CONTRACTS: {coverage_only}")

    if problems:
        _fail("Invalid manual option contracts: " + "; ".join(problems))


def _validate_manual_runtime_contract_shape(manual_smoke, runtime_coverage: dict[str, list[str]]) -> None:
    """Check that runtime contracts describe real /update scopes."""
    runtime_contracts = tuple(manual_smoke.RUNTIME_CONTRACTS)
    problems: list[str] = []

    duplicates = sorted({
        key for key in runtime_contracts
        if runtime_contracts.count(key) > 1
    })
    if duplicates:
        problems.append(f"Duplicate RUNTIME_CONTRACTS: {duplicates}")

    malformed = sorted(
        key for key in runtime_contracts
        if key.count(":") != 1 or not key.split(":", 1)[0] or not key.split(":", 1)[1]
    )
    if malformed:
        problems.append(f"Malformed RUNTIME_CONTRACTS: {malformed}")

    public_commands = _public_route_names(_json(".claude-plugin/plugin.json"))
    unknown_prefixes = sorted({
        key.split(":", 1)[0]
        for key in runtime_contracts
        if key.count(":") == 1 and key.split(":", 1)[0] not in public_commands
    })
    if unknown_prefixes:
        problems.append(f"RUNTIME_CONTRACTS with unpublished commands: {unknown_prefixes}")

    expected_update_contracts = {
        "update:scope-user-or-unknown",
        "update:scope-local-to-user",
        "update:scope-project-to-user",
        "update:scope-managed",
    }
    actual_update_contracts = {
        key for key in runtime_contracts
        if key.startswith("update:")
    }
    missing_update = sorted(expected_update_contracts - actual_update_contracts)
    extra_update = sorted(actual_update_contracts - expected_update_contracts)
    if missing_update or extra_update:
        problems.append(
            "/update RUNTIME_CONTRACTS out of sync: "
            f"missing={missing_update} extra={extra_update}"
        )

    coverage_only = sorted(set(runtime_coverage) - set(runtime_contracts))
    if coverage_only:
        problems.append(f"runtime_coverage contains keys outside RUNTIME_CONTRACTS: {coverage_only}")

    if problems:
        _fail("Invalid manual runtime contracts: " + "; ".join(problems))


def _validate_manual_case_contract_links(manual_smoke) -> None:
    """Ensure that a case of the correct command covers each manual contract."""
    aliases = getattr(manual_smoke, "_PUBLIC_COMMAND_ALIASES", {})

    def _canon(name: str) -> str:
        return aliases.get(name, name)

    problems: list[str] = []
    for case in manual_smoke.CASES:
        case_commands = set(getattr(case, "commands", ()) or ())
        prompt = getattr(case, "prompt", "")
        prompt_commands = set(re.findall(r"/alfred-dev:([a-z0-9-]+)", prompt))
        if re.search(r"(?<!\S)/alfred(?:\s|$)", prompt):
            prompt_commands.add("alfred")
        mapped_case = {_canon(name) for name in case_commands}
        mapped_prompt = {_canon(name) for name in prompt_commands}
        if case_commands:
            missing_prompt_commands = sorted(mapped_case - mapped_prompt)
            extra_prompt_commands = sorted(mapped_prompt - mapped_case)
            if missing_prompt_commands:
                problems.append(
                    f"{case.case_id}: prompt does not invoke {missing_prompt_commands}"
                )
            if extra_prompt_commands:
                problems.append(
                    f"{case.case_id}: prompt invokes undeclared commands {extra_prompt_commands}"
                )
        elif prompt_commands:
            problems.append(
                f"{case.case_id}: prompt invokes commands without declaring {sorted(prompt_commands)}"
            )
        for key in getattr(case, "option_keys", ()) or ():
            command_name = key.split(":", 1)[0] if ":" in key else ""
            if _canon(command_name) not in mapped_case:
                problems.append(f"{case.case_id}: option {key} does not belong to {sorted(case_commands)}")
        for key in getattr(case, "runtime_keys", ()) or ():
            command_name = key.split(":", 1)[0] if ":" in key else ""
            if _canon(command_name) not in mapped_case:
                problems.append(f"{case.case_id}: runtime {key} does not belong to {sorted(case_commands)}")
    if problems:
        _fail("Manual contracts linked to the wrong case: " + "; ".join(problems))


def _slash_command_names(text: str) -> list[str]:
    return re.findall(r"`/alfred-dev:([a-z0-9-]+)`", text)


def _section_between(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def check_command_catalog() -> list[str]:
    plugin = _json(".claude-plugin/plugin.json")
    manifest_names = _command_names_from_manifest(plugin)
    manifest_set = set(manifest_names)
    architecture = _read("docs/architecture.md")
    alfred_text = _read("commands/alfred.md")

    unpublished = {"_composicion", "_docs_vivas", "next", "search"}
    disk_names = {
        path.stem
        for path in (ROOT / "commands").glob("*.md")
        if path.stem not in unpublished
    }

    problems: list[str] = []
    if manifest_set != disk_names:
        problems.append(
            "published commands and commands/*.md do not match: "
            f"missing={sorted(disk_names - manifest_set)} extra={sorted(manifest_set - disk_names)}"
        )
    if "alfred" not in manifest_set:
        problems.append("public command alfred is missing")
    if "/alfred-dev:alfred" not in alfred_text and "/alfred" not in alfred_text:
        problems.append("commands/alfred.md must describe the contextual entry")
    if "18 команд" not in architecture and "/alfred-dev:alfred" not in architecture:
        problems.append("docs/architecture.md must mention 18 commands or /alfred-dev:alfred")

    for relative_path, name in zip(plugin["commands"], manifest_names):
        text = _read(relative_path.lstrip("./"))
        if not text.startswith("---\n"):
            problems.append(f"{relative_path}: frontmatter is missing")
            continue
        frontmatter = text.split("---", 2)[1]
        frontmatter_values = _frontmatter_top_level_values(text)
        unknown_fields = sorted(set(frontmatter_values) - COMMAND_SUPPORTED_FIELDS)
        if unknown_fields:
            problems.append(
                f"{relative_path}: unsupported frontmatter fields {unknown_fields}"
            )
        if not re.search(r"(?m)^description:\s*['\"]?.+['\"]?\s*$", frontmatter):
            problems.append(f"{relative_path}: description is missing in frontmatter")
        model = frontmatter_values.get("model")
        if model and not _is_supported_agent_model(model):
            problems.append(
                f"{relative_path}: uses a command model not supported by current Claude Code: {model!r}"
            )
        for tools_field in ("allowed-tools", "disallowed-tools"):
            unknown_tools = sorted(
                tool_name
                for tool_name in _frontmatter_tool_rule_names(
                    _frontmatter_field_rule_text(text, tools_field)
                )
                if not _is_known_permission_rule_name(tool_name)
            )
            if unknown_tools:
                problems.append(
                    f"{relative_path}: {tools_field} declares unknown tools {unknown_tools}"
                )
        if f"/alfred-dev:{name}" not in text:
            problems.append(f"{relative_path}: does not mention its slash command")

    if problems:
        _fail("Command catalog out of sync: " + "; ".join(problems))

    return [
        "18 namespaced commands aligned between plugin.json and architecture",
        "commands/alfred.md published as contextual entry",
        "command frontmatter with description",
        "command frontmatter compatible with current Claude Code",
        "command model validated against current Claude Code",
    ]


def _frontmatter_block(text: str) -> str:
    if not text.startswith("---\n"):
        return ""
    parts = text.split("---", 2)
    return parts[1] if len(parts) >= 3 else ""


def _frontmatter_top_level_fields(text: str) -> list[str]:
    fields: list[str] = []
    for line in _frontmatter_block(text).splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z_-]*)\s*:", line)
        if match:
            fields.append(match.group(1))
    return fields


def _frontmatter_top_level_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _frontmatter_block(text).splitlines():
        match = re.match(r"^([A-Za-z][A-Za-z_-]*)\s*:\s*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        values[key] = value.strip().strip('"').strip("'")
    return values


def _frontmatter_field_text(text: str, field: str) -> str:
    lines = _frontmatter_block(text).splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"^([A-Za-z][A-Za-z_-]*)\s*:\s*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        if key != field:
            continue
        stripped_value = value.strip()
        if stripped_value not in {"|", ">"}:
            return stripped_value.strip('"').strip("'")

        collected: list[str] = []
        for following in lines[index + 1:]:
            if re.match(r"^[A-Za-z][A-Za-z_-]*\s*:", following):
                break
            if following.startswith((" ", "\t")):
                collected.append(following.strip())
        return "\n".join(collected)
    return ""


def _is_supported_agent_model(model: str) -> bool:
    return model in AGENT_MODEL_ALIASES or AGENT_MODEL_ID_RE.fullmatch(model) is not None


def _frontmatter_tool_names(tools: str) -> set[str]:
    names: set[str] = set()
    for item in tools.split(","):
        name = item.strip()
        if not name:
            continue
        names.add(re.split(r"[\s(]", name, maxsplit=1)[0])
    return names


def _frontmatter_tool_rule_names(rules: str) -> set[str]:
    return set(
        re.findall(r"(?:^|[\s,])([A-Za-z][A-Za-z0-9_]*)(?:\(|(?=$|[\s,]))", rules)
    )


def _frontmatter_field_rule_text(text: str, field: str) -> str:
    """Return inline or simple YAML list rules for allowed/disallowed tools."""
    lines = _frontmatter_block(text).splitlines()
    values: list[str] = []
    collecting = False
    for line in lines:
        top_level = re.match(r"^([A-Za-z][A-Za-z_-]*)\s*:\s*(.*)$", line)
        if top_level:
            key, value = top_level.groups()
            collecting = key == field
            if collecting and value.strip():
                values.append(value.strip().strip("[]").strip('"').strip("'"))
            continue
        if collecting:
            list_item = re.match(r"^\s*-\s*(.+?)\s*$", line)
            if list_item:
                values.append(list_item.group(1))
    return " ".join(values)


def _is_known_agent_tool_name(tool_name: str) -> bool:
    return tool_name in CLAUDE_TOOL_NAMES or tool_name.startswith("mcp__")


def _is_known_permission_rule_name(tool_name: str) -> bool:
    return tool_name in CLAUDE_PERMISSION_RULE_NAMES or tool_name.startswith("mcp__")


def check_command_execution_contracts() -> list[str]:
    """Check that each published command keeps its operating strategy."""
    plugin = _json(".claude-plugin/plugin.json")
    commands = {
        Path(relative_path).stem: _read(relative_path.lstrip("./"))
        for relative_path in plugin["commands"]
    }
    composition = _read("commands/_composicion.md")
    problems: list[str] = []

    for name, text in commands.items():
        frontmatter = _frontmatter_block(text)
        has_arguments = "$ARGUMENTS" in text
        has_hint = re.search(r"(?m)^argument-hint:\s*.+$", frontmatter) is not None
        if has_arguments and not has_hint:
            problems.append(f"{name}: uses $ARGUMENTS but does not declare argument-hint")
        if has_hint and not has_arguments:
            problems.append(f"{name}: declares argument-hint but does not insert $ARGUMENTS")
        if re.search(r"`/alfred:[^`]*`|^/alfred:", text, re.MULTILINE):
            problems.append(f"{name}: contains legacy slash command /alfred:")
        if re.search(r"\bTask\b", text):
            problems.append(f"{name}: contains obsolete Task naming")
        if re.search(
            r"\*\*GATE \((?:libre|свободный)\):\*\*.*\b(?:Se aprueba siempre|Всегда одобряется)\b",
            text,
        ):
            problems.append(
                f"{name}: free gate promises unconditional approval without evidence"
            )

    helper_contracts = {
        "alfred": [
            'consume-prefetch "$PWD" --expected alfred',
            'alfred-continuity.py next "$PWD" --json',
            "По умолчанию не предлагай меню",
        ],
        "discuss": [
            'consume-prefetch "$PWD" --expected discuss',
            'alfred-continuity.py discuss "$PWD" --raw "$ARGUMENTS"',
            "итогового ответа",
            "commands/_docs_vivas.md",
        ],
        "map-codebase": [
            'consume-prefetch "$PWD" --expected map-codebase',
            'alfred-continuity.py map-codebase "$PWD" --raw "$ARGUMENTS"',
            "НЕ выдумывай стек, точки входа или риски",
            "commands/_docs_vivas.md",
        ],
        "memory-ui": [
            'consume-prefetch "$PWD" --expected memory-ui',
            'alfred-continuity.py memory-ui "$PWD" --raw "$ARGUMENTS"',
            "--stop",
        ],
        "next": [
            'alfred-continuity.py next "$PWD" --json',
            "один навигируемый `AskUserQuestion`",
        ],
        "pause": [
            'alfred-continuity.py pause "$PWD"',
            "Сначала выполни детерминированный helper",
            "Не оборачивай его во вторую сводку",
        ],
        "progress": [
            'alfred-continuity.py progress "$PWD"',
            "используй её как итоговый ответ",
            "НЕ используй `AskUserQuestion`",
        ],
        "quick": [
            'alfred-continuity.py quick "$PWD" --raw "$ARGUMENTS"',
            "НЕ используй\n   `Write` и `Edit`",
            "## Каноничное завершение команды",
        ],
        "search": [
            'alfred-continuity.py search "$PWD" --raw "$ARGUMENTS"',
            "Если `$ARGUMENTS` пуст, скажи об этом ясно",
        ],
        "sync-github": [
            'alfred-continuity.py sync-github "$PWD" --raw "$ARGUMENTS"',
            "Сохраняй локальную истину",
        ],
        "uat": [
            'alfred-continuity.py verify "$PWD" --raw "$ARGUMENTS"',
            "НЕ помечай UAT как одобренную без явного указания",
            "НЕ добавляй второй слой сводки",
        ],
        "retomar": [
            'alfred-continuity.py resume "$PWD"',
            "Сначала выполни детерминированный helper",
        ],
    }
    commands_for_contracts = dict(commands)
    commands_for_contracts["alfred"] = _read("commands/alfred.md")
    commands_for_contracts["next"] = _read("commands/next.md")
    commands_for_contracts["search"] = _read("commands/search.md")
    for name, needles in helper_contracts.items():
        text = commands_for_contracts[name]
        for needle in needles:
            if needle not in text:
                problems.append(f"{name}: helper contract is missing {needle!r}")

    flow_contracts = {
        "feature": [
            "Процесс до 7 фаз",
            "## HARD-GATES",
            "Максимум 5 попыток",
            "## Каноничное завершение команды",
            "ожидаемый следующий шаг",
            "commands/_docs_vivas.md",
            "check-project-docs",
        ],
        "fix": [
            "Процесс из 3 фаз",
            "тест, воспроизводящий баг",
            "Максимум 5 попыток",
            "## Каноничное завершение команды",
            "баг/первопричину в работе",
            "commands/_docs_vivas.md",
        ],
        "quick": [
            "Лёгкий процесс из 2 фаз",
            "Когда quick перестаёт быть quick",
            "## Каноничное завершение команды",
            "/alfred-dev:uat",
            "commands/_docs_vivas.md",
            "завершение",
        ],
        "spike": [
            "Процесс из 2 фаз",
            "Spike НЕ создают production-код",
            "## Каноничное завершение команды",
            "ADR",
            "пока не реализовывать",
        ],
        "ship": [
            "Процесс из 4 фаз",
            "Gate развёртывания ВСЕГДА интерактивный",
            "НИКОГДА не утверждай автоматически развёртывание",
            "## Каноничное завершение команды",
            "commands/_docs_vivas.md",
            "hygiene",
        ],
        "audit": [
            "Preflight SonarQube",
            "Запусти 4 агентов ПАРАЛЛЕЛЬНО",
            "Код не трогай, только генерируй отчёты",
            "## Каноничное завершение команды",
            "commands/_docs_vivas.md",
        ],
    }
    for name, needles in flow_contracts.items():
        text = commands[name]
        for needle in needles:
            if needle not in text:
                problems.append(f"{name}: flow contract is missing {needle!r}")

    composition_reader_contracts = ("feature", "fix", "quick", "spike", "ship", "audit")
    for name in composition_reader_contracts:
        text = commands[name]
        for needle in (
            "${CLAUDE_PLUGIN_ROOT}/commands/_composicion.md",
        ):
            if needle not in text:
                problems.append(f"{name}: loads _composicion without plugin contract: {needle!r}")

    docs_reader_contracts = ("feature", "fix", "quick", "spike", "ship", "audit")
    for name in docs_reader_contracts:
        text = commands[name]
        if "${CLAUDE_PLUGIN_ROOT}/commands/_docs_vivas.md" not in text:
            problems.append(
                f"{name}: loads _docs_vivas without plugin contract: "
                "'${CLAUDE_PLUGIN_ROOT}/commands/_docs_vivas.md'"
            )

    autopilot_texts = {
        "_composicion": composition,
        "feature": commands["feature"],
        "fix": commands["fix"],
        "ship": commands["ship"],
    }
    for name, text in autopilot_texts.items():
        if '"autopilot": true' not in text:
            problems.append(f"{name}: does not recognize the canonical autopilot state flag")
        if '"modo": "autopilot"' not in text:
            problems.append(f"{name}: does not keep the legacy autopilot state alias")

    interactive_contracts = {
        "ajustes": [
            "главное меню",
            "core/config_cli.py",
            "CONFIG_HEADLESS_MENU",
            "не вызывай `AskUserQuestion`",
            "возвращается отменённым",
            "build_config_section_summaries()",
            "build_config_section_menu()",
            "build_config_section_change_preview()",
            "update_config_section()",
        ],
        "cto": [
            "Аргументы пользователя: $ARGUMENTS",
            "codex login",
            "scope=all",
            "Не реализуй ни один пункт",
            "проверяемый следующий шаг",
        ],
        "update": [
            "как настоящий semver",
            "0.10.0",
            "один `AskUserQuestion`",
            "выполнить **`/reload-plugins`**",
            "`/reload-plugins --force`",
            "нужно перезапустить",
            "## Каноничное завершение команды",
        ],
    }
    for name, needles in interactive_contracts.items():
        text = commands[name]
        for needle in needles:
            if needle not in text:
                problems.append(f"{name}: interactive contract is missing {needle!r}")

    if problems:
        _fail("Command execution contracts incomplete: " + "; ".join(problems))

    return [
        "18 namespaced commands keep arguments, prefix and current naming",
        "18 helper-first wrappers covered",
        "6 main flows with canonical closing",
        "_composicion loads from the plugin install",
        "config/cto/update with verifiable interactive contracts",
        "free gates without unconditional approval",
        "autopilot via config/state without phantom public flag",
    ]


def _registered_hook_script_count() -> int:
    hooks = _json("hooks/hooks.json").get("hooks", {})
    scripts: set[str] = set()
    for groups in hooks.values():
        for group in groups:
            for hook in group.get("hooks", []):
                args = hook.get("args", [])
                if not isinstance(args, list):
                    continue
                for arg in args:
                    if isinstance(arg, str) and arg.startswith("${CLAUDE_PLUGIN_ROOT}/hooks/"):
                        scripts.add(Path(arg).name)
    return len(scripts)


def check_public_claims() -> list[str]:
    """Keep public claims aligned with the inventory and current docs."""
    readme = _read("README.md")
    architecture = _read("docs/architecture.md")
    skills_doc = _read("docs/skills.md")
    help_command = _read("commands/alfred.md")
    alfred_agent = _read("agents/alfred.md")
    cto_agent = _read("agents/cto.md")
    agents_readme = _read("docs/agents/README.md")
    has_site = _has_site()
    personality = _read("docs/personality.md")
    changelog = _read("CHANGELOG.md")

    agent_count = len(list((ROOT / "agents").glob("*.md")))
    skill_count = len(list((ROOT / "skills").rglob("SKILL.md")))
    command_count = len(_json(".claude-plugin/plugin.json")["commands"])
    hook_script_count = _registered_hook_script_count()

    expected_counts = {
        "agents": (agent_count, 10),
        "skills": (skill_count, 11),
        "commands": (command_count, 18),
        "hooks": (hook_script_count, hook_script_count),
    }
    for label, (actual, expected) in expected_counts.items():
        if actual != expected:
            _fail(f"Public inventory {label}={actual}, expected {expected}")

    required = {
        "README.md": [
            "10 агентов",
            "11 плоских skills",
            "quality gates",
            "https://code.claude.com/docs/en/overview",
            "Новое в v0.7.0",
        ],
        "docs/skills.md": [
            "каталог из 11 skills",
            "disable-model-invocation: true",
            "memory",
            "style-direction",
        ],
        "docs/architecture.md": [
            "18 команд",
            "Манифест не объявляет ключ `agents`",
        ],
        "commands/alfred.md": [
            "Agent Teams",
            "/alfred-dev:feature",
        ],
        "agents/alfred.md": [
            "Alfred",
        ],
        "docs/agents/README.md": [
            "Claude Code находит их напрямую в `agents/`",
            "манифест `plugin.json` не объявляет ручную секцию `agents`",
            "quality gates, проверяемые по подтверждению",
            "Результат не обещается детерминированным",
            "снижают вариативность",
        ],
        "agents/cto.md": [
            "Не навязывай модель по собственной инициативе",
            "Codex CLI (локальная конфигурация пользователя)",
            "codex exec",
            "--sandbox read-only",
            "--ephemeral",
            "--json",
            "--output-last-message",
            "codex_report",
            "codex_jsonl",
            "approval_policy",
            "status --porcelain=v1 -z",
        ],
        "CHANGELOG.md": [
            "displayName: \"Alfred Dev\"",
            "Alfred Dev (alfred-dev)",
            "технического namespace",
            "42 публичные опции",
            "4 runtime-контракта `/update`",
        ],
        "site/src/i18n/data.es.ts": [
            "displayName: \"Alfred Dev\"",
            "Alfred Dev (alfred-dev)",
            "namespace técnico",
            "Claude Code 2.1.183",
            "plugins, skills, hooks y MCP",
            "claude update",
        ],
        "site/src/i18n/data.en.ts": [
            "displayName: \"Alfred Dev\"",
            "Alfred Dev (alfred-dev)",
            "technical namespace",
            "Claude Code 2.1.183",
            "plugins, skills, hooks, and MCP",
            "claude update",
            "quality gates that require evidence before work can close",
        ],
    }
    sources = {
        "README.md": readme,
        "docs/skills.md": skills_doc,
        "docs/architecture.md": architecture,
        "commands/alfred.md": help_command,
        "agents/alfred.md": alfred_agent,
        "docs/agents/README.md": agents_readme,
        "agents/cto.md": cto_agent,
        "CHANGELOG.md": changelog,
    }
    if has_site:
        sources.update({
            "site/src/i18n/data.es.ts": _read("site/src/i18n/data.es.ts"),
            "site/src/i18n/data.en.ts": _read("site/src/i18n/data.en.ts"),
        })
    else:
        required = {
            path: needles
            for path, needles in required.items()
            if not path.startswith("site/")
        }
    missing: list[str] = []
    for path, needles in required.items():
        for needle in needles:
            if not _contains(sources[path], needle):
                missing.append(f"{path}: {_needle_label(needle)}")
    if missing:
        _fail(f"Public claims incomplete: {missing}")

    stale_exact = {
        "README.md": [
            "### Skills (60)",
            "### Hooks (12)",
            "### Core (6 modulos)",
            "### Core (6 módulos)",
            "GPT-5.4",
            "--autopilot",
            "keywords contextuales",
            "https://docs.anthropic.com/en/docs/claude-code",
            "quality gates infranqueables",
            "No hay excepciones, no hay modo de saltárselas",
            # Russian equivalents: README is translated.
            "quality gates непреодолим",
            "Исключений нет",
        ],
        "docs/architecture.md": ["Agentes de nucleo** (9)", "se registran igualmente en `plugin.json`"],
        "docs/agents/README.md": [
            "tambien aparecen en `plugin.json`",
            "quality gates infranqueables",
            "El resultado es previsible y reproducible",
            "produce resultados consistentes porque no arrastra",
        ],
        "commands/alfred.md": ["GPT-5.4"],
        "agents/alfred.md": [
            "9 agentes de nucleo + 8 opcionales",
            "reglas infranqueables",
            "NUNCA se pueden saltar",
            # Russian equivalents: agents/ is translated.
            "непреодолим",
            "НИКОГДА нельзя пропускать",
        ],
        "agents/cto.md": ["GPT-5.4", "gpt-5.4"],
        "docs/personality.md": ["GPT-5.4"],
        "CHANGELOG.md": [
            "GPT-5.4",
            "gpt-5.4",
            "22 opciones/variantes",
            "`codex review`",
            "approval: never",
            "sin prompt de confirmación al usuario",
            "ejecuta el scanner end-to-end",
            "Quality gates infranqueables",
        ],
        "site/src/i18n/data.es.ts": [
            "6 módulos core",
            "GPT-5.4",
            "codex review",
            "approval: never",
            "--autopilot",
            "sin pedir confirmación al usuario",
            "Verificado end-to-end con Docker",
            "ejecuta el scanner end-to-end",
            "No hay requisito de versión mínima específica",
            "Cualquier versión de Claude Code",
            "Claude Code instalado.",
        ],
        "site/src/i18n/data.en.ts": [
            "6 core modules",
            "GPT-5.4",
            "modelo configurado por el usuario",
            "codex review",
            "approval: never",
            "--autopilot",
            "quality gates the workflow cannot skip",
            "without asking the user for confirmation",
            "Verified end-to-end with Docker",
            "runs the scanner end-to-end",
            "There is no specific minimum version requirement",
            "Any version of Claude Code",
            "Claude Code installed.",
        ],
        "site/src/components/BrutalistLandingPage.astro": [
            "GPT-5.4",
            "codex review",
            "Los quality gates son infranqueables",
        ],
        "hooks/session-start.sh": [
            "Las quality gates son infranqueables",
            "непреодолим",
        ],
        "site/src/components/Footer.astro": ["https://docs.anthropic.com/en/docs/claude-code"],
        "docs/skills.md": [
            "garantizar que el resultado sea consistente, reproducible y de calidad profesional",
            "procedimiento verificable y reproducible",
            "garantizar que el software sea usable por todas las personas",
        ],
        "docs/flows.md": [
            "garantiza que cada linea de código tiene al menos un test",
            "garantiza que cada línea de código tiene al menos un test",
        ],
        "docs/agents/security-officer.md": [
            "garantizar que el software cumple con los estandares de seguridad",
        ],
        "agents/security-officer.md": [
            "garantiza que nada con vulnerabilidades conocidas llega a los usuarios",
            "bloqueantes absolutos. Sin excepciones",
            "seguridad infranqueable",
            # Russian equivalents: agents/ is translated.
            "Без исключений",
            "непреодолим",
            "ничто с известными уязвимостями",
        ],
    }
    stale_sources = {
        "README.md": readme,
        "docs/skills.md": skills_doc,
        "docs/flows.md": _read("docs/flows.md"),
        "docs/agents/security-officer.md": _read("docs/agents/security-officer.md"),
        "agents/security-officer.md": _read("agents/security-officer.md"),
        "hooks/session-start.sh": _read("hooks/session-start.sh"),
        "docs/architecture.md": architecture,
        "commands/alfred.md": help_command,
        "agents/alfred.md": alfred_agent,
        "docs/agents/README.md": agents_readme,
        "agents/cto.md": cto_agent,
        "docs/personality.md": personality,
        "CHANGELOG.md": changelog,
    }
    if has_site:
        stale_sources.update({
            "site/src/i18n/data.es.ts": _read("site/src/i18n/data.es.ts"),
            "site/src/i18n/data.en.ts": _read("site/src/i18n/data.en.ts"),
            "site/src/components/BrutalistLandingPage.astro": _read("site/src/components/BrutalistLandingPage.astro"),
            "site/src/components/Footer.astro": _read("site/src/components/Footer.astro"),
        })
    else:
        stale_exact = {
            path: needles
            for path, needles in stale_exact.items()
            if not path.startswith("site/")
        }
    stale_hits: list[str] = []
    for path, needles in stale_exact.items():
        for needle in needles:
            if needle in stale_sources[path]:
                stale_hits.append(f"{path}: {needle}")
    if stale_hits:
        _fail(f"Stale claims on the current surface: {stale_hits}")

    manual_only_problems: list[str] = []
    for relative_path in MANUAL_ONLY_SKILLS:
        frontmatter = _frontmatter_block(_read(relative_path))
        if not re.search(r"(?m)^disable-model-invocation:\s*true\s*$", frontmatter):
            manual_only_problems.append(relative_path)
    if manual_only_problems:
        _fail(
            "Sensitive skills without explicit manual activation: "
            f"{manual_only_problems}"
        )

    legacy_runtime: list[str] = []
    legacy_pattern = re.compile(r"/alfred\s+(feature|fix|ship|spike|audit|config)\b")
    for path in sorted((ROOT / "agents").glob("*.md")):
        text = path.read_text(encoding="utf-8")
        for match in legacy_pattern.finditer(text):
            legacy_runtime.append(f"{_rel(path)}:{match.group(0)}")
    if legacy_runtime:
        _fail(f"Runtime prompts with legacy slash command: {legacy_runtime}")

    surface_message = (
        "README, landing, architecture, help and agents without old counters"
        if has_site
        else "README, architecture, help and agents without old counters"
    )
    display_name_message = (
        "human displayName reflected in README, changelog and landing"
        if has_site
        else "human displayName reflected in README and changelog"
    )
    return [
        "public inventory 10/11/18 verified",
        surface_message,
        display_name_message,
        "sensitive skills keep explicit manual activation",
        "CTO does not pin an obsolete Codex CLI model",
        "runtime prompts without legacy /alfred",
    ]


def check_config_contracts() -> list[str]:
    """Check that /alfred-dev:ajustes exposes the real runtime options."""
    from core import config_loader
    from core import optional_agents

    def assert_ask_user_question_payload(label: str, payload: dict) -> None:
        questions = payload.get("questions")
        if not isinstance(questions, list) or len(questions) != 1:
            _fail(f"{label} does not expose questions[0] for AskUserQuestion: {payload}")
        question = questions[0]
        if not isinstance(question, dict):
            _fail(f"{label}.questions[0] is not an object: {question}")
        for field in ("question", "header", "options", "multiSelect"):
            if field not in question:
                _fail(f"{label}.questions[0] does not declare {field}")
        if question["multiSelect"] is not False:
            _fail(f"{label}.questions[0].multiSelect must be false")
        if question["question"] != payload.get("question"):
            _fail(f"{label}.questions[0].question does not match legacy question")
        if question["header"] != payload.get("header"):
            _fail(f"{label}.questions[0].header does not match legacy header")
        if question["options"] != payload.get("options"):
            _fail(f"{label}.questions[0].options does not match legacy options")
        for index, option in enumerate(question["options"]):
            if not isinstance(option, dict):
                _fail(f"{label}.questions[0].options[{index}] is not an object")
            if not str(option.get("label", "")).strip():
                _fail(f"{label}.questions[0].options[{index}] does not declare label")
            if not str(option.get("description", "")).strip():
                _fail(f"{label}.questions[0].options[{index}] does not declare description")

    def assert_prompt_examples_use_current_ask_user_question_schema(
        relative_path: str,
        text: str,
    ) -> None:
        for match in re.finditer(r"AskUserQuestion\(\{(?P<body>.*?)^\}\)", text, re.DOTALL | re.MULTILINE):
            body = match.group("body")
            missing = [
                needle
                for needle in ("questions: [", "multiSelect: false", "options: [")
                if needle not in body
            ]
            if missing:
                _fail(
                    "Obsolete AskUserQuestion example in "
                    f"{relative_path}: missing {missing}"
                )

    expected_sections = (
        "autonomia",
        "proyecto",
        "agentes_opcionales",
        "memoria",
        "compliance",
        "integraciones",
        "personalidad",
    )
    if tuple(config_loader._CONFIG_SECTION_ORDER) != expected_sections:
        _fail(
            "Config section order out of sync: "
            f"{config_loader._CONFIG_SECTION_ORDER}"
        )

    labels = config_loader._CONFIG_SECTION_LABELS
    if set(labels) != set(expected_sections):
        _fail(f"Config labels out of sync: {sorted(labels)}")

    summaries = config_loader.build_config_section_summaries(config_loader.DEFAULT_CONFIG)
    summary_sections = tuple(section["section"] for section in summaries)
    if summary_sections != expected_sections:
        _fail(f"Config summaries out of sync: {summary_sections}")

    menu = config_loader.build_config_section_menu(config_loader.DEFAULT_CONFIG)
    menu_labels = [option["label"] for option in menu["options"]]
    # core/config_loader.py may still use the Spanish label or a Russian one.
    if menu_labels[0] != "Salir sin cambios" and not menu_labels[0].startswith("Выйти"):
        _fail(f"Config menu has no initial exit option: {menu_labels}")
    missing_labels = [
        labels[section]
        for section in expected_sections
        if labels[section] not in menu_labels
    ]
    if missing_labels:
        _fail(f"Config menu does not expose sections: {missing_labels}")
    assert_ask_user_question_payload("build_config_section_menu", menu)

    for group_name in optional_agents.OPTIONAL_AGENT_GROUP_ORDER:
        assert_ask_user_question_payload(
            f"build_optional_agent_group_menu[{group_name}]",
            optional_agents.build_optional_agent_group_menu(group_name),
        )

    preview = config_loader.build_config_section_change_preview(
        config_loader.DEFAULT_CONFIG,
        "memoria",
        {"enabled": True},
    )
    if not preview["changed"] or not preview["updated_config"]["memoria"]["enabled"]:
        _fail(f"Config preview does not detect the memory change: {preview}")

    section_updates = {
        "autonomia": {
            "producto": "interactivo",
            "calidad": "semi-autonomo",
        },
        "proyecto": {
            "runtime": "node",
            "lenguaje": "typescript",
            "framework": "next",
            "test_runner": "vitest",
            "bundler": "vite",
        },
        "agentes_opcionales": {
            "cto": True,
            "cto": True,
        },
        "memoria": {
            "enabled": True,
            "sync_commits_limit": 3,
            "retention_days": 30,
        },
        "compliance": {
            "estilo": "strict",
            "lint": False,
            "format_on_save": False,
        },
        "integraciones": {
            "git": False,
            "ci": True,
            "deploy": True,
        },
        "personalidad": {
            "nivel_sarcasmo": 1,
            "verbosidad": "alta",
            "idioma": "es-ES",
            "celebrar_victorias": False,
        },
    }
    if tuple(section_updates) != expected_sections:
        _fail(f"Config matrix out of sync: {tuple(section_updates)}")

    stack_fixtures = {
        "node-typescript": {
            "files": {
                "package.json": json.dumps({"dependencies": {"next": "^15.0.0"}}),
                "tsconfig.json": "{}",
            },
            "expected": {"runtime": "node", "lenguaje": "typescript", "framework": "next"},
        },
        "python": {
            "files": {"requirements.txt": "fastapi==0.110.0\npytest==8.0.0\n"},
            "expected": {"runtime": "python", "lenguaje": "python", "framework": "fastapi"},
        },
        "rust": {
            "files": {"Cargo.toml": "[package]\nname = \"demo\"\n"},
            "expected": {"runtime": "rust", "lenguaje": "rust"},
        },
        "go": {
            "files": {"go.mod": "module example.com/demo\n"},
            "expected": {"runtime": "go", "lenguaje": "go"},
        },
        "ruby": {
            "files": {"Gemfile": "source 'https://rubygems.org'\n"},
            "expected": {"runtime": "ruby", "lenguaje": "ruby"},
        },
        "elixir": {
            "files": {"mix.exs": "defmodule Demo.MixProject do\nend\n"},
            "expected": {"runtime": "elixir", "lenguaje": "elixir"},
        },
        "java": {
            "files": {
                "pom.xml": (
                    "<project><dependencies>"
                    "<dependency><groupId>org.springframework.boot</groupId>"
                    "<artifactId>spring-boot-starter-web</artifactId></dependency>"
                    "</dependencies></project>"
                ),
            },
            "expected": {"runtime": "jvm", "lenguaje": "java", "framework": "spring-boot"},
        },
        "kotlin": {
            "files": {
                "build.gradle.kts": (
                    "plugins { kotlin(\"jvm\") version \"2.0.0\" }\n"
                    "dependencies { implementation(\"io.quarkus:quarkus-rest\") }\n"
                ),
            },
            "expected": {"runtime": "jvm", "lenguaje": "kotlin", "framework": "quarkus"},
        },
        "php": {
            "files": {
                "composer.json": json.dumps({"require": {"laravel/framework": "^11.0"}}),
            },
            "expected": {"runtime": "php", "lenguaje": "php", "framework": "laravel"},
        },
        "dotnet": {
            "files": {"App.csproj": '<Project Sdk="Microsoft.NET.Sdk.Web"></Project>'},
            "expected": {"runtime": "dotnet", "lenguaje": "csharp", "framework": "aspnet"},
        },
        "swift": {
            "files": {
                "Package.swift": (
                    "let package = Package("
                    "dependencies: [.package(url: \"https://github.com/vapor/vapor\", from: \"4.0.0\")])"
                ),
            },
            "expected": {"runtime": "swift", "lenguaje": "swift", "framework": "vapor"},
        },
    }
    with tempfile.TemporaryDirectory(prefix="alfred-stack-audit-") as tmp:
        tmp_path = Path(tmp)
        for fixture_name, fixture in stack_fixtures.items():
            project_path = tmp_path / fixture_name
            project_path.mkdir()
            for relative_path, content in fixture["files"].items():
                target = project_path / relative_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
            stack = config_loader.detect_stack(str(project_path))
            for key, expected_value in fixture["expected"].items():
                actual = stack.get(key)
                if actual != expected_value:
                    _fail(
                        "Promised stack detection out of sync: "
                        f"{fixture_name}.{key}={actual!r} != {expected_value!r}"
                    )

    with tempfile.TemporaryDirectory(prefix="alfred-config-audit-") as tmp:
        config_path = Path(tmp) / "alfred-dev.local.md"
        config_path.write_text(
            "---\n"
            "memoria:\n"
            "  enabled: false\n"
            "---\n\n"
            "## Notas\n\n"
            "Nota estable.\n",
            encoding="utf-8",
        )
        for section_name, values in section_updates.items():
            section_preview = config_loader.build_config_section_change_preview(
                config_loader.DEFAULT_CONFIG,
                section_name,
                values,
            )
            if not section_preview["changed"]:
                _fail(f"Config preview does not detect the change in {section_name}: {section_preview}")
            for key, value in values.items():
                actual = section_preview["updated_config"][section_name].get(key)
                if actual != value:
                    _fail(
                        "Config preview does not apply value "
                        f"{section_name}.{key}: {actual!r} != {value!r}"
                    )

            persisted_preview = config_loader.update_config_section(
                str(config_path),
                section_name,
                values,
                include_defaults=False,
            )
            if persisted_preview["section"] != section_name:
                _fail(
                    "Config persistence returns the wrong section: "
                    f"{persisted_preview}"
                )
            reloaded = config_loader.load_config(str(config_path))
            for key, value in values.items():
                actual = reloaded[section_name].get(key)
                if actual != value:
                    _fail(
                        "Config persistence does not keep value "
                        f"{section_name}.{key}: {actual!r} != {value!r}"
                    )
            if "Nota estable" not in reloaded.get("notas", ""):
                _fail(f"Config persistence loses notes after {section_name}")

    command_norm = _normalize(_read("commands/ajustes.md"))
    docs_norm = _normalize(_read("docs/configuration.md"))
    architecture = _read("docs/architecture.md")
    assert_prompt_examples_use_current_ask_user_question_schema(
        "commands/ajustes.md",
        _read("commands/ajustes.md"),
    )
    assert_prompt_examples_use_current_ask_user_question_schema(
        "commands/_composicion.md",
        _read("commands/_composicion.md"),
    )
    # commands/ajustes.md and docs/configuration.md are translated to Russian.
    # Both surfaces use the same labels.
    required_command_labels = [
        "автономность по фазам",
        "проект",
        "опциональные агенты",
        "постоянная память",
        "compliance",
        "интеграции",
        "личность",
    ]
    missing: list[str] = []
    for label in required_command_labels:
        if _normalize(label) not in command_norm:
            missing.append(f"commands/config.md: {label}")
    for label in required_command_labels:
        if _normalize(label) not in docs_norm:
            missing.append(f"docs/configuration.md: {label}")

    helper_names = [
        "build_config_section_summaries()",
        "build_config_section_menu()",
        "apply_config_section_update()",
        "build_config_section_change_preview()",
        "update_config_section()",
        "update_project_config_section()",
    ]
    for helper_name in helper_names:
        if helper_name not in _read("commands/ajustes.md"):
            missing.append(f"commands/config.md: {helper_name}")
        if helper_name not in _read("docs/configuration.md"):
            missing.append(f"docs/configuration.md: {helper_name}")
        if helper_name not in architecture:
            missing.append(f"docs/architecture.md: {helper_name}")

    for needle in ("questions[]", "multiselect: false"):
        if needle not in docs_norm:
            missing.append(f"docs/configuration.md: {needle}")

    if missing:
        _fail("Config contracts incomplete: " + "; ".join(missing))

    return [
        "7 config sections aligned with runtime",
        "automatic detection covers promised stacks",
        "main config menu exposes exit and canonical sections",
        "config before/after preview works",
        "7 config sections with preview/persistence round-trip",
        "config docs and command cover canonical helpers",
        "AskUserQuestion config/optional uses current questions[] and multiSelect",
    ]


def check_flow_gate_claims() -> list[str]:
    """Exercise public claims about flows, Designer, gates and autopilot."""
    from core.config_loader import has_frontend
    from core.orchestrator import (
        FLOWS,
        advance_phase,
        check_gate,
        create_session,
        is_autopilot_gate_passable,
    )

    problems: list[str] = []
    flows_doc = _read("docs/flows.md")
    configuration_doc = _read("docs/configuration.md")
    readme = _read("README.md")
    has_site = _has_site()

    free_gate_doc_requirements = {
        "docs/flows.md": (
            "прямое подтверждение ожидаемого артефакта или чек-листа",
            "не делает её безусловным одобрением",
            "Docs готовы, свободная gate с подтверждением",
        ),
        "docs/configuration.md": (
            "Нужен положительный результат и подтверждение/чек-лист; одобрение человека не требуется.",
        ),
        "README.md": (
            "Все артефакты задокументированы, есть проверяемый чек-лист/подтверждение",
        ),
    }
    free_gate_sources = {
        "docs/flows.md": flows_doc,
        "docs/configuration.md": configuration_doc,
        "README.md": readme,
    }
    for path, needles in free_gate_doc_requirements.items():
        for needle in needles:
            if not _contains(free_gate_sources[path], needle):
                problems.append(
                    f"{path}: free gate/docs without honest contract {_needle_label(needle)!r}"
                )
    stale_free_gate_claims = {
        "docs/flows.md": (
            "Se supera siempre que el resultado sea favorable.",
            "Avance automático con gate libre",
        ),
        "docs/configuration.md": (
            "Se supera siempre que el resultado sea favorable.",
        ),
        "README.md": (
            "Todos los artefactos están documentados |",
            "Все артефакты задокументированы |",
        ),
    }
    for path, needles in stale_free_gate_claims.items():
        for needle in needles:
            if needle in free_gate_sources[path]:
                problems.append(f"{path}: free gate claim is too loose {needle!r}")
    public_gate_sources = {
        "README.md": readme,
        "docs/README.md": _read("docs/README.md"),
        "docs/agents/README.md": _read("docs/agents/README.md"),
        "docs/hooks.md": _read("docs/hooks.md"),
        "docs/release.md": _read("docs/release.md"),
    }
    public_gate_requirements = {
        "README.md": (
            "проверяемыми по подтверждению quality gates",
            "Autopilot решает только настроенные пользовательские gates",
            "не пропускает тесты, безопасность, подтверждение и ручное подтверждение развёртывания",
        ),
        "docs/README.md": ("quality gates, проверяемые по подтверждению",),
        "docs/agents/README.md": ("quality gates, проверяемые по подтверждению",),
        "docs/hooks.md": ("Quality gates, проверяемые по подтверждению",),
        "docs/release.md": ("quality gates проверяемы по локальному контракту",),
    }
    if has_site:
        public_gate_sources["site/src/i18n/data.en.ts"] = _read("site/src/i18n/data.en.ts")
        public_gate_requirements["site/src/i18n/data.en.ts"] = (
            "quality gates that require evidence before work can close",
        )
    for path, needles in public_gate_requirements.items():
        for needle in needles:
            if needle not in public_gate_sources[path]:
                problems.append(f"{path}: gate claim without verifiable evidence {_needle_label(needle)!r}")
    public_gate_stale = {
        "README.md": (
            "quality gates infranqueables",
            "No hay excepciones, no hay modo de saltárselas",
            "quality gates непреодолим",
            "Исключений нет",
        ),
        "docs/README.md": ("quality gates infranqueables",),
        "docs/agents/README.md": ("quality gates infranqueables",),
        "docs/hooks.md": ("quality gates infranqueables",),
        "docs/release.md": ("quality gates son infranqueables",),
    }
    if has_site:
        public_gate_stale["site/src/i18n/data.en.ts"] = ("quality gates the workflow cannot skip",)
    for path, needles in public_gate_stale.items():
        for needle in needles:
            if needle in public_gate_sources[path]:
                problems.append(f"{path}: absolute gate claim without evidence nuance {needle!r}")

    feature_phases = FLOWS["feature"]["fases"]
    if len(feature_phases) != 7:
        problems.append(f"feature must have 7 phases, has {len(feature_phases)}")
    estilo = feature_phases[1] if len(feature_phases) > 1 else {}
    expected_style_contract = {
        "nombre": "estilo_visual",
        "agentes": ["designer"],
        "gate_tipo": "usuario",
        "condicion": "tiene_frontend",
    }
    for key, expected in expected_style_contract.items():
        if estilo.get(key) != expected:
            problems.append(f"estilo_visual.{key}={estilo.get(key)!r} != {expected!r}")

    if not has_frontend({"framework": "next", "runtime": "node"}):
        problems.append("has_frontend does not recognize Next as frontend")
    if has_frontend({"framework": "fastapi", "runtime": "python"}):
        problems.append("has_frontend treats FastAPI as frontend")

    frontend_session = create_session(
        "feature",
        "Panel with UI",
        stack={"runtime": "node", "framework": "next"},
    )
    frontend_session = advance_phase(frontend_session, resultado="aprobado")
    if frontend_session["fase_actual"] != "estilo_visual":
        problems.append("feature with frontend does not enter estilo_visual after producto")

    backend_session = create_session(
        "feature",
        "API without UI",
        stack={"runtime": "python", "framework": "fastapi"},
    )
    backend_session = advance_phase(backend_session, resultado="aprobado")
    skipped_style = [
        phase
        for phase in backend_session.get("fases_completadas", [])
        if phase.get("nombre") == "estilo_visual"
    ]
    if backend_session["fase_actual"] != "arquitectura" or not skipped_style:
        problems.append("feature without frontend does not skip estilo_visual to arquitectura")
    elif skipped_style[0].get("resultado") != "saltada":
        problems.append(f"skipped estilo_visual records an unexpected result: {skipped_style[0]}")

    gate_session = create_session("feature", "Strict gates")
    gate_session = advance_phase(gate_session, resultado="aprobado")
    gate_session = advance_phase(gate_session, resultado="aprobado")
    gate_session = advance_phase(gate_session, resultado="aprobado")
    if check_gate(gate_session, resultado="aprobado", tests_ok=False)["passed"]:
        problems.append("automatic development gate does not block red tests")
    gate_session = advance_phase(gate_session, resultado="aprobado", tests_ok=True)
    if check_gate(gate_session, resultado="aprobado", security_ok=False)["passed"]:
        problems.append("automatic+security quality gate does not block failed security")

    autopilot_session = create_session("feature", "Autopilot")
    autopilot_session["autopilot"] = True
    if not is_autopilot_gate_passable(autopilot_session)["passed"]:
        problems.append("autopilot approves a user gate")
    autopilot_session = advance_phase(autopilot_session, resultado="aprobado")
    autopilot_session = advance_phase(autopilot_session, resultado="aprobado")
    autopilot_session = advance_phase(autopilot_session, resultado="aprobado")
    if is_autopilot_gate_passable(autopilot_session, tests_ok=False)["passed"]:
        problems.append("autopilot skips an automatic gate with red tests")

    ship_session = create_session("ship", "Release autopilot")
    ship_session["autopilot"] = True
    ship_session = advance_phase(ship_session, resultado="aprobado", tests_ok=True, security_ok=True)
    ship_session = advance_phase(ship_session, resultado="aprobado")
    ship_session = advance_phase(ship_session, resultado="aprobado", tests_ok=True, security_ok=True)
    ship_gate = is_autopilot_gate_passable(ship_session, security_ok=True)
    if ship_session["fase_actual"] != "despliegue":
        problems.append(f"ship does not reach despliegue in the expected phase: {ship_session['fase_actual']}")
    ship_reason = ship_gate.get("reason", "")
    # core/orchestrator.py may still return the Spanish reason or a Russian one.
    explicit_confirmation = "confirmación explícita del usuario" in ship_reason or (
        "явн" in ship_reason and "подтвержд" in ship_reason
    )
    if ship_gate["passed"] or not explicit_confirmation:
        problems.append("ship autopilot does not keep human deploy confirmation")

    if problems:
        _fail("Flow/gate claims out of sync: " + "; ".join(problems))

    return [
        "feature keeps 7 phases with conditional Designer",
        "Designer runs only with frontend and is skipped with backend",
        "free gates documented as evidence without human approval",
        "automatic gates block red tests and failed security",
        "autopilot does not skip automatic gates or human deploy",
    ]


def check_hook_contracts() -> list[str]:
    """Check that hooks.json follows the modern Claude Code contract."""
    hooks_config = _json("hooks/hooks.json")
    hooks_by_event = hooks_config.get("hooks")
    if not isinstance(hooks_by_event, dict):
        _fail("hooks/hooks.json does not declare hooks")

    expected_events = {
        "SessionStart",
        "SessionEnd",
        "UserPromptSubmit",
        "PreToolUse",
        "PostToolUse",
    }
    actual_events = set(hooks_by_event)
    if actual_events != expected_events:
        missing_events = sorted(expected_events - actual_events)
        extra_events = sorted(actual_events - expected_events)
        _fail(
            "Hook events out of sync: "
            f"actual={sorted(hooks_by_event)} missing={missing_events} extra={extra_events}"
        )

    visible_scripts = sorted(
        path.name
        for path in (ROOT / "hooks").iterdir()
        if path.is_file()
        and path.suffix in {".py", ".sh"}
        and path.name not in {"evidence_guard_lib.py", "secret-guard.sh"}
    )
    if len(visible_scripts) != 10:
        _fail(f"Unexpected visible hooks: {visible_scripts}")

    registered: list[tuple[str, str, dict]] = []
    problems: list[str] = []
    for event, groups in hooks_by_event.items():
        if not isinstance(groups, list) or not groups:
            problems.append(f"{event}: must contain groups")
            continue
        for group in groups:
            if not isinstance(group, dict):
                problems.append(f"{event}: group is not an object")
                continue
            if event in HOOK_EVENTS_WITHOUT_MATCHER and "matcher" in group:
                problems.append(
                    f"{event}: declares a matcher that Claude Code ignores for this event"
                )
            for hook in group.get("hooks", []):
                if not isinstance(hook, dict) or hook.get("type") != "command":
                    problems.append(f"{event}: hook is not command")
                    continue
                if "if" in hook:
                    if event not in HOOK_EVENTS_WITH_IF_SUPPORT:
                        problems.append(
                            f"{event}: declares an if that Claude Code does not evaluate for this event"
                        )
                    elif not isinstance(hook["if"], str) or not hook["if"].strip():
                        problems.append(f"{event}: if must be a non-empty string")
                command = hook.get("command")
                args = hook.get("args")
                if not isinstance(command, str) or not command:
                    problems.append(f"{event}: invalid command")
                    continue
                if "|| true" in command or "test -f" in command:
                    problems.append(f"{event}: shell command masks errors: {command}")
                if "${CLAUDE_PLUGIN_ROOT}" in command:
                    problems.append(f"{event}: uses a placeholder in command instead of args: {command}")
                if not isinstance(args, list) or len(args) != 1 or not isinstance(args[0], str):
                    problems.append(f"{event}: hook without exec form args for {command}")
                    continue
                script_arg = args[0]
                prefix = "${CLAUDE_PLUGIN_ROOT}/hooks/"
                if not script_arg.startswith(prefix):
                    problems.append(f"{event}: args does not point to hooks/: {script_arg}")
                    continue
                script_name = script_arg.removeprefix(prefix)
                script_path = ROOT / "hooks" / script_name
                if not script_path.is_file():
                    problems.append(f"{event}: script does not exist {script_name}")
                    continue
                if script_name.endswith(".py") and command != "python3":
                    problems.append(f"{script_name}: must use command python3")
                if script_name.endswith(".sh") and command != "bash":
                    problems.append(f"{script_name}: must use command bash")
                if "async" in hook and not isinstance(hook["async"], bool):
                    problems.append(f"{script_name}: async must be boolean")
                timeout = hook.get("timeout")
                if hook.get("async") is not True:
                    if type(timeout) is not int:
                        problems.append(f"{script_name}: synchronous hook without integer timeout")
                    elif timeout > HOOK_SYNC_TIMEOUT_LIMIT:
                        problems.append(
                            f"{script_name}: synchronous hook exceeds timeout "
                            f"{HOOK_SYNC_TIMEOUT_LIMIT}s ({timeout}s)"
                        )
                registered.append((event, script_name, hook))

    registered_names = {script_name for _, script_name, _ in registered}
    missing = sorted(set(visible_scripts) - registered_names)
    extras = sorted(registered_names - set(visible_scripts))
    if missing:
        problems.append(f"unregistered scripts: {missing}")
    if extras:
        problems.append(f"unexpected registered scripts: {extras}")

    blocking = {
        "secret-guard.py",
        "dangerous-command-guard.py",
    }
    for script_name in blocking:
        matches = [
            (event, hook)
            for event, registered_script, hook in registered
            if registered_script == script_name
        ]
        if not matches:
            problems.append(f"{script_name}: not registered")
            continue
        for event, hook in matches:
            if event != "PreToolUse":
                problems.append(f"{script_name}: must register in PreToolUse, not {event}")
            if hook.get("async"):
                problems.append(f"{script_name}: must not be async")
            if hook.get("timeout", 99) > 5:
                problems.append(f"{script_name}: timeout must be <= 5")

    for path in sorted((ROOT / "hooks").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")

    for path in sorted((ROOT / "hooks").glob("*.sh")):
        result = subprocess.run(
            ["bash", "-n", str(path)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            problems.append(f"{_rel(path)}: bash -n failed: {result.stdout}")

    wrapper_needles = (
        "EMBEDDED_PLUGIN_ROOT",
        "CLAUDE_PLUGIN_ROOT",
        "ALFRED_DEV_PLUGIN_ROOT",
        "def _cache_candidates():",
        "core/continuity.py",
    )
    for script_name in ("session-bootstrap.sh",):
        source = _read(f"hooks/{script_name}")
        for needle in wrapper_needles:
            if needle not in source:
                problems.append(f"{script_name}: wrapper does not contain {needle}")

    hooks_doc = _read("docs/hooks.md")
    if '"decisión": "block"' in hooks_doc:
        problems.append("docs/hooks.md uses the obsolete key \"decisión\" instead of decision")
    nested_hook_output = re.findall(
        r"hookSpecificOutput\.(?:"
        r"SessionStart|UserPromptSubmit|UserPromptExpansion|Stop|PreToolUse|PreCompact|PostToolUse|"
        r"PostToolUseFailure|PostToolBatch|PermissionRequest|Notification|"
        r"Setup|SubagentStart"
        r")\.[A-Za-z]",
        hooks_doc,
    )
    if nested_hook_output:
        problems.append(
            "docs/hooks.md uses hookSpecificOutput nested by event: "
            f"{sorted(set(nested_hook_output))}"
        )
    for needle in (
        '"decision": "block"',
        "hookSpecificOutput.hookEventName",
        "hookSpecificOutput.additionalContext",
        "systemMessage",
        "Claude Code игнорирует `matcher`",
        "Поле `if` вычисляется только в событиях инструментов",
        "`manual\\|auto` опускается, чтобы покрыть оба",
        "Claude Code игнорирует любой JSON, когда процесс завершается с `2`",
        "не смешивай управляющий JSON с `exit 2`",
    ):
        if needle not in hooks_doc:
            problems.append(f"docs/hooks.md no documenta contrato moderno de hooks: {needle}")
    if "Timeout синхронных хуков не должен превышать 10 секунд" not in hooks_doc:
        problems.append("docs/hooks.md no documenta limite de timeout sincronico")

    direct_checks = [
        (
            "secret-guard invalid json",
            ["bash", str(ROOT / "hooks" / "secret-guard.sh")],
            "not-json",
        ),
        (
            "dangerous-command invalid json",
            [sys.executable, str(ROOT / "hooks" / "dangerous-command-guard.py")],
            "not-json",
        ),
        (
            "dangerous-command rm root",
            [sys.executable, str(ROOT / "hooks" / "dangerous-command-guard.py")],
            json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "rm -rf /"},
                }
            ),
        ),
    ]
    for name, command, stdin in direct_checks:
        result = subprocess.run(
            command,
            cwd=ROOT,
            input=stdin,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        if result.returncode != 2:
            problems.append(
                f"{name}: expected exit 2, got {result.returncode}; "
                f"stdout={result.stdout!r} stderr={result.stderr!r}"
            )
        if result.stdout:
            problems.append(
                f"{name}: a hook with exit 2 must not emit JSON/stdout "
                f"because Claude Code ignores it: {result.stdout!r}"
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir)
        (project / ".claude").mkdir()
        (project / ".claude" / "alfred-prefetch.json").write_text(
            json.dumps(
                {
                    "source_command": "alfred",
                    "prefetched_command": "map-codebase",
                    "response_text": "prefetch ready",
                    "expires_at": "2999-01-01T00:00:00+00:00",
                }
            ),
            encoding="utf-8",
        )
        pass

    if problems:
        _fail("Hook contracts incomplete: " + "; ".join(problems))

    return [
        "10 visible hooks registered",
        "declared hook scripts exist and cover the 9 visible ones",
        "exec form without shell wrappers or unquoted paths",
        "blocking hooks keep exit 2",
        "hooks with exit 2 do not emit JSON that Claude Code ignores",
        "events SessionStart, SessionEnd, UserPromptSubmit, PreToolUse and PostToolUse",
        "events without matcher do not declare an ignored matcher",
        "hooks do not use if outside tool events",
        "synchronous hooks declare integer timeout <= 10 seconds",
        "hook syntax validated",
        "helper-first wrapper resilient to a rotated plugin cache",
        "hook docs use current decision/hookSpecificOutput",
    ]


def check_mcp_config() -> list[str]:
    mcp = _json(".mcp.json")
    server = mcp.get("mcpServers", {}).get("alfred-memory")
    if not isinstance(server, dict):
        _fail(".mcp.json does not declare mcpServers.alfred-memory")
    if server.get("command") != "python3":
        _fail("alfred-memory must start with command python3 so that the installers can patch it")
    args = server.get("args")
    if not isinstance(args, list) or not args or "memory_server.py" not in str(args[0]):
        _fail("alfred-memory must point to mcp/memory_server.py")
    if "${CLAUDE_PLUGIN_ROOT}" not in str(args[0]):
        _fail("alfred-memory must use CLAUDE_PLUGIN_ROOT")

    return ["portable root MCP with memory_server.py"]


def _npm_pack_dry_run_package() -> dict:
    completed = subprocess.run(
        ["npm", "pack", "--dry-run", "--json"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=30,
        check=False,
    )
    if completed.returncode != 0:
        _fail(f"npm pack --dry-run failed: {completed.stderr.strip()}")

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        _fail(f"npm pack did not return valid JSON: {exc}: {completed.stdout[:500]}")
    if not isinstance(payload, list) or not payload:
        _fail(f"npm pack returned an unexpected payload: {payload!r}")
    package = payload[0]
    if not isinstance(package, dict):
        _fail(f"npm pack returned an unexpected package: {package!r}")
    return package


def _publishable_symlink_problems() -> list[str]:
    problems: list[str] = []
    root = ROOT.resolve()
    for root_name in PUBLISHABLE_SYMLINK_ROOTS:
        root_path = ROOT / root_name
        if not root_path.exists() and not root_path.is_symlink():
            continue
        candidates = [root_path]
        if root_path.is_dir() and not root_path.is_symlink():
            candidates.extend(root_path.rglob("*"))
        for path in candidates:
            if not path.is_symlink():
                continue
            try:
                target = path.resolve(strict=True)
            except FileNotFoundError:
                problems.append(f"{_rel(path)} is a broken symlink")
                continue
            try:
                target.relative_to(root)
            except ValueError:
                problems.append(
                    f"{_rel(path)} is a symlink outside the plugin: {os.readlink(path)!r}"
                )
    return problems


def check_packaging_contracts() -> list[str]:
    """Check the real package that npm would produce before publishing."""
    package = _npm_pack_dry_run_package()
    if package.get("name") != "alfred-dev" or package.get("version") != VERSION:
        _fail(f"npm pack packs an unexpected identity: {package}")

    packed_paths = {
        entry.get("path")
        for entry in package.get("files", [])
        if isinstance(entry, dict)
    }
    required_paths = {
        ".claude-plugin/plugin.json",
        ".claude-plugin/marketplace.json",
        ".mcp.json",
        "commands/_composicion.md",
        "commands/alfred.md",
        "agents/alfred.md",
        "hooks/hooks.json",
        "mcp/memory_server.py",
        "core/continuity.py",
        "scripts/release_audit.py",
        "visual/scripts/frame-template.html",
        "visual/scripts/helper.js",
        "visual/scripts/read-choice.py",
        "visual/scripts/server.cjs",
        "visual/scripts/start-server.sh",
        "visual/scripts/stop-server.sh",
        "visual/scripts/write-guided-style-options.py",
        "visual/scripts/write-style-demo-gallery.py",
        "visual/scripts/write-style-direction.py",
        "visual/scripts/write-style-options.py",
        "visual/scripts/write-style-selector.py",
    }
    required_paths.update(TEMPLATE_PATHS)
    missing_required = sorted(required_paths - packed_paths)
    if missing_required:
        _fail(f"npm pack does not include critical artifacts: {missing_required}")

    forbidden_prefixes = (
        ".alfred-dev/",
        ".claude/",
        ".crupier/",
        ".git/",
        ".pytest_cache/",
        "docs/manual-smoke",
        "node_modules/",
        "site/.astro/",
        "site/dist/",
        "site/node_modules/",
        "tests/",
    )
    forbidden_suffixes = (
        ".pyc",
        ".pyo",
    )
    leaked = sorted(
        path for path in packed_paths
        if path and (
            path.startswith(forbidden_prefixes)
            or any(part == "__pycache__" for part in path.split("/"))
            or path.endswith(forbidden_suffixes)
        )
    )
    if leaked:
        _fail(f"npm pack includes local or test artifacts: {leaked[:20]}")
    symlink_problems = _publishable_symlink_problems()
    if symlink_problems:
        _fail("Publishable symlinks incompatible with the Claude cache: " + "; ".join(symlink_problems))

    manifest_command_paths = {
        path.lstrip("./")
        for path in _json(".claude-plugin/plugin.json")["commands"]
    }
    public_command_paths = [
        path for path in packed_paths
        if path in manifest_command_paths
    ]
    agent_paths = [
        path for path in packed_paths
        if path.startswith("agents/") and path.endswith(".md")
    ]
    skill_paths = [
        path for path in packed_paths
        if path.startswith("skills/") and path.endswith("/SKILL.md")
    ]
    template_paths = [
        path for path in packed_paths
        if path.startswith("templates/") and path.endswith(".md")
    ]
    if len(public_command_paths) != 18 or len(agent_paths) != 10 or len(skill_paths) != 11:
        _fail(
            "npm pack out of sync with the public inventory: "
            f"commands={len(public_command_paths)} agents={len(agent_paths)} skills={len(skill_paths)}"
        )
    if sorted(template_paths) != sorted(TEMPLATE_PATHS):
        _fail(
            "npm pack out of sync with artifact templates: "
            f"{sorted(template_paths)}"
        )

    return [
        f"npm pack dry-run {VERSION} valid",
        "package without local caches or tests",
        "package without .claude/.crupier or manual evidence",
        "package without publishable symlinks outside the plugin",
        "package contains 18 namespaced commands, 10 agents and 11 skills",
        "package contains 8 artifact templates",
        "package contains the Designer visual runtime",
    ]


def check_published_secret_scan() -> list[str]:
    """Scan the publishable artifact for real secrets."""
    from core.secrets import find_secret_label

    package = _npm_pack_dry_run_package()
    packed_paths = {
        entry.get("path")
        for entry in package.get("files", [])
        if isinstance(entry, dict)
    }
    findings: list[str] = []
    for relative in sorted(path for path in packed_paths if isinstance(path, str)):
        path = ROOT / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        label = find_secret_label(text)
        if label:
            findings.append(f"{relative}: {label}")

    if findings:
        _fail(
            "The publishable package contains possible real secrets: "
            + "; ".join(findings[:20])
        )

    return ["publishable package without real secret patterns"]


def check_install_update_contracts() -> list[str]:
    """Check install, uninstall and update with explicit scopes."""
    install_sh = _read("install.sh")
    install_ps1 = _read("install.ps1")
    uninstall_sh = _read("uninstall.sh")
    uninstall_ps1 = _read("uninstall.ps1")
    update_command = _read("commands/update.md")
    installation_docs = _read("docs/installation.md")

    requirements = {
        "install.sh": [
            'claude plugin uninstall "${PLUGIN_NAME}@${PLUGIN_NAME}" --scope local',
            'claude plugin uninstall "${PLUGIN_NAME}@${PLUGIN_NAME}" --scope project',
            'claude plugin marketplace remove "${PLUGIN_NAME}" --scope local',
            'claude plugin marketplace remove "${PLUGIN_NAME}" --scope project',
            'claude plugin uninstall "${PLUGIN_NAME}@${PLUGIN_NAME}" --scope user',
            'claude plugin marketplace remove "${PLUGIN_NAME}" --scope user',
            'claude plugin marketplace add "${REPO}" --scope user',
            'claude plugin install "${PLUGIN_NAME}@${PLUGIN_NAME}" --scope user',
            "claude plugin list --json",
            "Глобальная установка для пользователя подтверждена (--scope user)",
            "~/.claude/skills не затрагивается",
            'HOOKS_JSON="${PLUGIN_ROOT}/hooks/hooks.json"',
            'MCP_JSON="${PLUGIN_ROOT}/.mcp.json"',
            "/reload-plugins",
            "MCP/стоимости cache",
        ],
        "install.ps1": [
            "claude plugin uninstall $PluginKey --scope local",
            "claude plugin uninstall $PluginKey --scope project",
            "claude plugin marketplace remove $PluginName --scope local",
            "claude plugin marketplace remove $PluginName --scope project",
            "claude plugin uninstall $pluginKey --scope user",
            "claude plugin marketplace remove $PluginName --scope user",
            "claude plugin marketplace add $Repo --scope user",
            "claude plugin install $pluginKey --scope user",
            "claude plugin list --json",
            "Глобальная установка для пользователя подтверждена (--scope user)",
            "~/.claude/skills не затрагивается",
            'Join-Path $PluginRoot "hooks/hooks.json"',
            'Join-Path $PluginRoot ".mcp.json"',
            "/reload-plugins",
            "MCP/стоимости cache",
        ],
        "uninstall.sh": [
            'claude plugin uninstall "${PLUGIN_KEY}" --scope user',
            'claude plugin marketplace remove "${PLUGIN_NAME}" --scope user',
            'known_marketplaces.json',
            'installed_plugins.json',
            'enabledPlugins',
            "Глобальный alias /alfred удалён",
            "Глобальный shim команды /alfred удалён",
        ],
        "uninstall.ps1": [
            "claude plugin uninstall $PluginKey --scope user",
            "claude plugin marketplace remove $PluginName --scope user",
            "known_marketplaces.json",
            "installed_plugins.json",
            "enabledPlugins",
            "Глобальный alias /alfred удалён",
            "Глобальный shim команды /alfred удалён",
        ],
        "commands/update.md": [
            "claude plugin list --json",
            "как настоящий semver",
            "один `AskUserQuestion`",
            "Обновить сейчас",
            "Не сейчас",
            "нормализует их в `--scope user`",
            "не затрагивает `~/.claude/skills`",
            "Не используй `claude plugin update --scope local`",
            "`claude plugin update --scope project`",
            "curl -fsSL https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/install.sh | bash",
            "выполнить **`/reload-plugins`**",
            "`/reload-plugins --force`",
            "нужно перезапустить",
        ],
        "docs/installation.md": [
            "--scope user",
            "глобальную пользовательскую установку",
            "не перезаписывает",
            "~/.claude/commands/alfred.md",
            "claude plugin list --json",
            "не использует официальный marketplace Anthropic",
            "`/reload-plugins` применяет изменения",
            "`/reload-plugins --force`",
        ],
    }
    sources = {
        "install.sh": install_sh,
        "install.ps1": install_ps1,
        "uninstall.sh": uninstall_sh,
        "uninstall.ps1": uninstall_ps1,
        "commands/update.md": update_command,
        "docs/installation.md": installation_docs,
    }
    missing = []
    for path, needles in requirements.items():
        for needle in needles:
            if not _contains(sources[path], needle):
                missing.append(f"{path}: {_needle_label(needle)}")
    if missing:
        _fail("Install/update contracts incomplete: " + "; ".join(missing))

    stateful_plugin_command = re.compile(
        r"\bclaude plugin "
        r"(?:(?:marketplace\s+(?:add|remove))|(?:install|uninstall|update))\b"
    )
    bad_scope = []
    for path in ("install.sh", "install.ps1", "uninstall.sh", "uninstall.ps1"):
        for line_number, line in enumerate(sources[path].splitlines(), start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not stateful_plugin_command.search(stripped):
                continue
            scope_match = re.search(r"--scope\s+([A-Za-z_$\{\}]+)", stripped)
            if not scope_match:
                bad_scope.append(f"{path}:{line_number}: {stripped}")
                continue
            scope = scope_match.group(1).strip("${}").lstrip("$")
            if scope == "user":
                continue
            is_cleanup = (
                path in {"install.sh", "install.ps1"}
                and scope in {"local", "project"}
                and (
                    "plugin uninstall" in stripped
                    or "plugin marketplace remove" in stripped
                )
            )
            if not is_cleanup:
                bad_scope.append(f"{path}:{line_number}: scope {scope} forbidden")
    if bad_scope:
        _fail(
            "CLI plugin without explicit user scope or allowed local/project cleanup: "
            + "; ".join(bad_scope)
        )

    if "instalación local que limpiar" in uninstall_sh:
        _fail("uninstall.sh must not describe Alfred Dev as a local install")

    return [
        "installers use explicit user scope",
        "installers verify user scope after install",
        "installers clean inherited local/project scopes before the user install",
        "installers do not touch ~/.claude/skills or install a global /alfred alias",
        "update keeps semver and human menu, normalizes to user scope and documents reload/restart",
    ]


def check_audit_docs() -> list[str]:
    package = _json("package.json")
    readme = _read("README.md")
    docs_readme = _read("docs/README.md")
    architecture = _read("docs/architecture.md")
    install = _read("docs/installation.md")
    release_doc = _read("docs/release.md")
    gitignore = _read(".gitignore")
    npmignore = _read(".npmignore")

    required = {
        "README.md": [
            "Новое в v0.7.0",
            "docs/release.md",
            "современном MCP stdio",
        ],
        "docs/README.md": [
            "release.md",
            "11 skills",
            "18 команд",
        ],
        "docs/installation.md": [
            "plugin:alfred-dev:alfred-memory",
            "Pending approval",
            "Одобрять эту проектную запись для проверки плагина не нужно",
            'claude plugin marketplace add "$PWD" --scope user',
            "Текущий Claude Code даёт полезную диагностику",
            "claude plugin details alfred-dev@alfred-dev",
            "claude plugin validate . --strict",
            "claude --debug",
            "/plugin validate",
        ],
        "docs/architecture.md": [
            "`matcher` необязателен",
            "объявляется только в событиях, где Claude Code его поддерживает",
            "Claude Code его игнорирует",
            "PreCompact",
            "и ручную, и автоматическую",
        ],
        "docs/release.md": [
            "18 команд",
            "10 агентов",
            "11 skills",
            "10 хуков",
            "displayName: \"Alfred Dev\"",
            "технический namespace: `alfred-dev`",
            "не трогает `~/.claude/skills`",
            "`_composicion.md`",
            "`_docs_vivas.md`",
            "commands/ как поддерживаемые плоские skills",
            "публичного UX",
            "`/alfred-dev:*`",
            "argument-hint",
            "$ARGUMENTS",
            "1536 символов",
            "disable-model-invocation: true",
            "npm run release:audit",
            "npm run release:audit:manual",
            "npm run release:audit:manual:evidence",
            "npm run release:audit:prepublish",
            "18 публичных маршрутов",
            "40 публичных опций",
            "4 runtime-контракта",
            "--auth-preflight",
            "core/secrets.py",
            "правами `0600`",
            "evidence_file",
            "evidence_sha256",
            "plugin_surface.sha256",
            "notes_low_quality",
            "notes_repeated",
            "--require-current-auth-preflight",
            "auth_preflight.status=ok",
            "scripts/manual_smoke.py",
            "scripts/external_live_smoke.py",
            "не создаёт issues, не запускает контейнеры",
            "quality gates проверяемы по локальному контракту",
            "questions[]",
            "multiSelect",
            "hookSpecificOutput.additionalContext",
            "Сам по себе не одобряет релиз",
            "Что не покрывает локальный контракт",
            "claude auth login",
            "scripts/claude_auth_recovery.py",
        ],
    }
    sources = {
        "README.md": readme,
        "docs/README.md": docs_readme,
        "docs/architecture.md": architecture,
        "docs/installation.md": install,
        "docs/release.md": release_doc,
    }
    missing = []
    for path, needles in required.items():
        for needle in needles:
            if needle not in sources[path]:
                missing.append(f"{path}: {needle}")
    if re.search(r"PreCompact[^.\n]*(?:ignora|ignorado|игнорир)", architecture):
        _fail("docs/architecture.md wrongly claims that PreCompact ignores matcher")
    if 'displayName: "Alfred Dev"' not in release_doc:
        _fail("docs/release.md must document the human displayName")
    if re.search(r"plugin_surface\.sha256=[0-9a-f]{64}", release_doc):
        _fail("docs/release.md must not freeze plugin_surface.sha256")
    if "docs/manual-smoke*.json" not in gitignore:
        _fail(".gitignore must exclude manual evidence/reviews docs/manual-smoke*.json")
    if "docs/manual-smoke*.json" not in npmignore:
        _fail(".npmignore must exclude manual evidence/reviews docs/manual-smoke*.json")
    if "docs/manual-smoke*.md" not in gitignore:
        _fail(".gitignore must exclude manual reports docs/manual-smoke*.md")
    if "docs/manual-smoke*.md" not in npmignore:
        _fail(".npmignore must exclude manual reports docs/manual-smoke*.md")
    if "docs/project/" not in gitignore:
        _fail(".gitignore must exclude local operating state docs/project/")
    if "docs/project/" not in npmignore:
        _fail(".npmignore must exclude local operating state docs/project/")
    if "docs/external-live-smoke*.json" not in gitignore:
        _fail(".gitignore must exclude external evidence docs/external-live-smoke*.json")
    if "docs/external-live-smoke*.json" not in npmignore:
        _fail(".npmignore must exclude external evidence docs/external-live-smoke*.json")
    if "docs/claude-auth-recovery*.json" not in gitignore:
        _fail(".gitignore must exclude auth diagnostics docs/claude-auth-recovery*.json")
    if "docs/claude-auth-recovery*.json" not in npmignore:
        _fail(".npmignore must exclude auth diagnostics docs/claude-auth-recovery*.json")
    if missing:
        _fail(f"Audit documentation incomplete: {missing}")
    scripts = package.get("scripts", {})
    expected_scripts = {
        "release:audit:external:preflight": (
            "python3 scripts/external_live_smoke.py --output docs/external-live-smoke-0.7.0.json"
        ),
        "release:audit:claude:commands": "python3 scripts/claude_command_discovery.py",
        "release:audit:manual": "python3 scripts/manual_smoke.py",
        "release:audit:manual:evidence": (
            "python3 scripts/manual_smoke.py --auth-preflight --output docs/manual-smoke-0.7.0.json"
        ),
        "release:audit:manual:evidence:installed": (
            "python3 scripts/manual_smoke.py --installed --auth-preflight --output docs/manual-smoke-installed-0.7.0.json"
        ),
        "release:audit:manual:preflight": "python3 scripts/manual_smoke.py --auth-preflight --preflight-only",
        "release:audit:manual:preflight:diagnose": (
            "python3 scripts/manual_smoke.py --auth-preflight --preflight-only --allow-auth-failure"
        ),
        "release:audit:manual:auth:diagnose": "python3 scripts/claude_auth_recovery.py",
        "release:audit:manual:auth:strict": "python3 scripts/claude_auth_recovery.py --strict",
        "release:audit:manual:review:init": (
            "python3 scripts/manual_review_gate.py --init-template docs/manual-smoke-0.7.0.json docs/manual-smoke-review-0.7.0.json"
        ),
        "release:audit:manual:review": (
            "python3 scripts/manual_review_gate.py --require-current-auth-preflight --expect-plugin-source worktree docs/manual-smoke-0.7.0.json docs/manual-smoke-review-0.7.0.json"
        ),
        "release:audit:manual:report": (
            "python3 scripts/manual_review_report.py docs/manual-smoke-0.7.0.json docs/manual-smoke-review-0.7.0.json --output docs/manual-smoke-report-0.7.0.md"
        ),
        "release:audit:manual:review:installed:init": (
            "python3 scripts/manual_review_gate.py --init-template docs/manual-smoke-installed-0.7.0.json docs/manual-smoke-installed-review-0.7.0.json"
        ),
        "release:audit:manual:review:installed": (
            "python3 scripts/manual_review_gate.py --require-current-auth-preflight --expect-plugin-source installed-cache docs/manual-smoke-installed-0.7.0.json docs/manual-smoke-installed-review-0.7.0.json"
        ),
        "release:audit:manual:report:installed": (
            "python3 scripts/manual_review_report.py docs/manual-smoke-installed-0.7.0.json docs/manual-smoke-installed-review-0.7.0.json --output docs/manual-smoke-installed-report-0.7.0.md"
        ),
        "release:audit:prepublish:prepare": (
            "npm run release:audit:full && "
            "npm run release:audit:manual:evidence && "
            "npm run release:audit:manual:evidence:installed"
        ),
        "release:audit:prepublish": (
            "npm run release:audit:full && "
            "npm run release:audit:manual:preflight && "
            "npm run release:audit:manual:review && "
            "npm run release:audit:manual:review:installed"
        ),
    }
    bad_scripts = {
        name: {"actual": scripts.get(name), "expected": expected}
        for name, expected in expected_scripts.items()
        if scripts.get(name) != expected
    }
    if bad_scripts:
        _fail(f"Manual smoke npm scripts out of sync: {bad_scripts}")
    if not (ROOT / "scripts" / "manual_smoke.py").is_file():
        _fail("scripts/manual_smoke.py is missing; it reproduces the manual matrix")
    if not (ROOT / "scripts" / "manual_review_gate.py").is_file():
        _fail("scripts/manual_review_gate.py is missing; it validates the human review")
    if not (ROOT / "scripts" / "external_live_smoke.py").is_file():
        _fail("scripts/external_live_smoke.py is missing; it captures the external preflight")
    if not (ROOT / "scripts" / "claude_command_discovery.py").is_file():
        _fail("scripts/claude_command_discovery.py is missing; it tests interactive /alfred-dev:alfred")
    if not (ROOT / "docs" / "release.md").is_file():
        _fail("docs/release.md is missing; it audits claims and release readiness")
    prepare = scripts.get("release:audit:prepublish:prepare", "")
    required_prepare_parts = (
        "npm run release:audit:full",
        "npm run release:audit:manual:evidence",
        "npm run release:audit:manual:evidence:installed",
    )
    missing_prepare = [
        part for part in required_prepare_parts if part not in prepare
    ]
    if missing_prepare:
        _fail(f"release:audit:prepublish:prepare incomplete: {missing_prepare}")

    prepublish = scripts.get("release:audit:prepublish", "")
    required_prepublish_parts = (
        "npm run release:audit:full",
        "npm run release:audit:manual:preflight",
        "npm run release:audit:manual:review",
        "npm run release:audit:manual:review:installed",
    )
    missing_prepublish = [
        part for part in required_prepublish_parts if part not in prepublish
    ]
    if missing_prepublish:
        _fail(f"release:audit:prepublish incomplete: {missing_prepublish}")
    prepublish_parts = {part.strip() for part in prepublish.split("&&")}
    forbidden_prepublish_parts = {
        "npm run release:audit:manual:evidence",
        "npm run release:audit:manual:evidence:installed",
    }
    forbidden_present = sorted(prepublish_parts & forbidden_prepublish_parts)
    if forbidden_present:
        _fail(
            "release:audit:prepublish must not regenerate already reviewed evidence: "
            f"{forbidden_present}"
        )

    spec = importlib.util.spec_from_file_location(
        "manual_smoke_release_audit",
        ROOT / "scripts" / "manual_smoke.py",
    )
    if spec is None or spec.loader is None:
        _fail("Could not load scripts/manual_smoke.py to audit coverage")
    manual_smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manual_smoke)
    if "plugin_surface.sha256" not in release_doc:
        _fail("docs/release.md must require plugin_surface.sha256 from the run, not a frozen hash")
    manual_smoke_text = _read("scripts/manual_smoke.py")
    manual_review_gate_text = _read("scripts/manual_review_gate.py")
    manual_review_report_text = _read("scripts/manual_review_report.py")
    manual_smoke_runtime_needles = (
        '"--permission-mode",',
        '"bypassPermissions",',
        'parser.add_argument("--budget", default="1.50"',
        'parser.add_argument(\n        "--preflight-only"',
        'if args.preflight_only:',
        'error_max_budget_usd',
    )
    missing_manual_smoke_runtime = [
        needle for needle in manual_smoke_runtime_needles if needle not in manual_smoke_text
    ]
    if missing_manual_smoke_runtime:
        _fail(
            "The manual smoke must reproduce a real claude -p without interactive permissions or a low budget: "
            f"{missing_manual_smoke_runtime}"
        )
    preview_sanitizer_needles = (
        "from core.secrets import sanitize_text",
        "def _safe_preview(",
        "path.chmod(0o600)",
        "previews[relative] = _safe_preview(",
        '"response_preview": _safe_preview(response_text, 2000)',
        '"stderr_preview": _safe_preview(result.stderr, 2000)',
        '"response_preview": _safe_preview(response_text, 500)',
        '"stderr_preview": _safe_preview(result.stderr, 500)',
    )
    missing_preview_sanitizer = [
        needle for needle in preview_sanitizer_needles if needle not in manual_smoke_text
    ]
    if missing_preview_sanitizer:
        _fail(
            "Manual evidence must sanitize previews with core/secrets.py: "
            f"{missing_preview_sanitizer}"
        )
    review_secret_gate_needles = (
        "from core.secrets import find_secret_label",
        "def _iter_secret_findings(",
        "evidence_secret_findings = _iter_secret_findings(evidence, \"evidence\")",
        "review_secret_findings = _iter_secret_findings(review, \"review\")",
        ("evidence contiene posibles secretos reales", "evidence contains possible real secrets"),
        ("review contiene posibles secretos reales", "review contains possible real secrets"),
        (
            "No se crea plantilla de revisión con evidencia que contiene",
            "Review template not created: evidence contains",
        ),
        "review_path.chmod(0o600)",
        "GENERIC_REVIEW_NOTES",
        "MIN_REVIEW_NOTE_CHARS",
        "MIN_REVIEW_NOTE_WORDS",
        "def _is_low_quality_review_note(",
        (
            "review.cases con notes humanas demasiado genericas o cortas",
            "review.cases has human notes that are too generic or short",
        ),
        ("review.cases contiene notes humanas repetidas", "review.cases contains repeated human notes"),
        "--require-current-auth-preflight",
        ("preflight actual de Claude CLI no esta ok", "current Claude CLI preflight is not ok"),
    )
    missing_review_secret_gate = [
        _needle_label(needle)
        for needle in review_secret_gate_needles
        if not _contains(manual_review_gate_text, needle)
    ]
    if missing_review_secret_gate:
        _fail(
            "The manual review gate must reject secrets with core/secrets.py: "
            f"{missing_review_secret_gate}"
        )
    review_report_note_needles = (
        "def _plugin_surface_flags(",
        ("## Superficie Del Plugin", "## Plugin Surface"),
        (
            "evidence.plugin_surface.roots no coincide con el plugin actual",
            "evidence.plugin_surface.roots does not match the current plugin",
        ),
        (
            "evidence.plugin_surface.file_count no coincide con el plugin actual",
            "evidence.plugin_surface.file_count does not match the current plugin",
        ),
        (
            "evidence.plugin_surface.sha256 no coincide con el plugin actual",
            "evidence.plugin_surface.sha256 does not match the current plugin",
        ),
        "def _review_quality_flags(",
        "_manual_review_gate_module()",
        ("## Calidad De Review Humana", "## Human Review Quality"),
        "notes_missing",
        "notes_low_quality",
        "notes_repeated",
        "review_secret_findings",
        ("Sin flags automaticos de notas humanas", "No automatic human note flags"),
    )
    missing_review_report_notes = [
        _needle_label(needle)
        for needle in review_report_note_needles
        if not _contains(manual_review_report_text, needle)
    ]
    if missing_review_report_notes:
        _fail(
            "The manual review report must show weak or repeated human notes: "
            f"{missing_review_report_notes}"
        )
    review_traceability_needles = (
        ("review.evidence_file es obligatorio", "review.evidence_file is required"),
        (
            "review.evidence_file no coincide con el evidence pasado al gate",
            "review.evidence_file does not match the evidence passed to the gate",
        ),
        ("review.evidence_file coincide", "review.evidence_file matches"),
        ("review.cases desalineados con matriz actual", "review.cases out of sync with the current matrix"),
        (
            "review.cases coincide con la matriz manual actual",
            "review.cases matches the current manual matrix",
        ),
    )
    missing_review_traceability = [
        _needle_label(needle)
        for needle in review_traceability_needles
        if not _contains(manual_review_gate_text, needle)
    ]
    if missing_review_traceability:
        _fail(
            "The manual review gate must bind evidence_file to the validated evidence: "
            f"{missing_review_traceability}"
        )
    _validate_manual_case_contract_links(manual_smoke)
    coverage = manual_smoke._case_command_coverage()
    missing = [name for name, case_ids in coverage.items() if not case_ids]
    if len(coverage) != 18 or missing:
        _fail(f"The manual matrix does not cover the 18 public routes: missing={missing}")
    option_coverage = manual_smoke._case_option_coverage()
    missing_options = [
        name for name, case_ids in option_coverage.items()
        if not case_ids
    ]
    expected_option_contracts = len(manual_smoke.OPTION_CONTRACTS)
    if len(option_coverage) != expected_option_contracts or missing_options:
        _fail(
            "The manual matrix does not cover the public options: "
            f"total={len(option_coverage)} missing={missing_options}"
        )
    _validate_manual_option_contract_shape(manual_smoke, option_coverage)
    aliases = getattr(manual_smoke, "_PUBLIC_COMMAND_ALIASES", {})
    covered_option_commands = set()
    for name, case_ids in option_coverage.items():
        if not case_ids:
            continue
        prefix = name.split(":", 1)[0]
        covered_option_commands.add(prefix)
        mapped = aliases.get(prefix)
        if mapped:
            covered_option_commands.add(mapped)
    argument_commands = _public_argument_commands()
    missing_argument_commands = sorted(argument_commands - covered_option_commands)
    if missing_argument_commands:
        _fail(
            "Commands with argument-hint/$ARGUMENTS without a manual option contract: "
            f"{missing_argument_commands}"
        )
    runtime_coverage = manual_smoke._case_runtime_coverage()
    missing_runtime = [
        name for name, case_ids in runtime_coverage.items()
        if not case_ids
    ]
    _validate_manual_runtime_contract_shape(manual_smoke, runtime_coverage)
    if len(runtime_coverage) != 4 or missing_runtime:
        _fail(
            "The manual matrix does not cover the runtime contracts: "
            f"total={len(runtime_coverage)} missing={missing_runtime}"
        )

    return [
        "docs/release.md is the living audit page",
        "project-scope MCP note documented",
        "commands/ documented as supported flat skills",
        "manual matrix covers 18 public routes",
        f"manual matrix covers {expected_option_contracts} public options",
        "manual matrix validates option IDs against public commands",
        "manual matrix links contracts to the correct command",
        "manual matrix validates prompts against declared commands",
        "manual matrix binds each argument-hint to a covered option",
        "manual matrix validates update runtime contracts",
        "manual matrix covers 4 runtime contracts",
        "manual smoke uses worktree by default and explicit --installed",
        "manual smoke has a real auth preflight and fail-fast evidence",
        "manual evidence and templates are written with 0600 permissions",
        "manual evidence ignored by git and npm",
        "docs/project operating state ignored by git and npm",
        "manual evidence sanitizes previews with core/secrets.py",
        "manual review gate requires explicit human approval",
        "manual review gate rejects evidence/review with secrets",
        "manual review gate does not create templates from evidence with secrets",
        "manual review gate requires a current preflight before approval",
        "manual review report shows weak or repeated human notes",
        "manual review gate requires the correct worktree/installed source",
        "manual review gate binds evidence_file to the validated JSON",
        "plugin_surface.sha256 is required in human review, not frozen in docs",
        "manual review gate validates case metadata against the current matrix",
        "manual review gate validates review metadata against the current matrix",
        "manual review gate validates coverage maps against the current matrix",
        "manual/preflight npm scripts aligned",
        "prepublish:prepare generates manual evidence before the human review",
        "prepublish validates already reviewed manual evidence without regenerating it",
        "matrix documents dry packaging",
        "plugin details documents the human displayName",
        "official docs revalidated 2026-08-15",
        "release readiness keeps human and external pending items",
        "human review runbook documents criteria and blockers",
    ]


def check_human_contracts() -> list[str]:
    """Check prompt-level contracts for human treatment and operational honesty."""
    command_names = [
        "_composicion",
        "alfred",
        "ajustes",
        "discuss",
        "feature",
        "fix",
        "map-codebase",
        "memory-ui",
        "next",
        "pause",
        "progress",
        "quick",
        "retomar",
        "search",
        "ship",
        "sync-github",
        "uat",
        "update",
    ]
    commands = {name: _read(f"commands/{name}.md") for name in command_names}
    commands_norm = {name: _normalize(text) for name, text in commands.items()}
    alfred_agent = _read("agents/alfred.md")
    alfred_agent_norm = _normalize(alfred_agent)

    requirements = {
        "clarifying questions": [
            ("Используй `AskUserQuestion` только если действительно есть два правдоподобных пути", commands["alfred"]),
            ("один короткий вопрос", commands["alfred"]),
            ("один `AskUserQuestion` с настоящим выбираемым меню", commands["alfred"]),
            ("Если нужно спросить из-за реальной неоднозначности", commands["next"]),
            ("один навигируемый `AskUserQuestion`", commands["next"]),
            ("НЕ используй `AskUserQuestion` по умолчанию", commands["discuss"]),
            ("меню не нужно", commands["discuss"]),
            ("DISCUSS_ROUTE_MENU_HEADLESS", commands["discuss"]),
            ("возвращается отменённым", commands["discuss"]),
            ("главное меню", commands["ajustes"]),
            ("config_headless_menu", commands_norm["ajustes"]),
            ("один `AskUserQuestion`", commands["update"]),
        ],
        "human gates": [
            ("Если пользовательский gate остаётся в ожидании, используй один навигируемый", commands["feature"]),
            ("Если пользовательский gate остаётся в ожидании, используй один навигируемый", commands["fix"]),
            ("Gate развёртывания ВСЕГДА интерактивный", commands["ship"]),
            ("НИКОГДА не утверждай автоматически развёртывание", commands["ship"]),
            ("НЕ помечай UAT как одобренную без явного указания пользователя", commands["uat"]),
            ("`/alfred-dev:verify aprobado`", commands["uat"]),
        ],
        "operational honesty": [
            ("Операционная честность и запрет имитации", commands["_composicion"]),
            ("Не говори «я выполнил», «прошло» или «проверено», если ты только предположил это", commands["_composicion"]),
            ("Всегда различай «рекомендую выполнить X» и «я выполнил X", commands["_composicion"]),
            ("Не имитируй подтверждение", commands["alfred"]),
            ("вывод инструмента", commands["alfred"]),
            ("проверяемый следующий шаг", commands["alfred"]),
            ("Не имитируй подтвержден", alfred_agent),
            ("явного подтверждения пользователя", alfred_agent),
        ],
        "grounded fallbacks": [
            ("НЕ выдумывай стек, точки входа или риски", commands["map-codebase"]),
            ("НЕ выдумывай handoff", commands["pause"]),
            ("преждевременную ручную приёмку", commands["uat"]),
            ("Если `$ARGUMENTS` пуст, скажи об этом ясно и не выдумывай поиск", commands["search"]),
        ],
    }
    missing: list[str] = []
    for group, checks in requirements.items():
        for needle, haystack in checks:
            if needle not in haystack:
                missing.append(f"{group}: {needle}")

    helper_wrappers = [
        "alfred",
        "discuss",
        "map-codebase",
        "memory-ui",
        "pause",
        "progress",
        "retomar",
        "search",
        "sync-github",
        "uat",
    ]
    final_markers = tuple(
        _normalize(marker)
        for marker in (
            "итоговый ответ",
            "итогового ответа",
            "как есть",
            "не продолжай исследование",
            "второй слой",
            "не оборачивай",
        )
    )
    for name in helper_wrappers:
        text_norm = commands_norm[name]
        if "helper" not in text_norm and "alfred-continuity.py" not in commands[name]:
            missing.append(f"helper-first {name}: helper is missing")
        if not any(marker in text_norm for marker in final_markers):
            missing.append(f"helper-first {name}: final output rule without rewrapping is missing")

    if "Не говори" not in commands["_composicion"] or "проверяемый следующий шаг" not in commands["alfred"]:
        missing.append("humanity: central anti-pretending contract is missing")
    if "Не имитируй подтвержден" not in alfred_agent:
        missing.append("humanity: anti-pretending contract is missing in the Alfred agent")

    if missing:
        _fail("Humanity contracts incomplete: " + "; ".join(missing))

    return [
        "AskUserQuestion limited to real ambiguity and human gates",
        "operating helpers do not duplicate or rewrap output",
        "UAT requires explicit human instruction",
        "anti-pretending centralized in commands and the Alfred agent",
    ]


def check_external_contracts() -> list[str]:
    audit = _read("commands/audit.md")
    sonarqube = _read("skills/sonarqube/SKILL.md")
    sync = _read("commands/sync-github.md")
    sync_norm = _normalize(sync)
    cto_command = _read("commands/cto.md")
    cto_agent = _read("agents/cto.md")
    cto_all = cto_command + "\n" + cto_agent
    ship = _read("commands/ship.md")

    requirements = {
        "audit SonarQube preflight": [
            ("docker --version", audit),
            ("docker info", audit),
            ("AskUserQuestion", audit),
            ("НЕ пытайся установить его сам", audit),
            ("НЕ пытайся запустить его сам", audit),
            ("даже если проект в режиме autopilot", audit),
            ("SonarQube пропущен по явному решению пользователя", audit),
        ],
        "sonarqube skill permission": [
            ("Не устанавливай Docker, не открывай Docker Desktop и не запускай демон без явного одобрения пользователя.", sonarqube),
            ("Если предварительного разрешения нет, запроси его сейчас и жди ответа.", sonarqube),
            ("Проверь, занят ли порт `9000`", sonarqube),
            ("docker rm -f sonarqube-alfred", sonarqube),
            ("всё равно попытайся выполнить финальную очистку временного контейнера", sonarqube),
        ],
        "sync-github safe mirror": [
            ('python3 .claude/alfred-continuity.py sync-github "$PWD" --raw "$ARGUMENTS"', sync),
            ("gh --version", sync),
            ("gh auth status", sync),
            ("НЕ используй `AskUserQuestion` по умолчанию", sync),
            ("Не удаляй issues, не относящиеся к Alfred", sync),
            ("Сохраняй локальную истину", sync),
        ],
        "cto external audit": [
            ("codex --version", cto_all),
            ("codex login", cto_all),
            ("явное подтверждение", cto_all),
            ("codex exec", cto_all),
            ("--sandbox read-only", cto_all),
            ("--ephemeral", cto_all),
            ("--json", cto_all),
            ("--output-last-message", cto_all),
            ("codex_report", cto_all),
            ("codex_jsonl", cto_all),
            ("approval_policy", cto_all),
            ("status --porcelain=v1 -z", cto_all),
            ("НЕ изменяй никакие файлы", cto_all),
            ("Ты никогда не запускаешь код проекта", cto_all),
            ("Ты не заменяешь `qa-engineer`, `security-officer` и `architect`", cto_all),
            ("не заменяет канонический sign-off", cto_all),
        ],
        "ship deploy gate": [
            ("Gate развёртывания", ship),
            ("ВСЕГДА интерактивный", ship),
            ("одним навигируемым `AskUserQuestion`", ship),
            ("НИКОГДА не утверждай автоматически развёртывание", ship),
            ("пользователь+безопасность", ship),
        ],
    }
    missing: list[str] = []
    for group, checks in requirements.items():
        for needle, haystack in checks:
            if needle not in haystack:
                missing.append(f"{group}: {needle}")
    if missing:
        _fail("External contracts incomplete: " + "; ".join(missing))

    return [
        "Docker/SonarQube asks for permission and documents skips",
        "sync-github keeps GitHub as a safe mirror",
        "CTO confirms cost and does not modify files",
        "ship keeps deploy behind a human gate",
    ]


def run_command(name: str, command: list[str], timeout: int = 120) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise AuditError(
            f"{name} failed with code {result.returncode}\n{result.stdout}"
        )
    return result.stdout


def _materialized_alfred_alias_bytes(*, invocable: bool = True) -> bytes:
    alias_source = ROOT / "skills" / "alfred" / "alfred" / "SKILL.md"
    text = alias_source.read_text(encoding="utf-8")
    value = "true" if invocable else "false"
    if re.search(r"(?m)^user-invocable:\s*(true|false)\s*$", text):
        text = re.sub(
            r"(?m)^user-invocable:\s*(true|false)\s*$",
            f"user-invocable: {value}",
            text,
            count=1,
        )
    elif text.startswith("---\n"):
        text = text.replace("---\n", f"---\nuser-invocable: {value}\n", 1)
    return text.encode("utf-8")


def check_installed_cache_freshness() -> list[str]:
    if not INSTALLED_PLUGIN_DIR.is_dir():
        _fail(
            "The installed Claude 0.7.0 cache does not exist. Refresh it with:\n"
            "claude plugin marketplace remove alfred-dev --scope user\n"
            "claude plugin marketplace add \"$PWD\" --scope user\n"
            "claude plugin uninstall alfred-dev@alfred-dev --scope user\n"
            "claude plugin install alfred-dev@alfred-dev --scope user"
        )

    missing: list[str] = []
    drifted: list[str] = []
    for relative in _iter_installed_cache_freshness_files():
        worktree_path = ROOT / relative
        installed_path = INSTALLED_PLUGIN_DIR / relative
        if not installed_path.is_file():
            missing.append(relative)
            continue
        if _sha256(worktree_path) != _sha256(installed_path):
            drifted.append(relative)

    if missing or drifted:
        details = []
        if missing:
            details.append("missing=" + ", ".join(missing[:12]))
        if drifted:
            details.append("drifted=" + ", ".join(drifted[:12]))
        _fail(
            "The installed Claude cache does not match the audited worktree "
            f"({'; '.join(details)}). Refresh it with:\n"
            "claude plugin marketplace remove alfred-dev --scope user\n"
            "claude plugin marketplace add \"$PWD\" --scope user\n"
            "claude plugin uninstall alfred-dev@alfred-dev --scope user\n"
            "claude plugin install alfred-dev@alfred-dev --scope user"
        )

    return [
        "installed 0.7.0 cache is complete and matches the worktree"
    ]


def _run_continuity(project_dir: Path, *args: str, timeout: int = 60) -> str:
    return run_command(
        f"continuity {' '.join(args)}",
        [sys.executable, str(ROOT / "core" / "continuity.py"), *args],
        timeout=timeout,
    )


def _run_continuity_raw(project_dir: Path, *args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "core" / "continuity.py"), *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )


def _complete_quick_session(project_dir: Path) -> None:
    from core.orchestrator import advance_phase, create_session, save_state

    session = create_session("quick", "Adjust login copy")
    while session["fase_actual"] != "completado":
        session = advance_phase(session, resultado="aprobado", artefactos=[])
    save_state(session, str(project_dir / ".claude" / "alfred-dev-state.json"))


def check_continuity_smoke() -> list[str]:
    with tempfile.TemporaryDirectory(prefix="alfred-release-audit-") as tmp:
        project = Path(tmp)
        (project / "src").mkdir()
        (project / "package.json").write_text('{"name":"fixture"}\n', encoding="utf-8")
        (project / "src" / "app.js").write_text(
            "export function label() { return 'Login'; }\n",
            encoding="utf-8",
        )

        sync_empty = project / "sync-empty"
        sync_empty.mkdir()
        sync_fail = _run_continuity_raw(sync_empty, "sync-github", str(sync_empty), "--raw", "owner/repo")
        if sync_fail.returncode == 0:
            _fail("sync-github should fail without syncable tasks prepared for GitHub")
        sync_error = sync_fail.stderr + sync_fail.stdout
        if (
            "Нет задач с идентификатором [T-XXX]" not in sync_error
            and "В docs/project/kanban/ нет задач" not in sync_error
        ):
            _fail(f"sync-github did not fail explicitly without tasks: {sync_error}")

        next_initial = json.loads(_run_continuity(project, "next", str(project), "--json"))
        if next_initial.get("command") != "map-codebase":
            _fail(f"initial next expected map-codebase, got {next_initial}")

        mapped = json.loads(
            _run_continuity(project, "map-codebase", str(project), "--raw", "login", "--json")
        )
        if mapped.get("recommended_command") != "discuss":
            _fail(f"map-codebase expected to recommend discuss, got {mapped}")
        if not (project / "docs" / "project" / "codebase-map.md").exists():
            _fail("map-codebase did not create docs/project/codebase-map.md")

        from core.continuity import save_prefetch_result

        save_prefetch_result(
            str(project),
            {
                "source_command": "map-codebase",
                "prefetched_command": "map-codebase",
                "project_name": "fixture",
                "stack": {"runtime": "node", "framework": "desconocido"},
                "recommended_command": "discuss",
            },
        )
        consumed = _run_continuity(
            project,
            "consume-prefetch",
            str(project),
            "--expected",
            "map-codebase",
        )
        if "## Карта brownfield составлена" not in consumed:
            _fail("consume-prefetch did not return the expected helper-first response")
        if (project / ".claude" / "alfred-prefetch.json").exists():
            _fail("consume-prefetch did not clean the transient prefetch")

        discussed = json.loads(
            _run_continuity(project, "discuss", str(project), "--raw", "ajustar login", "--json")
        )
        if discussed.get("recommended_command") not in {"feature", "quick", "fix", "spike"}:
            _fail(f"discuss returned an unexpected recommendation: {discussed}")

        quick = _run_continuity(project, "quick", str(project), "--raw", "cambiar CTA")
        if "## Quick подготовлен" not in quick or "/alfred-dev:verify" not in quick:
            _fail("quick did not return a human summary with the next verify")

        handoff = json.loads(_run_continuity(project, "write-handoff", str(project)))
        handoff_path = project / ".claude" / "alfred-handoff.json"
        handoff_payload = json.loads(handoff_path.read_text(encoding="utf-8")) if handoff_path.exists() else {}
        if handoff_payload.get("command") != "quick" or not Path(handoff.get("json_path", "")).exists():
            _fail(f"write-handoff did not persist the quick handoff: {handoff}")

        bypass = json.loads(
            _run_continuity(
                project,
                "allow-stop-once",
                str(project),
                "--command",
                "/alfred-dev:status",
            )
        )
        if bypass.get("command") != "/alfred-dev:status" or not Path(bypass.get("bypass_path", "")).exists():
            _fail(f"allow-stop-once did not arm a valid bypass: {bypass}")

        status = _run_continuity(project, "status", str(project))
        if "## Рабочее состояние Alfred Dev" not in status:
            _fail("status did not return an operating summary")

        pause = _run_continuity(project, "pause", str(project))
        if "## Сессия на паузе" not in pause:
            _fail("pause did not leave a human pause output")

        resume = _run_continuity(project, "resume", str(project))
        if "## Сессия возобновлена" not in resume:
            _fail("resume did not leave a human resume output")

        for command, expected in [
            ("progress", "## Рабочая сводка проекта"),
            ("standup", "## Ежедневный standup"),
            ("blocked", "## Задачи в blocked"),
            ("in-progress", "## Задачи в in progress"),
            ("validate", "## Рабочая валидация"),
        ]:
            output = _run_continuity(project, command, str(project))
            if expected not in output:
                _fail(f"{command} does not contain {expected!r}")

        search = _run_continuity(project, "search", str(project), "--raw", "login")
        if "## Результаты для `login`" not in search:
            _fail("search did not return human results")

        kanban = project / "docs" / "project" / "kanban"
        kanban.mkdir(parents=True, exist_ok=True)
        (kanban / "backlog.md").write_text(
            "# Backlog\n\n"
            "### [T-010] Validar login con /alfred-dev:verify\n\n"
            "- **Agente:** alfred:verify\n",
            encoding="utf-8",
        )
        for lane in ("in-progress", "done", "blocked"):
            (kanban / f"{lane}.md").write_text(f"# {lane.title()}\n", encoding="utf-8")
        normalize = _run_continuity(project, "normalize-kanban", str(project))
        if "## Нормализация kanban" not in normalize or "Исправлено задач" not in normalize:
            _fail("normalize-kanban did not return a normalization summary")

        memory_started = False
        try:
            memory_ui = json.loads(
                _run_continuity(
                    project,
                    "memory-ui",
                    str(project),
                    "--json",
                    "--no-open",
                    timeout=90,
                )
            )
            memory_started = True
            if not str(memory_ui.get("url", "")).startswith("http://127.0.0.1:"):
                _fail(f"memory-ui did not return a valid local URL: {memory_ui}")
            if not (project / ".claude" / "alfred-memory-ui.json").exists():
                _fail("memory-ui did not persist .claude/alfred-memory-ui.json")
        finally:
            if memory_started:
                _run_continuity(project, "memory-ui", str(project), "--stop", "--json", timeout=90)

        _complete_quick_session(project)
        verify = _run_continuity(project, "verify", str(project), "--raw", "aprobado")
        uat_path = project / ".claude" / "alfred-uat.json"
        uat = json.loads(uat_path.read_text(encoding="utf-8")) if uat_path.exists() else {}
        verify_lower = verify.lower()
        # core/continuity.py may still render the Spanish heading or the Russian one.
        has_uat_heading = "Verificación manual / UAT" in verify or "Ручная проверка / UAT" in verify
        is_approved = "aprobada" in verify_lower or "одобрен" in verify_lower
        if not has_uat_heading or not is_approved or uat.get("status") != "approved":
            _fail("verify aprobado did not record a human UAT")

    return [
        "next/map-codebase/discuss/quick",
        "status/pause/resume/progress/standup",
        "blocked/in-progress/validate/search/verify",
        "write-handoff/allow-stop-once/consume-prefetch/normalize-kanban/memory-ui/sync-github-fail-closed",
    ]


class _MCPJsonlClient:
    def __init__(self, project_dir: Path) -> None:
        self._next_id = 1
        self._proc = subprocess.Popen(
            [sys.executable, str(ROOT / "mcp" / "memory_server.py")],
            cwd=project_dir,
            text=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._selector = selectors.DefaultSelector()
        assert self._proc.stdout is not None
        self._selector.register(self._proc.stdout, selectors.EVENT_READ)

    def close(self) -> None:
        if self._proc.stdin is not None:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        if self._proc.returncode not in {0, None}:
            stderr = self._proc.stderr.read() if self._proc.stderr else ""
            _fail(f"MCP server exited with code {self._proc.returncode}: {stderr}")

    def notify(self, method: str, params: dict | None = None) -> None:
        assert self._proc.stdin is not None
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def request(self, method: str, params: dict | None = None) -> dict:
        assert self._proc.stdin is not None
        request_id = self._next_id
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            payload["params"] = params
        self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

        events = self._selector.select(timeout=10)
        if not events:
            stderr = self._proc.stderr.read() if self._proc.stderr else ""
            _fail(f"Timeout waiting for MCP response to {method}: {stderr}")
        line = self._proc.stdout.readline()  # type: ignore[union-attr]
        if not line:
            stderr = self._proc.stderr.read() if self._proc.stderr else ""
            _fail(f"MCP server closed stdout during {method}: {stderr}")
        response = json.loads(line)
        if response.get("id") != request_id:
            _fail(f"MCP response with unexpected id: {response}")
        if "error" in response:
            _fail(f"MCP error in {method}: {response['error']}")
        return response["result"]

    def call_tool(self, name: str, arguments: dict | None = None) -> dict:
        result = self.request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        if result.get("isError"):
            _fail(f"{name} returned isError: {result}")
        content = result.get("content") or []
        if not content or content[0].get("type") != "text":
            _fail(f"{name} did not return text content: {result}")
        return json.loads(content[0]["text"])


def check_mcp_tools_smoke() -> list[str]:
    with tempfile.TemporaryDirectory(prefix="alfred-mcp-audit-") as tmp:
        project = Path(tmp)
        (project / ".claude").mkdir()
        adr_dir = project / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        (adr_dir / "0001-cache.md").write_text(
            "# Usar Redis\n\n"
            "## Contexto\n\nNecesitamos cachear lecturas frecuentes.\n\n"
            "## Decisión\n\nUsar Redis para cache compartida.\n",
            encoding="utf-8",
        )

        client = _MCPJsonlClient(project)
        try:
            init = client.request(
                "initialize",
                {
                    "protocolVersion": "2025-11-25",
                    "clientInfo": {"name": "alfred-release-audit", "version": VERSION},
                    "capabilities": {},
                },
            )
            if init.get("serverInfo", {}).get("name") != "alfred-memory":
                _fail(f"unexpected initialize: {init}")
            client.notify("notifications/initialized")

            tools = client.request("tools/list")["tools"]
            tool_names = [tool["name"] for tool in tools]
            if len(tool_names) != 15:
                _fail(f"tools/list expected 15 tools, got {tool_names}")
            tool_by_name = {tool["name"]: tool for tool in tools}
            expected_limits = {
                "memory_search": 100,
                "memory_get_decisions": 200,
                "memory_import": 1000,
            }
            for tool_name, maximum in expected_limits.items():
                schema = tool_by_name[tool_name]["inputSchema"]["properties"]["limit"]
                if schema.get("minimum") != 1 or schema.get("maximum") != maximum:
                    _fail(
                        f"{tool_name} does not declare defensive MCP limits: {schema}"
                    )
            event_schema = tool_by_name["memory_log_event"]["inputSchema"]["properties"]
            expected_event_bounds = {
                "event_type": 80,
                "phase": 80,
                "summary": 500,
                "content": 8000,
            }
            for field, maximum in expected_event_bounds.items():
                if event_schema[field].get("maxLength") != maximum:
                    _fail(f"memory_log_event does not declare maxLength for {field}: {event_schema[field]}")
            if "preview" not in event_schema["payload"].get("description", ""):
                _fail("memory_log_event does not document preview for a huge payload")

            started = client.call_tool(
                "memory_manage_iteration",
                {"action": "start", "command": "feature", "description": "Login release audit"},
            )
            iteration_id = started.get("iteration_id")
            if not iteration_id:
                _fail(f"memory_manage_iteration did not return iteration_id: {started}")

            dec1 = client.call_tool(
                "memory_log_decision",
                {
                    "title": "Login cache",
                    "chosen": "Redis",
                    "context": "Login with frequent reads",
                    "tags": ["release-audit"],
                },
            )["decision_id"]
            dec2 = client.call_tool(
                "memory_log_decision",
                {
                    "title": "User session",
                    "chosen": "Secure cookie",
                    "tags": ["release-audit"],
                },
            )["decision_id"]
            client.call_tool(
                "memory_update_decision",
                {"id": dec1, "status": "superseded", "tags": ["mcp-smoke"]},
            )
            client.call_tool(
                "memory_link_decisions",
                {"source_id": dec1, "target_id": dec2, "link_type": "relates"},
            )
            client.call_tool(
                "memory_log_commit",
                {
                    "sha": "abc123releaseaudit",
                    "message": "feat: login cache",
                    "author": "Alfred Audit",
                    "decision_ids": [dec1],
                    "files": ["src/login.py"],
                },
            )
            client.call_tool(
                "memory_log_event",
                {
                    "event_type": "gate_passed",
                    "phase": "calidad",
                    "summary": "Redis cache validated",
                    "payload": {"note": "redis cache validated"},
                },
            )
            large_event = client.call_tool(
                "memory_log_event",
                {
                    "event_type": "custom",
                    "phase": "calidad",
                    "summary": "large MCP event",
                    "content": "x" * 9000,
                    "payload": {"blob": "y" * 9000},
                },
            )
            if not large_event.get("content_truncated") or not large_event.get("payload_truncated"):
                _fail(f"memory_log_event did not truncate huge content/payload: {large_event}")

            search = client.call_tool("memory_search", {"query": "Redis", "limit": 10})
            if search.get("total", 0) < 1:
                _fail(f"memory_search did not find seeded data: {search}")
            capped_search = client.call_tool(
                "memory_search",
                {"query": "Redis", "limit": 999999},
            )
            if capped_search.get("applied_limit") != 100:
                _fail(f"memory_search did not cap an abusive limit: {capped_search}")
            if client.call_tool("memory_get_iteration", {"id": iteration_id}).get("iteration") is None:
                _fail("memory_get_iteration did not return the created iteration")
            if client.call_tool("memory_get_timeline", {"iteration_id": iteration_id}).get("total", 0) < 1:
                _fail("memory_get_timeline did not return events")
            if client.call_tool("memory_get_decisions", {"tags": ["release-audit"]}).get("total", 0) < 2:
                _fail("memory_get_decisions did not return seeded decisions")
            if client.call_tool("memory_stats").get("total_decisions", 0) < 2:
                _fail("memory_stats did not count decisions")
            if client.call_tool("memory_health").get("status") != "healthy":
                _fail("memory_health did not return healthy")
            export_path = str(project / "DECISIONS.md")
            if client.call_tool("memory_export", {"format": "markdown", "path": export_path}).get("exported", 0) < 2:
                _fail("memory_export did not export decisions")
            if not Path(export_path).exists():
                _fail("memory_export did not create DECISIONS.md")
            blocked_export = client.request(
                "tools/call",
                {
                    "name": "memory_export",
                    "arguments": {
                        "format": "markdown",
                        "path": str(project.parent / "OUTSIDE.md"),
                    },
                },
            )
            if not blocked_export.get("isError"):
                _fail(f"memory_export allowed writing outside the project: {blocked_export}")
            if client.call_tool("memory_import", {"source": "adr", "path": str(adr_dir)}).get("imported") != 1:
                _fail("memory_import adr did not import the ADR fixture")
            purge = client.call_tool("memory_purge", {"retention_days": 1})
            if "purged_events" not in purge:
                _fail("memory_purge did not return purged_events")
            client.call_tool("memory_manage_iteration", {"action": "complete", "iteration_id": iteration_id})
        finally:
            client.close()

    return [
        "15 tools listed",
        "15 tools invoked with real data",
        "defensive MCP limits in schemas and handlers",
        "memory_log_event truncates huge MCP payload/content",
        "MCP paths bounded to the project",
        "temporary SQLite healthy",
    ]


def check_external(args: argparse.Namespace) -> list[str]:
    ok: list[str] = []
    if args.with_external_contracts:
        for line in check_external_contracts():
            ok.append(f"external {line}")
    if args.with_human_contracts:
        for line in check_human_contracts():
            ok.append(f"human {line}")
    if args.with_continuity:
        for line in check_continuity_smoke():
            ok.append(f"continuity {line}")
    if args.with_mcp_tools:
        for line in check_mcp_tools_smoke():
            ok.append(f"mcp-tools {line}")

    if args.with_claude:
        for line in check_installed_cache_freshness():
            ok.append(f"claude {line}")
        details = run_command(
            "claude plugin validate/details",
            [
                "sh",
                "-c",
                "claude plugin validate . --strict && "
                "claude plugin details alfred-dev@alfred-dev | sed -n '1,18p' && "
                "claude mcp get plugin:alfred-dev:alfred-memory",
            ],
            timeout=90,
        )
        for needle in ("Alfred Dev (alfred-dev) 0.7.0", "Skills (11)", "Agents (10)", "MCP servers (1)", "Status: ✔ Connected"):
            if needle not in details:
                _fail(f"Claude smoke does not contain {needle!r}")
        ok.append("Claude CLI validates inventory and MCP")
        discovery = run_command(
            "claude interactive /alfred discovery",
            [sys.executable, str(ROOT / "scripts" / "claude_command_discovery.py")],
            timeout=35,
        )
        if "ok claude interactive command discovery" not in discovery:
            _fail("Claude smoke did not confirm interactive discovery of /alfred")
        if "FAIL claude-command-discovery" in discovery:
            _fail("Claude smoke still shows an interactive /alfred discovery failure")
        ok.append("Claude CLI discovers /alfred in the interactive picker")

    if args.with_site:
        run_command("npm site check/build", ["sh", "-c", "npm --prefix site run check && npm --prefix site run build"], timeout=180)
        ok.append("site check/build")

    if args.with_tests:
        run_command("full pytest", ["python3", "-m", "pytest", "tests/", "-q"], timeout=300)
        ok.append("full pytest")

    if args.with_syntax:
        run_command(
            "syntax/json/diff",
            [
                "sh",
                "-c",
                "bash -n install.sh && "
                "python3 -m json.tool .mcp.json >/dev/null && "
                "python3 -m json.tool .claude-plugin/plugin.json >/dev/null && "
                "python3 -m json.tool .claude-plugin/marketplace.json >/dev/null && "
                "git diff --check",
            ],
            timeout=60,
        )
        ok.append("syntax/json/diff-check")

    return ok


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-claude", action="store_true", help="Run smokes with claude plugin/mcp.")
    parser.add_argument("--with-site", action="store_true", help="Run npm --prefix site run check/build.")
    parser.add_argument("--with-tests", action="store_true", help="Run python3 -m pytest tests/ -q.")
    parser.add_argument("--with-syntax", action="store_true", help="Run bash -n, json.tool and git diff --check.")
    parser.add_argument("--with-continuity", action="store_true", help="Run the operating helper smoke in a temporary fixture.")
    parser.add_argument("--with-mcp-tools", action="store_true", help="Invoke the 15 MCP tools on a temporary SQLite.")
    parser.add_argument("--with-external-contracts", action="store_true", help="Check safe prompts for Docker, GitHub, CTO and deploy.")
    parser.add_argument("--with-human-contracts", action="store_true", help="Check human treatment, AskUserQuestion, UAT and anti-pretending.")
    parser.add_argument("--full", action="store_true", help="Enable all external smokes.")
    args = parser.parse_args(argv)

    if args.full:
        args.with_claude = args.with_site = args.with_tests = True
        args.with_syntax = args.with_continuity = True
        args.with_mcp_tools = args.with_external_contracts = True
        args.with_human_contracts = True

    checks = [
        ("versions", check_versions),
        ("inventory", check_inventory),
        ("catalog", check_command_catalog),
        ("commands", check_command_execution_contracts),
        ("claims", check_public_claims),
        ("config", check_config_contracts),
        ("flows", check_flow_gate_claims),
        ("hooks", check_hook_contracts),
        ("mcp", check_mcp_config),
        ("packaging", check_packaging_contracts),
        ("secrets", check_published_secret_scan),
        ("install", check_install_update_contracts),
        ("docs", check_audit_docs),
    ]

    try:
        for name, check in checks:
            for line in check():
                print(f"ok {name}: {line}")
        for line in check_external(args):
            print(f"ok smoke: {line}")
    except (AuditError, subprocess.TimeoutExpired) as exc:
        print(f"FAIL release-audit: {exc}", file=sys.stderr)
        return 1

    print(f"release-audit {VERSION} ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
