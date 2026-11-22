#!/usr/bin/env python3
"""Public surface contracts that prevent release drift.

These tests check that the main plugin numbers and claims (agents,
commands, skills, domains, phases and install requirements) match between
the real repo state and the docs and manifests published to the user.
"""

from collections import Counter
import json
import os
import re
import unicodedata
import unittest


ROOT = os.path.join(os.path.dirname(__file__), "..")
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
AGENT_MODEL_ALIASES = {"sonnet", "opus", "haiku", "fable", "inherit"}
AGENT_MODEL_ID_RE = re.compile(r"^claude-[a-z0-9]+(?:-[a-z0-9]+)*$")
ALFRED_AGENT_MODEL_POLICY = Counter({"inherit": 10})
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


def _read(relative_path: str) -> str:
    path = os.path.normpath(os.path.join(ROOT, relative_path))
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _read_json(relative_path: str):
    return json.loads(_read(relative_path))


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _slice_between(text: str, start: str, end: str) -> str:
    start_index = text.index(start)
    end_index = text.index(end, start_index)
    return text[start_index:end_index]


def _count_skill_files() -> int:
    count = 0
    for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, "skills")):
        count += filenames.count("SKILL.md")
    return count


def _count_skill_domains() -> int:
    domains = set()
    skills_root = os.path.join(ROOT, "skills")
    for dirpath, _dirnames, filenames in os.walk(skills_root):
        if "SKILL.md" not in filenames:
            continue
        rel = os.path.relpath(dirpath, skills_root)
        domain = rel.split(os.sep, 1)[0]
        domains.add(domain)
    return len(domains)


def _count_agent_files() -> int:
    count = 0
    for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, "agents")):
        count += sum(1 for filename in filenames if filename.endswith(".md"))
    return count


def _iter_agent_files():
    agent_files = []
    for dirpath, _dirnames, filenames in os.walk(os.path.join(ROOT, "agents")):
        for filename in filenames:
            if filename.endswith(".md"):
                agent_files.append(os.path.join(dirpath, filename))
    return sorted(agent_files)


def _iter_manifest_skill_files():
    plugin = _read_json(".claude-plugin/plugin.json")
    skill_files = []
    declared = plugin.get("skills")
    roots = declared if declared else ["./skills/"]

    for relative_path in roots:
        absolute = os.path.join(ROOT, relative_path.lstrip("./"))
        if os.path.isdir(absolute):
            for dirpath, _dirnames, filenames in os.walk(absolute):
                if "SKILL.md" in filenames:
                    skill_files.append(os.path.join(dirpath, "SKILL.md"))
            continue

        if os.path.isfile(absolute) and os.path.basename(absolute) == "SKILL.md":
            skill_files.append(absolute)

    return sorted(skill_files)


def _iter_manifest_command_files():
    plugin = _read_json(".claude-plugin/plugin.json")
    return [
        os.path.join(ROOT, relative_path.lstrip("./"))
        for relative_path in plugin["commands"]
    ]


def _parse_frontmatter_fields(path: str):
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(ROOT, path))

    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    if not text.startswith("---\n"):
        return {}

    fields = {}
    for line in text.splitlines()[1:]:
        if line.strip() == "---":
            break
        match = re.match(r"^([A-Za-z][A-Za-z_-]*)\s*:\s*(.*)$", line)
        if not match:
            continue
        key, value = match.groups()
        fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def _frontmatter_field_text(path: str, field: str) -> str:
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(ROOT, path))

    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    if not text.startswith("---\n"):
        return ""

    lines = text.split("---", 2)[1].splitlines()
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

        collected = []
        for following in lines[index + 1:]:
            if re.match(r"^[A-Za-z][A-Za-z_-]*\s*:", following):
                break
            if following.startswith((" ", "\t")):
                collected.append(following.strip())
        return "\n".join(collected)
    return ""


def _is_supported_agent_model(model: str) -> bool:
    return model in AGENT_MODEL_ALIASES or AGENT_MODEL_ID_RE.fullmatch(model) is not None


def _frontmatter_tool_names(tools: str):
    names = set()
    for item in tools.split(","):
        name = item.strip()
        if not name:
            continue
        names.add(re.split(r"[\s(]", name, maxsplit=1)[0])
    return names


def _frontmatter_tool_rule_names(rules: str):
    return set(
        re.findall(r"(?:^|[\s,])([A-Za-z][A-Za-z0-9_]*)(?:\(|(?=$|[\s,]))", rules)
    )


def _frontmatter_field_rule_text(path: str, field: str):
    if not os.path.isabs(path):
        path = os.path.normpath(os.path.join(ROOT, path))

    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()

    if not text.startswith("---\n"):
        return ""

    lines = text.split("---", 2)[1].splitlines()
    values = []
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


class TestRuntimeSurfaceCounts(unittest.TestCase):
    def test_manifest_and_filesystem_reflect_current_counts(self):
        plugin = _read_json(".claude-plugin/plugin.json")
        published_skill_files = _iter_manifest_skill_files()

        self.assertEqual(len(plugin["commands"]), 19)
        self.assertNotIn("agents", plugin)
        self.assertEqual(_count_agent_files(), 10)
        self.assertNotIn("mcpServers", plugin)
        self.assertEqual(_count_skill_files(), 11)
        self.assertEqual(len(published_skill_files), 11)
        self.assertEqual(len(set(published_skill_files)), 11)

        for relative_path in plugin["commands"]:
            absolute = os.path.join(ROOT, relative_path.lstrip("./"))
            self.assertTrue(
                os.path.exists(absolute),
                f"Resource declared in plugin.json does not exist: {relative_path}",
            )
        self.assertTrue(os.path.exists(os.path.join(ROOT, ".mcp.json")))
        mcp = _read_json(".mcp.json")
        alfred_memory = mcp["mcpServers"]["alfred-memory"]
        self.assertEqual(alfred_memory["command"], "python3")
        self.assertIn("memory_server.py", alfred_memory["args"][0])
        self.assertIn("CLAUDE_PLUGIN_ROOT", alfred_memory["args"][0])

    def test_published_skills_have_canonical_frontmatter(self):
        skill_names = {}
        for skill_path in _iter_manifest_skill_files():
            frontmatter = _parse_frontmatter_fields(skill_path)
            unknown = set(frontmatter) - SKILL_SUPPORTED_FIELDS
            self.assertFalse(
                unknown,
                f"Unsupported skill frontmatter fields in {skill_path}: {unknown}",
            )
            self.assertTrue(
                frontmatter.get("name"),
                f"Missing `name` in the frontmatter of {skill_path}",
            )
            self.assertTrue(
                frontmatter.get("description"),
                f"Missing `description` in the frontmatter of {skill_path}",
            )
            listing_text_length = len(
                _frontmatter_field_text(skill_path, "description")
                + _frontmatter_field_text(skill_path, "when_to_use")
            )
            self.assertLessEqual(
                listing_text_length,
                SKILL_LISTING_TEXT_LIMIT,
                f"description + when_to_use exceeds the Claude Code listing limit in {skill_path}: {listing_text_length}",
            )
            expected_name = os.path.basename(os.path.dirname(skill_path))
            self.assertEqual(
                frontmatter.get("name"),
                expected_name,
                f"The skill name must match its directory in {skill_path}",
            )
            for boolean_field in SKILL_BOOLEAN_FIELDS:
                value = frontmatter.get(boolean_field)
                if value:
                    self.assertIn(
                        value.lower(),
                        SKILL_BOOLEAN_VALUES,
                        f"{boolean_field} must be a boolean in {skill_path}: {value}",
                    )
            model = frontmatter.get("model")
            if model:
                self.assertTrue(
                    _is_supported_agent_model(model),
                    f"Skill model not supported by current Claude Code in {skill_path}: {model}",
                )
            effort = frontmatter.get("effort")
            if effort:
                self.assertIn(
                    effort,
                    SKILL_EFFORT_VALUES,
                    f"Skill effort not supported by current Claude Code in {skill_path}: {effort}",
                )
            context = frontmatter.get("context")
            if context:
                self.assertIn(
                    context,
                    SKILL_CONTEXT_VALUES,
                    f"Skill context not supported by current Claude Code in {skill_path}: {context}",
                )
            if frontmatter.get("agent"):
                self.assertEqual(
                    context,
                    "fork",
                    f"Use the agent field only with context: fork in {skill_path}",
                )
            shell = frontmatter.get("shell")
            if shell:
                self.assertIn(
                    shell,
                    SKILL_SHELL_VALUES,
                    f"Skill shell not supported by current Claude Code in {skill_path}: {shell}",
                )
            for tools_field in ("allowed-tools", "disallowed-tools"):
                unknown_tools = [
                    tool_name
                    for tool_name in _frontmatter_tool_rule_names(
                        _frontmatter_field_rule_text(skill_path, tools_field)
                    )
                    if not _is_known_permission_rule_name(tool_name)
                ]
                self.assertFalse(
                    unknown_tools,
                    f"Skill {tools_field} declares unknown tools in {skill_path}: {unknown_tools}",
                )
            skill_names.setdefault(frontmatter["name"], []).append(skill_path)
        duplicated = {
            name: paths for name, paths in skill_names.items() if len(paths) > 1
        }
        self.assertFalse(duplicated, f"Skills with a duplicate name: {duplicated}")

    def test_published_commands_have_current_frontmatter_fields(self):
        for command_path in _iter_manifest_command_files():
            frontmatter = _parse_frontmatter_fields(command_path)
            unknown = set(frontmatter) - COMMAND_SUPPORTED_FIELDS
            self.assertFalse(
                unknown,
                f"Unsupported command frontmatter fields in {command_path}: {unknown}",
            )
            self.assertTrue(
                frontmatter.get("description"),
                f"Missing `description` in the frontmatter of {command_path}",
            )
            model = frontmatter.get("model")
            if model:
                self.assertTrue(
                    _is_supported_agent_model(model),
                    f"Command model not supported by current Claude Code in {command_path}: {model}",
                )
            for tools_field in ("allowed-tools", "disallowed-tools"):
                unknown_tools = [
                    tool_name
                    for tool_name in _frontmatter_tool_rule_names(
                        _frontmatter_field_rule_text(command_path, tools_field)
                    )
                    if not _is_known_permission_rule_name(tool_name)
                ]
                self.assertFalse(
                    unknown_tools,
                    f"Command {tools_field} declares unknown tools in {command_path}: {unknown_tools}",
                )

    def test_plugin_agent_frontmatter_avoids_fields_ignored_by_claude_plugins(self):
        supported = {
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
        ignored_by_plugin_agents = {"hooks", "mcpServers", "permissionMode"}
        model_counts = Counter()

        for agent_path in _iter_agent_files():
            frontmatter = _parse_frontmatter_fields(agent_path)
            field_names = set(frontmatter)
            self.assertTrue(
                {"name", "description", "model"}.issubset(field_names),
                f"Agent {agent_path} must declare name, description and model",
            )
            self.assertFalse(
                field_names & ignored_by_plugin_agents,
                f"Claude ignores these fields in plugin agents: {agent_path}",
            )
            self.assertFalse(
                field_names - supported - ignored_by_plugin_agents,
                f"Unsupported frontmatter fields in {agent_path}",
            )
            model = frontmatter["model"]
            model_counts[model] += 1
            self.assertTrue(
                _is_supported_agent_model(model),
                f"Model not supported by current Claude Code in {agent_path}: {model}",
            )
            color = frontmatter.get("color")
            self.assertTrue(color, f"Agent {agent_path} must declare a color")
            self.assertIn(
                color,
                AGENT_COLOR_VALUES,
                f"Color not supported by current Claude Code in {agent_path}: {color}",
            )
            self.assertFalse(
                _frontmatter_tool_names(frontmatter.get("tools", ""))
                & SUBAGENT_UNAVAILABLE_TOOLS,
                f"Agent {agent_path} lists tools that are not available in subagents",
            )
            unknown_tools = [
                tool_name
                for tool_name in _frontmatter_tool_names(frontmatter.get("tools", ""))
                if not _is_known_agent_tool_name(tool_name)
            ]
            self.assertFalse(
                unknown_tools,
                f"Agent {agent_path} lists unknown tools: {unknown_tools}",
            )
            agent_text = _read(os.path.relpath(agent_path, ROOT))
            self.assertFalse(
                [tool for tool in SUBAGENT_UNAVAILABLE_TOOLS if tool in agent_text],
                f"Agent {agent_path} instructs tools that are not available in subagents",
            )

        self.assertEqual(model_counts, ALFRED_AGENT_MODEL_POLICY)

    def test_manual_only_skills_keep_explicit_disable_model_invocation(self):
        manual_only = [
            "skills/style-direction/SKILL.md",
            "skills/incident-response/SKILL.md",
            "skills/sonarqube/SKILL.md",
            "skills/pr-workflow/SKILL.md",
        ]

        for relative_path in manual_only:
            frontmatter = _parse_frontmatter_fields(relative_path)
            self.assertEqual(
                frontmatter.get("disable-model-invocation"),
                "true",
                f"Manual skill {relative_path} must keep disable-model-invocation: true",
            )

    def test_alfred_is_a_published_plugin_command(self):
        plugin = _read_json(".claude-plugin/plugin.json")
        command_names = {
            os.path.splitext(os.path.basename(relative_path))[0]
            for relative_path in plugin["commands"]
        }
        skill_names = {
            _parse_frontmatter_fields(skill_path).get("name")
            for skill_path in _iter_manifest_skill_files()
        }
        collisions = sorted(name for name in (skill_names & command_names) if name)
        self.assertEqual(collisions, [])
        self.assertIn("alfred", command_names)
        self.assertIn("./commands/alfred.md", plugin["commands"])


class TestReadmeAndDocsSurface(unittest.TestCase):
    def test_readme_matches_current_public_claims(self):
        readme = _read("README.md")
        self.assertIn(_normalize("11 плоских skills"), _normalize(readme))
        self.assertIn("Python 3.10+", readme)
        self.assertIn("## Новое в v0.7.0", readme)

    def test_docs_readme_and_architecture_match_current_surface(self):
        docs_readme = _read("docs/README.md")
        architecture = _read("docs/architecture.md")
        agents_readme = _read("docs/agents/README.md")

        self.assertIn(_normalize("10 агентов"), _normalize(docs_readme))
        self.assertIn("11 skills", _normalize(docs_readme))
        self.assertIn(_normalize("19 команд"), _normalize(architecture))
        self.assertIn("Манифест не объявляет ключ `agents`", architecture)
        self.assertIn("optional_agents.py", architecture)
        self.assertIn("build_optional_agent_group_menus()", architecture)
        self.assertNotIn("TASK_KEYWORDS", architecture)
        self.assertIn("визуальный стиль", agents_readme)
        self.assertIn("style-direction", _read("docs/skills.md"))

    def test_skills_docs_cover_manual_and_special_domains_in_catalog(self):
        skills_doc = _read("docs/skills.md")
        self.assertIn("incident-response", skills_doc)
        self.assertIn("style-direction", skills_doc)
        self.assertIn("sonarqube", skills_doc)
        self.assertIn("memory", skills_doc)

    def test_every_manifest_agent_has_public_docs_page(self):
        docs_readme = _read("docs/README.md")
        agents_index = _read("docs/agents/README.md")

        for absolute_agent in _iter_agent_files():
            relative_path = os.path.relpath(absolute_agent, ROOT)
            agent_name = os.path.splitext(os.path.basename(relative_path))[0]
            public_doc = f"docs/agents/{agent_name}.md"
            absolute_doc = os.path.join(ROOT, public_doc)
            self.assertTrue(
                os.path.exists(absolute_doc),
                f"Missing public page for agent {agent_name}: {public_doc}",
            )
            self.assertIn(
                f"agents/{agent_name}.md",
                docs_readme,
                f"docs/README.md does not link the public page of {agent_name}",
            )
            self.assertIn(
                f"[{agent_name}.md]({agent_name}.md)",
                agents_index,
                f"docs/agents/README.md does not link the public page of {agent_name}",
            )

    def test_feature_docs_protect_designer_phase(self):
        flows = _read("docs/flows.md")
        feature_command = _read("commands/feature.md")
        cto = _read("docs/agents/cto.md")

        self.assertIn("style", _normalize(flows))
        self.assertIn("designer", _normalize(feature_command))
        self.assertIn("cto", _normalize(cto))

    def test_large_commands_define_canonical_closeout_contracts(self):
        feature_command = _read("commands/feature.md")
        quick_command = _read("commands/quick.md")
        fix_command = _read("commands/fix.md")
        ship_command = _read("commands/ship.md")
        audit_command = _read("commands/audit.md")

        self.assertIn("## Каноничное завершение команды", feature_command)
        self.assertIn(".claude/alfred-dev-state.json", feature_command)
        self.assertIn("docs/project/current.md", feature_command)
        self.assertIn("AskUserQuestion", feature_command)
        self.assertIn("ожидаемый следующий шаг", feature_command)

        self.assertIn("## Каноничное завершение команды", quick_command)
        self.assertIn("свободной планировкой", quick_command)
        self.assertIn("docs/project/traceability.md", quick_command)
        self.assertIn("/alfred-dev:uat", quick_command)

        self.assertIn("## Каноничное завершение команды", fix_command)
        self.assertIn("баг/первопричину в работе", fix_command)
        self.assertIn("docs/project/progress.md", fix_command)

        self.assertIn("## Каноничное завершение команды", ship_command)
        self.assertIn("Gate развёртывания должен решаться одним навигируемым `AskUserQuestion`", ship_command)
        self.assertIn("текущую фазу релиза", ship_command)
        self.assertIn("пока не разворачивать", ship_command)

        self.assertIn("## Каноничное завершение команды", audit_command)
        self.assertIn("preflight SonarQube требует решения человека", audit_command)
        self.assertIn("действенную сводку для руководства", audit_command)
        self.assertIn("не заменяет находки", audit_command)

    def test_hooks_docs_keep_dangerous_command_guard_fail_closed(self):
        hooks_doc_norm = _normalize(_read("docs/hooks.md"))
        self.assertIn(_normalize("политика этого хука **fail-closed**"), hooks_doc_norm)
        self.assertIn("dangerous-command-guard.py", hooks_doc_norm)

    def test_docs_navigation_keeps_public_plugin_docs_only(self):
        docs_readme = _read("docs/README.md")
        self.assertNotIn("[audit.md](audit.md)", docs_readme)
        self.assertNotIn("internal/docs-audit.md", docs_readme)
        self.assertNotIn("internal/", docs_readme)
        self.assertIn("release.md", docs_readme)
        self.assertNotIn("release-audit-0.6.0.md", docs_readme)
        self.assertNotIn("promise-evidence-0.6.0.md", docs_readme)

    def test_configuration_surface_uses_canonical_phase_schema(self):
        readme = _read("README.md")
        config_command_norm = _normalize(_read("commands/config.md"))
        configuration_doc_norm = _normalize(_read("docs/configuration.md"))

        readme_config = _slice_between(
            readme,
            "## Конфигурация",
            "## Отказ от ответственности",
        )
        self.assertIn("delivery: autonomous", readme_config)
        self.assertIn("cto: true", readme_config)
        self.assertNotIn("security: autonomous", readme_config)
        self.assertNotIn("devops: semi-autonomous", readme_config)

        self.assertIn(
            "product, architecture, development, quality, documentation, delivery",
            config_command_norm,
        )
        self.assertIn(_normalize("главное меню"), config_command_norm)
        self.assertIn(_normalize("Неинтерактивный режим"), config_command_norm)
        self.assertIn("config_headless_menu", config_command_norm)
        self.assertIn(_normalize("возвращается отменённым"), config_command_norm)
        self.assertIn("core/config_cli.py", config_command_norm)
        self.assertIn("меню", config_command_norm)
        self.assertIn("build_config_section_summaries()", config_command_norm)
        self.assertIn("build_config_section_menu()", config_command_norm)
        self.assertIn("apply_config_section_update()", config_command_norm)
        self.assertIn("build_config_section_change_preview()", config_command_norm)
        self.assertIn("update_config_section()", config_command_norm)
        self.assertIn("update_project_config_section()", config_command_norm)
        self.assertIn("cto: false", configuration_doc_norm)
        self.assertIn("build_config_section_summaries()", configuration_doc_norm)
        self.assertIn("build_config_section_menu()", configuration_doc_norm)
        self.assertIn("build_config_section_change_preview()", configuration_doc_norm)
        self.assertIn("update_config_section()", configuration_doc_norm)
        self.assertIn("update_project_config_section()", configuration_doc_norm)
        self.assertIn("группы `audit`", configuration_doc_norm)
        self.assertIn(_normalize("внешнее второе мнение"), configuration_doc_norm)
        self.assertIn("memory.enabled: true", configuration_doc_norm)
        self.assertIn("ship:deployment", configuration_doc_norm)
        self.assertIn(_normalize("обязательное подтверждение человеком"), configuration_doc_norm)
        architecture = _normalize(_read("docs/architecture.md"))
        self.assertIn("build_config_section_summaries()", architecture)
        self.assertIn("build_config_section_menu()", architecture)
        self.assertIn("build_config_section_change_preview()", architecture)
        self.assertIn("update_config_section()", architecture)
        self.assertIn("update_project_config_section()", architecture)

    def test_operational_commands_use_canonical_continuity_helpers(self):
        next_command = _read("commands/next.md")
        progress_command = _read("commands/progress.md")
        sync_github_command = _read("commands/sync-github.md")
        pause_command = _read("commands/pause.md")
        resume_command = _read("commands/resume.md")
        verify_command = _read("commands/uat.md")
        update_command = _read("commands/update.md")

        self.assertIn('python3 .claude/alfred-continuity.py next "$PWD" --json', next_command)
        self.assertIn("source_label", next_command)
        self.assertIn("directive", next_command)
        self.assertIn('python3 .claude/alfred-continuity.py progress "$PWD"', progress_command)
        self.assertIn("focus", progress_command)
        self.assertIn("directive", progress_command)
        self.assertIn("используй её как итоговый ответ", progress_command)
        self.assertIn('python3 .claude/alfred-continuity.py resume "$PWD"', resume_command)
        self.assertIn("focus", sync_github_command)
        self.assertIn("directive", sync_github_command)
        self.assertIn("используй его как итоговый ответ и закончи", sync_github_command)
        self.assertIn("короче 12 строк", sync_github_command)
        self.assertIn("не добавляй блоки `Insight`", sync_github_command)
        self.assertIn("не продолжай исследование", sync_github_command)
        self.assertIn('python3 .claude/alfred-continuity.py pause "$PWD"', pause_command)
        self.assertIn("Сначала выполни детерминированный helper", pause_command)
        self.assertIn("Только если helper падает, переходи в ручной режим", pause_command)
        self.assertIn("Не оборачивай его во вторую сводку", pause_command)
        self.assertIn('python3 .claude/alfred-continuity.py resume "$PWD"', resume_command)
        self.assertIn("Сначала выполни детерминированный helper", resume_command)
        self.assertIn("Только если helper падает, переходи в ручной режим", resume_command)
        self.assertIn("Не оборачивай его во вторую сводку", resume_command)
        self.assertIn('python3 .claude/alfred-continuity.py verify "$PWD" --raw "$ARGUMENTS"', verify_command)
        self.assertIn("Если helper возвращает валидный ответ, используй его как итоговый ответ", verify_command)
        self.assertIn("НЕ добавляй второй слой сводки", verify_command)
        self.assertIn("## Каноничное завершение команды", update_command)
        self.assertIn("одно настоящее выбираемое меню", update_command)

    def test_long_flows_are_helper_first_for_headless_runs(self):
        activity_capture = _read("hooks/activity-capture.py")
        session_start = _read("hooks/session-start.sh")

        self.assertIn("start_flow_session", activity_capture)
        self.assertIn('"audit"', activity_capture)
        self.assertIn('"feature"', activity_capture)
        self.assertIn('"fix"', activity_capture)
        self.assertIn('"spike"', activity_capture)
        self.assertIn('"ship"', activity_capture)
        self.assertIn("/alfred-dev:feature", session_start)

        markers = {
            "audit": "AUDIT_HEADLESS_START",
            "feature": "FEATURE_HEADLESS_START",
            "fix": "FIX_HEADLESS_START",
            "spike": "SPIKE_HEADLESS_START",
            "ship": "SHIP_HEADLESS_START",
        }
        for command, marker in markers.items():
            command_doc = _read(f"commands/{command}.md")
            self.assertIn("consume-prefetch", command_doc)
            self.assertIn("start-flow", command_doc)
            self.assertIn("--command " + command, command_doc)
            self.assertIn("режиме headless", _normalize(command_doc))
            self.assertIn(marker, command_doc)
            self.assertIn("НЕ", command_doc)
            self.assertIn("не вызывай агентов", command_doc)

        audit_command = _read("commands/audit.md")
        self.assertIn("AUDIT_DOCKER_INSTALL_MENU_HEADLESS", audit_command)
        self.assertIn("AUDIT_DOCKER_START_MENU_HEADLESS", audit_command)
        self.assertIn("не выбирай сам", audit_command)

    def test_cto_is_helper_first_for_headless_runs(self):
        activity_capture = _read("hooks/activity-capture.py")
        session_start = _read("hooks/session-start.sh")
        cto_command = _read("commands/cto.md")

        self.assertIn('"cto"', activity_capture)
        self.assertIn("prepare_cto_review", activity_capture)
        self.assertIn("CTO", session_start)
        self.assertIn("consume-prefetch", cto_command)
        self.assertIn('python3 .claude/alfred-continuity.py cto "$PWD" --raw "$ARGUMENTS"', cto_command)
        self.assertIn("режиме headless", _normalize(cto_command))
        self.assertIn("CTO_HEADLESS_START", cto_command)
        self.assertIn("CTO_INVALID_SCOPE", cto_command)
        self.assertIn("НЕ запускай Agent", cto_command)
        self.assertIn("выполняй `greptile review`", cto_command)
        self.assertIn("НЕ представляй ревью как выполненное", cto_command)


class TestInstallSurfaceContracts(unittest.TestCase):
    def test_windows_installation_requires_and_patches_python(self):
        install_ps1 = _read("install.ps1")
        install_doc = _read("docs/installation.md")

        self.assertIn("Get-CompatiblePython", install_ps1)
        self.assertIn("Get-InstalledPluginRoot", install_ps1)
        self.assertIn("Get-CompatiblePython", install_ps1)
        self.assertIn('Write-Ok "hooks.json пропатчен', install_ps1)
        self.assertIn('Write-Ok ".mcp.json пропатчен', install_ps1)
        self.assertIn("Python 3.10+", install_doc)
        self.assertIn("hooks, core и MCP", install_doc)
        self.assertIn("обновляет `hooks.json` и `.mcp.json`", install_doc)

    def test_linux_installation_patches_hooks_and_mcp(self):
        install_sh = _read("install.sh")
        self.assertIn("Patch hooks and MCP", install_sh)
        self.assertIn("MCP_JSON", install_sh)
        self.assertIn("mcpServers", install_sh)
        self.assertIn('ok ".mcp.json пропатчен', install_sh)
        self.assertIn("resolve_installed_plugin_root", install_sh)
        self.assertIn("resolve_installed_plugin_root", install_sh)

    def test_quick_headless_closes_compactly_after_helper_first(self):
        quick = _read("commands/quick.md")

        self.assertIn("закрой этой сводкой и закончи", quick)
        self.assertIn("короче 20 строк", quick)
        self.assertIn("без блоков `Insight`", quick)

    def test_installation_docs_describe_claude_cli_based_flow(self):
        install_doc = _read("docs/installation.md")
        readme = _read("README.md")
        update_command = _read("commands/update.md")
        docs_readme = _read("docs/README.md")

        self.assertIn("claude plugin marketplace add grigoriev/alfred-dev --scope user", install_doc)
        self.assertIn("claude plugin install alfred-dev@alfred-dev --scope user", install_doc)
        self.assertIn("claude plugin uninstall alfred-dev@alfred-dev --scope local", install_doc)
        self.assertIn("claude plugin uninstall alfred-dev@alfred-dev --scope project", install_doc)
        self.assertIn('claude plugin marketplace add "$PWD" --scope user', install_doc)
        self.assertIn("~/.claude/skills/alfred/SKILL.md", install_doc)
        self.assertIn("~/.claude/commands/alfred.md", install_doc)
        self.assertIn("bash ./install.sh", install_doc)
        self.assertIn("bash ./install.sh", readme)
        self.assertIn("bash ./uninstall.sh", install_doc)
        self.assertIn("bash ./uninstall.sh", readme)
        self.assertIn("https://code.claude.com/docs/en/overview", readme)
        self.assertNotIn("https://docs.anthropic.com/en/docs/claude-code", readme)
        self.assertIn("/reload-plugins", readme)
        self.assertIn("/reload-plugins", install_doc)
        self.assertIn("/reload-plugins --force", install_doc)
        self.assertIn("/reload-plugins", update_command)
        self.assertIn("claude plugin details alfred-dev@alfred-dev", install_doc)
        self.assertIn("claude plugin validate . --strict", install_doc)
        self.assertIn("claude --debug", install_doc)
        self.assertIn("/plugin validate", install_doc)
        self.assertNotIn("Claude Code no ofrece diagnosticos", install_doc)
        self.assertNotIn("completamente silencioso", install_doc)
        self.assertIn("hooks.json", install_doc)
        self.assertIn(".mcp.json", install_doc)
        self.assertIn(_normalize("собственный GitHub-источник"), _normalize(install_doc))
        self.assertIn(_normalize("неофициальный"), _normalize(install_doc))
        self.assertIn(_normalize("глобальный источник GitHub"), _normalize(readme))
        self.assertIn(_normalize("одно меню выбора"), _normalize(install_doc))
        self.assertIn(_normalize("один `AskUserQuestion`"), _normalize(update_command))
        self.assertIn("claude plugin list --json", update_command)
        self.assertIn("нормализует их в `--scope user`", update_command)
        self.assertIn("не затрагивает `~/.claude/skills`", update_command)
        self.assertNotIn("alias personal global `/alfred`", update_command)
        self.assertNotIn("персональный глобальный алиас `/alfred`", update_command)
        self.assertIn("~/.claude/skills/alfred/SKILL.md", install_doc)
        self.assertIn("~/.claude/commands/alfred.md", update_command)
        self.assertIn("`--scope local` не поддерживается как путь установки", install_doc)
        self.assertIn("сначала удаляет любые следы `local` или `project`", install_doc)
        self.assertIn("Не используй `claude plugin update --scope local`", update_command)
        self.assertIn("plugin:alfred-dev:alfred-memory", install_doc)
        self.assertIn("Pending approval", install_doc)
        self.assertIn("docs/release.md", readme)
        self.assertIn("release.md", docs_readme)
        self.assertNotIn("release-audit-0.6.0.md", readme)
        self.assertNotIn("release-audit-0.6.0.md", docs_readme)
        self.assertIn("**Никогда не**", update_command)
        self.assertIn("0.10.0", update_command)
        self.assertIn('echo \'{"version":2,"plugins":{}}\'', install_doc)
        self.assertNotIn("git clone --depth 1", install_doc)
        self.assertNotIn("0.4.7", install_doc)
        self.assertNotIn("os.replace", install_doc)

    def test_uninstall_surface_is_also_cli_first(self):
        uninstall_sh = _read("uninstall.sh")
        uninstall_ps1 = _read("uninstall.ps1")
        install_doc = _read("docs/installation.md")
        readme = _read("README.md")

        self.assertIn('claude plugin uninstall "${PLUGIN_KEY}" --scope user', uninstall_sh)
        self.assertIn('claude plugin marketplace remove "${PLUGIN_NAME}" --scope user', uninstall_sh)
        self.assertIn("find_compatible_python", uninstall_sh)
        self.assertIn("remove_global_alfred_alias", uninstall_sh)
        self.assertIn("Глобальный alias /alfred удалён", uninstall_sh)
        self.assertIn("& claude plugin uninstall $PluginKey --scope user", uninstall_ps1)
        self.assertIn("& claude plugin marketplace remove $PluginName --scope user", uninstall_ps1)
        self.assertIn("Remove-GlobalAlfredAlias", uninstall_ps1)
        self.assertIn("Глобальный alias /alfred удалён", uninstall_ps1)
        self.assertIn(_normalize("нативную CLI Claude Code"), _normalize(install_doc))
        self.assertIn("claude plugin uninstall alfred-dev@alfred-dev --scope user", _normalize(install_doc))
        self.assertIn("claude plugin marketplace remove alfred-dev --scope user", _normalize(install_doc))
        self.assertIn(_normalize("нативный CLI Claude Code"), _normalize(readme))

class TestOptionalAgentsContracts(unittest.TestCase):
    def test_config_and_composition_include_nine_optional_agents(self):
        config = _read("commands/config.md")
        composition = _read("commands/_composition.md")
        configuration = _read("docs/configuration.md")

        self.assertIn("cto", _normalize(config))
        self.assertIn("build_optional_agent_group_menu", config)
        self.assertIn("Designer", composition)
        self.assertIn("build_optional_agent_group_menus()", configuration)

    def test_core_agent_docs_keep_product_architecture_orchestration_boundary_clear(self):
        po = _read("docs/agents/product-owner.md")
        architect = _read("docs/agents/architect.md")
        alfred = _read("docs/agents/alfred.md")
        agents_readme = _read("docs/agents/README.md")

        self.assertIn("Не переопределяет архитектуру, компоненты и выбор стека", po)
        self.assertIn("решает, **какую** проблему стоит решать и **зачем**", po)
        self.assertIn("Не переопределяет объём, истории и критерии приёмки, уже одобренные в PRD", architect)
        self.assertIn("решает, **как** устроено техническое решение", architect)
        self.assertIn("Не переопределяет функциональный объём и не заменяет одобренный PRD собственным мнением", alfred)
        self.assertIn("`product-owner` решает, **что** строить и **зачем**", alfred)
        self.assertIn("`architect` решает, **как** это реализуется технически", alfred)
        self.assertIn("`alfred`** решает, **когда** вмешивается каждый", agents_readme)


if __name__ == "__main__":
    unittest.main()
