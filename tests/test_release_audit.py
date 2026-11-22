#!/usr/bin/env python3
"""Tests del verificador de auditoria de release."""

import importlib.util
import os
from pathlib import Path
import re
import tempfile
import unittest


ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPT_PATH = os.path.join(ROOT, "scripts", "release_audit.py")
MANUAL_SMOKE_PATH = os.path.join(ROOT, "scripts", "manual_smoke.py")


def _load_release_audit_module():
    spec = importlib.util.spec_from_file_location("release_audit", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_manual_smoke_module():
    spec = importlib.util.spec_from_file_location("manual_smoke", MANUAL_SMOKE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestReleaseAuditScript(unittest.TestCase):
    def _skip_without_site(self):
        if not (Path(ROOT) / "site" / "package.json").is_file():
            self.skipTest("La landing vive en la rama Alfred-Astro")

    def test_default_release_audit_passes_local_contracts(self):
        """El modo por defecto no depende de red ni de la CLI de Claude."""
        release_audit = _load_release_audit_module()

        self.assertEqual(release_audit.main([]), 0)

    def test_version_scan_ignores_generated_manual_evidence(self):
        """Las evidencias manuales ignoradas no son superficie viva de release."""
        release_audit = _load_release_audit_module()
        json_artifact = Path(release_audit.ROOT) / "docs" / "manual-smoke-ignore-test.json"
        md_artifact = Path(release_audit.ROOT) / "docs" / "manual-smoke-ignore-test.md"
        json_artifact.write_text(
            f'{{"response_preview": "Claude menciono v{release_audit.OLD_VERSION}"}}\n',
            encoding="utf-8",
        )
        md_artifact.write_text(
            f"# Reporte\n\nClaude menciono v{release_audit.OLD_VERSION}\n",
            encoding="utf-8",
        )
        try:
            result = release_audit.check_versions()
        finally:
            json_artifact.unlink(missing_ok=True)
            md_artifact.unlink(missing_ok=True)

        self.assertIn(f"no leftovers of {release_audit.OLD_VERSION}", result)

    def test_inventory_keeps_composition_helper_internal(self):
        """_composicion se empaqueta como recurso, no como comando publico."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_inventory()

        self.assertIn("18 namespaced commands published", result)
        self.assertIn("commands/alfred.md published as contextual entry", result)
        self.assertIn("commands/_composicion.md internal", result)
        self.assertIn("human displayName aligned between manifest and marketplace", result)
        self.assertIn("10 agents in root agents/", result)
        self.assertIn("11 flat skills", result)
        self.assertTrue(
            any("canonical version only in plugin.json" in line for line in result),
            result,
        )
        self.assertIn("marketplace does not supplement components or enablement", result)
        self.assertIn("command/skill paths bounded to the plugin root", result)
        self.assertIn("manifest without unaudited components", result)

    def test_inventory_rejects_manifest_components_without_release_gate(self):
        """Los componentes estructurales deben tener gate antes de declararse."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/plugin.json":
                data = dict(data)
                data["agents"] = ["./agents/alfred.md"]
                data["mcpServers"] = {"alfred-memory": {"command": "python3"}}
                data["lspServers"] = {
                    "python": {
                        "command": "pyright-langserver",
                        "extensionToLanguage": {".py": "python"},
                    }
                }
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        message = str(context.exception)
        self.assertIn("Plugin components without explicit audit", message)
        self.assertIn("agents", message)
        self.assertIn("mcpServers", message)
        self.assertIn("lspServers", message)
        self.assertIn("LSP gate", message)

    def test_inventory_rejects_experimental_components_without_release_gate(self):
        """Themes/monitors experimentales no deben colarse sin pruebas dedicadas."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/plugin.json":
                data = dict(data)
                data["experimental"] = {
                    "monitors": "./monitors/monitors.json",
                    "themes": "./themes/",
                }
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        message = str(context.exception)
        self.assertIn("experimental.monitors", message)
        self.assertIn("experimental.themes", message)

    def test_inventory_rejects_marketplace_component_supplements(self):
        """El marketplace de Alfred no debe alterar el inventario probado en plugin.json."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/marketplace.json":
                data = dict(data)
                plugin_entry = dict(data["plugins"][0])
                plugin_entry["skills"] = ["./skills/"]
                plugin_entry["mcpServers"] = "./mcp-extra.json"
                data["plugins"] = [plugin_entry]
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        message = str(context.exception)
        self.assertIn("Alfred Dev marketplace out of sync", message)
        self.assertIn("skills", message)
        self.assertIn("mcpServers", message)

    def test_inventory_rejects_marketplace_strict_false_or_enablement_override(self):
        """strict=false/defaultEnabled cambiarian la autoridad del plugin auditado."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/marketplace.json":
                data = dict(data)
                plugin_entry = dict(data["plugins"][0])
                plugin_entry["strict"] = False
                plugin_entry["defaultEnabled"] = False
                data["plugins"] = [plugin_entry]
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        message = str(context.exception)
        self.assertIn("strict=false", message)
        self.assertIn("defaultEnabled", message)

    def test_inventory_rejects_marketplace_duplicate_plugin_entries(self):
        """La auditoria 0.6.0 asume una sola entrada alfred-dev en marketplace local."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/marketplace.json":
                data = dict(data)
                data["plugins"] = [dict(data["plugins"][0]), dict(data["plugins"][0])]
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        self.assertIn("exactly one entry", str(context.exception))

    def test_inventory_rejects_generic_skills_manifest_for_root_marketplace(self):
        """El marketplace root debe publicar los dominios de skills explícitos."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/plugin.json":
                data = dict(data)
                data["skills"] = ["./skills/"]
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        self.assertIn("plugin.json must not list skills", str(context.exception))

    def test_inventory_rejects_manifest_component_path_without_dot_slash(self):
        """Claude resuelve paths de componentes relativos al root; usamos ./ explícito."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/plugin.json":
                data = dict(data)
                data["commands"] = list(data["commands"])
                data["commands"][0] = "commands/alfred.md"
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        self.assertIn("Incompatible manifest component paths", str(context.exception))
        self.assertIn("must start with ./", str(context.exception))

    def test_inventory_rejects_manifest_component_absolute_path(self):
        """El paquete instalado no puede depender de rutas absolutas del dev host."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/plugin.json":
                data = dict(data)
                data["commands"] = list(data["commands"])
                data["commands"][0] = "/tmp/alfred.md"
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        self.assertIn("must not be absolute", str(context.exception))

    def test_inventory_rejects_manifest_component_traversal(self):
        """Los componentes declarados no deben apuntar fuera del plugin con ..."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/plugin.json":
                data = dict(data)
                data["commands"] = list(data["commands"])
                data["commands"][0] = "./../shared-skills/"
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        message = str(context.exception)
        self.assertIn("must not escape the plugin", message)
        self.assertIn("resolves outside the plugin root", message)

    def test_inventory_rejects_duplicate_manifest_component_paths(self):
        """Las rutas duplicadas inflan el inventario y hacen ambigua la auditoria."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/plugin.json":
                data = dict(data)
                data["commands"] = list(data["commands"])
                data["commands"].append(data["commands"][0])
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        self.assertIn("duplicates a manifest path", str(context.exception))

    def test_inventory_rejects_marketplace_display_name_drift(self):
        """La UI humana debe mantener el mismo displayName en manifest y marketplace."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/marketplace.json":
                data = dict(data)
                data["plugins"] = [dict(data["plugins"][0], displayName="Alfred")]
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        self.assertIn("human displayName", str(context.exception))

    def test_inventory_rejects_marketplace_version_duplication(self):
        """La version canonica vive en plugin.json, no duplicada en marketplace."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/marketplace.json":
                data = dict(data)
                data["plugins"] = [dict(data["plugins"][0], version="0.6.0")]
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        self.assertIn("must not duplicate version", str(context.exception))

    def test_inventory_rejects_marketplace_source_escaping_root(self):
        """El source relativo del marketplace no debe apuntar fuera del root."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == ".claude-plugin/marketplace.json":
                data = dict(data)
                data["plugins"] = [dict(data["plugins"][0], source="./../alfred-dev")]
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._json = original_json

        self.assertIn("must not escape the root", str(context.exception))

    def test_inventory_rejects_unsupported_skill_frontmatter_field(self):
        """Los SKILL.md no deben usar campos de frontmatter que Claude Code no documenta."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "skills/pr-workflow/SKILL.md":
                return text.replace(
                    "description:",
                    "unsupported-field: true\ndescription:",
                    1,
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._read = original_read

        self.assertIn("Incompatible skill frontmatter", str(context.exception))
        self.assertIn("unsupported-field", str(context.exception))

    def test_inventory_rejects_skill_name_different_from_directory(self):
        """El name del skill debe quedar estable y coincidir con la ruta invocable."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "skills/pr-workflow/SKILL.md":
                return text.replace("name: pr-workflow", "name: refactor-code", 1)
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._read = original_read

        self.assertIn("Incompatible skill frontmatter", str(context.exception))
        self.assertIn("directory", str(context.exception))
        self.assertIn("refactor-code", str(context.exception))

    def test_inventory_rejects_invalid_skill_boolean_value(self):
        """Los booleanos de SKILL.md deben usar valores que Claude entienda."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "skills/pr-workflow/SKILL.md":
                return text.replace(
                    "disable-model-invocation: true",
                    "disable-model-invocation: maybe",
                    1,
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._read = original_read

        self.assertIn("Incompatible skill frontmatter", str(context.exception))
        self.assertIn("disable-model-invocation", str(context.exception))
        self.assertIn("maybe", str(context.exception))

    def test_inventory_rejects_skill_listing_text_over_claude_limit(self):
        """Claude trunca description + when_to_use por encima de 1536 chars."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read
        long_description = "a" * (release_audit.SKILL_LISTING_TEXT_LIMIT + 1)

        def fake_read(path):
            text = original_read(path)
            if path == "skills/pr-workflow/SKILL.md":
                return re.sub(
                    r"(?m)^description: .+$",
                    f"description: {long_description}",
                    text,
                    count=1,
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._read = original_read

        self.assertIn("Incompatible skill frontmatter", str(context.exception))
        self.assertIn("skill listing limit", str(context.exception))
        self.assertIn(str(release_audit.SKILL_LISTING_TEXT_LIMIT + 1), str(context.exception))

    def test_inventory_rejects_invalid_skill_effort_value(self):
        """Los effort de skills deben seguir el set documentado por Claude Code."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "skills/pr-workflow/SKILL.md":
                return text.replace("description:", "effort: enormous\ndescription:", 1)
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._read = original_read

        self.assertIn("Incompatible skill frontmatter", str(context.exception))
        self.assertIn("effort not supported", str(context.exception))
        self.assertIn("enormous", str(context.exception))

    def test_inventory_rejects_unknown_skill_allowed_tool_name(self):
        """Los permisos de SKILL.md deben nombrar herramientas reales."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "skills/pr-workflow/SKILL.md":
                return text.replace(
                    "description:",
                    "allowed-tools: Browser\ndescription:",
                    1,
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._read = original_read

        self.assertIn("Incompatible skill frontmatter", str(context.exception))
        self.assertIn("allowed-tools", str(context.exception))
        self.assertIn("Browser", str(context.exception))

    def test_inventory_rejects_unsupported_agent_model(self):
        """Los agentes no deben usar valores de model fuera del contrato actual."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "agents/alfred.md":
                return text.replace("model: inherit", "model: llama", 1)
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._read = original_read

        self.assertIn("model not supported", str(context.exception))
        self.assertIn("llama", str(context.exception))

    def test_inventory_rejects_supported_agent_model_when_release_policy_drifts(self):
        """Un alias válido de Claude también debe actualizar la política/documentación."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "agents/qa-engineer.md":
                return text.replace("model: inherit", "model: haiku", 1)
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._read = original_read

        self.assertIn("agent model distribution", str(context.exception))
        self.assertIn("haiku", str(context.exception))

    def test_inventory_rejects_unsupported_agent_color(self):
        """Los colores de subagentes deben seguir el set documentado por Claude Code."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "agents/alfred.md":
                return text.replace("color: blue", "color: magenta", 1)
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._read = original_read

        self.assertIn("subagent color not supported", str(context.exception))
        self.assertIn("magenta", str(context.exception))

    def test_inventory_rejects_unavailable_subagent_tool(self):
        """Los agentes de plugin no deben listar herramientas que Claude no da a subagentes."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "agents/alfred.md":
                return text.replace(
                    "tools: Glob,Grep,Read,Write,Edit,Bash,Agent,WebSearch",
                    "tools: Glob,Grep,Read,Write,Edit,Bash,Agent,WebSearch,AskUserQuestion",
                    1,
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._read = original_read

        self.assertIn("tools not available in subagents", str(context.exception))
        self.assertIn("AskUserQuestion", str(context.exception))

    def test_inventory_rejects_unknown_agent_tool_name(self):
        """Los tools de agentes deben usar nombres reales de Claude Code o patrones MCP."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "agents/alfred.md":
                return text.replace(
                    "tools: Glob,Grep,Read,Write,Edit,Bash,Agent,WebSearch",
                    "tools: Glob,Grep,Read,Write,Edit,Bash,Agent,WebSearch,Browser",
                    1,
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_inventory()
        finally:
            release_audit._read = original_read

        self.assertIn("tools unknown", str(context.exception))
        self.assertIn("Browser", str(context.exception))

    def test_continuity_smoke_covers_human_operational_helpers(self):
        """El smoke operativo recorre helpers reales en un fixture temporal."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_continuity_smoke()

        self.assertIn("next/map-codebase/discuss/quick", result)
        self.assertIn("blocked/in-progress/validate/search/verify", result)
        self.assertIn(
            "write-handoff/allow-stop-once/consume-prefetch/normalize-kanban/memory-ui/sync-github-fail-closed",
            result,
        )

    def test_mcp_tools_smoke_invokes_all_memory_tools(self):
        """El smoke MCP no se limita a tools/list: invoca las 15 tools."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_mcp_tools_smoke()

        self.assertIn("15 tools listed", result)
        self.assertIn("15 tools invoked with real data", result)
        self.assertIn("defensive MCP limits in schemas and handlers", result)
        self.assertIn("memory_log_event truncates huge MCP payload/content", result)
        self.assertIn("MCP paths bounded to the project", result)

    def test_external_contracts_cover_human_permission_boundaries(self):
        """Docker, GitHub, CTO y deploy deben tener límites humanos claros."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_external_contracts()

        self.assertIn("Docker/SonarQube asks for permission and documents skips", result)
        self.assertIn("CTO confirms cost and does not modify files", result)
        self.assertIn("ship keeps deploy behind a human gate", result)

    def test_command_catalog_is_exhaustive_and_deduplicated(self):
        """La ayuda y arquitectura deben reflejar todos los comandos publicados."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_command_catalog()

        self.assertIn("18 namespaced commands aligned between plugin.json and architecture", result)
        self.assertIn("commands/alfred.md published as contextual entry", result)
        self.assertIn("command frontmatter compatible with current Claude Code", result)
        self.assertIn("command model validated against current Claude Code", result)

    def test_command_catalog_rejects_unsupported_frontmatter_field(self):
        """Los slash commands no deben usar campos de frontmatter que Claude ignore."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "commands/quick.md":
                return text.replace("description:", "unknown-field: true\ndescription:", 1)
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_command_catalog()
        finally:
            release_audit._read = original_read

        self.assertIn("unsupported frontmatter fields", str(context.exception))
        self.assertIn("unknown-field", str(context.exception))

    def test_command_catalog_rejects_skill_only_frontmatter_field(self):
        """Los comandos no deben aceptar campos que solo pertenecen a SKILL.md."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "commands/quick.md":
                return text.replace(
                    "description:",
                    "when_to_use: solo para skills\ndescription:",
                    1,
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_command_catalog()
        finally:
            release_audit._read = original_read

        self.assertIn("unsupported frontmatter fields", str(context.exception))
        self.assertIn("when_to_use", str(context.exception))

    def test_command_catalog_rejects_unknown_allowed_tool(self):
        """Los permisos de slash commands deben nombrar herramientas reales."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "commands/quick.md":
                return text.replace(
                    "argument-hint:",
                    "allowed-tools: Browser\nargument-hint:",
                    1,
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_command_catalog()
        finally:
            release_audit._read = original_read

        self.assertIn("allowed-tools", str(context.exception))
        self.assertIn("Browser", str(context.exception))

    def test_command_catalog_rejects_unknown_allowed_tool_in_yaml_list(self):
        """Las listas YAML de tools en commands se validan igual que los valores inline."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "commands/quick.md":
                return text.replace(
                    "argument-hint:",
                    "allowed-tools:\n  - Browser\nargument-hint:",
                    1,
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_command_catalog()
        finally:
            release_audit._read = original_read

        self.assertIn("allowed-tools", str(context.exception))
        self.assertIn("Browser", str(context.exception))

    def test_command_catalog_rejects_unsupported_command_model(self):
        """El model opcional de commands debe usar alias/ID aceptado por Claude Code."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "commands/quick.md":
                return text.replace(
                    "description:",
                    "model: llama\ndescription:",
                    1,
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_command_catalog()
        finally:
            release_audit._read = original_read

        self.assertIn("command model not supported", str(context.exception))
        self.assertIn("llama", str(context.exception))

    def test_command_execution_contracts_cover_all_public_commands(self):
        """Los comandos publicados deben conservar argumentos, helpers y cierres."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_command_execution_contracts()

        self.assertIn("18 namespaced commands keep arguments, prefix and current naming", result)
        self.assertIn("18 helper-first wrappers covered", result)
        self.assertIn("6 main flows with canonical closing", result)
        self.assertIn("_composicion loads from the plugin install", result)
        self.assertIn("free gates without unconditional approval", result)
        self.assertIn("autopilot via config/state without phantom public flag", result)

    def test_command_execution_contracts_reject_unconditional_free_gates(self):
        """Las gates libres no deben declarar aprobacion sin evidencia."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "commands/ship.md":
                return original_read(path).replace(
                    "Может закрываться без одобрения человека, но не объявляй фазу пройденной, если не хватает артефактов.",
                    "Всегда одобряется.",
                    1,
                )
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_command_execution_contracts()
        finally:
            release_audit._read = original_read

        self.assertIn("ship", str(context.exception))
        self.assertIn("unconditional approval", str(context.exception))

    def test_public_claims_do_not_drift_from_current_inventory(self):
        """README, web, arquitectura y agentes no deben prometer contadores viejos."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_public_claims()

        self.assertIn("public inventory 10/11/18 verified", result)
        self.assertIn("README, architecture, help and agents without old counters", result)
        self.assertIn("human displayName reflected in README and changelog", result)
        self.assertIn("sensitive skills keep explicit manual activation", result)
        self.assertIn("runtime prompts without legacy /alfred", result)
        self.assertIn("CTO does not pin an obsolete Codex CLI model", result)

    def test_public_claims_reject_absolute_gate_language(self):
        """La superficie publica no debe prometer gates absolutas sin matiz."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "README.md":
                return original_read(path) + "\nNo hay excepciones, no hay modo de saltárselas\n"
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_public_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("README.md", str(context.exception))
        self.assertIn("No hay excepciones", str(context.exception))

    def test_public_claims_reject_russian_absolute_gate_language(self):
        """El README ruso tampoco debe prometer gates absolutas sin matiz."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "README.md":
                return original_read(path) + "\nQuality gates непреодолимы. Исключений нет.\n"
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_public_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("README.md", str(context.exception))
        self.assertIn("Исключений нет", str(context.exception))

    def test_public_claims_reject_llm_determinism_overclaim(self):
        """La docs de agentes no debe prometer determinismo de modelo."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "docs/agents/README.md":
                return (
                    original_read(path)
                    + "\nEl resultado es previsible y reproducible: produce resultados consistentes porque no arrastra contexto.\n"
                )
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_public_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("docs/agents/README.md", str(context.exception))
        self.assertIn("previsible y reproducible", str(context.exception))

    def test_public_claims_reject_absolute_quality_overclaims(self):
        """TDD, seguridad, UX e i18n deben prometer evidencia, no garantias totales."""
        cases = [
            (
                "docs/flows.md",
                "garantiza que cada linea de código tiene al menos un test",
                "cada linea",
            ),
            (
                "docs/skills.md",
                "garantizar que el software sea usable por todas las personas",
                "usable por todas",
            ),
            (
                "docs/agents/security-officer.md",
                "garantizar que el software cumple con los estandares de seguridad",
                "estandares de seguridad",
            ),
            (
                "agents/security-officer.md",
                "garantiza que nada con vulnerabilidades conocidas llega a los usuarios",
                "vulnerabilidades conocidas",
            ),
            (
                "agents/alfred.md",
                "Las HARD-GATES son condiciones que NUNCA se pueden saltar",
                "NUNCA se pueden saltar",
            ),
            (
                "agents/security-officer.md",
                "bloqueantes absolutos. Sin excepciones",
                "Sin excepciones",
            ),
            (
                "hooks/session-start.sh",
                "Las quality gates son infranqueables",
                "infranqueables",
            ),
            (
                "agents/alfred.md",
                "HARD-GATES это условия, которые НИКОГДА нельзя пропускать",
                "НИКОГДА нельзя пропускать",
            ),
            (
                "agents/security-officer.md",
                "абсолютные блокеры. Без исключений",
                "Без исключений",
            ),
            (
                "hooks/session-start.sh",
                "Quality gates непреодолимы",
                "непреодолим",
            ),
        ]

        for path, stale_claim, expected_fragment in cases:
            with self.subTest(path=path):
                release_audit = _load_release_audit_module()
                original_read = release_audit._read

                def fake_read(read_path):
                    if read_path == path:
                        return original_read(read_path) + f"\n{stale_claim}\n"
                    return original_read(read_path)

                release_audit._read = fake_read
                try:
                    with self.assertRaises(release_audit.AuditError) as context:
                        release_audit.check_public_claims()
                finally:
                    release_audit._read = original_read

                self.assertIn(path, str(context.exception))
                self.assertIn(expected_fragment, str(context.exception))

    def test_public_claims_reject_agent_manifest_drift(self):
        """Los docs no pueden volver a decir que plugin.json declara agents."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "docs/agents/README.md":
                return (
                    "Los agentes tambien aparecen en `plugin.json` para que "
                    "la superficie publicada sea completa."
                )
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_public_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("docs/agents/README.md", str(context.exception))
        self.assertIn("plugin.json", str(context.exception))

    def test_public_claims_reject_stale_core_counter_on_landing(self):
        """La landing no debe volver al contador congelado de seis modulos core."""
        self._skip_without_site()
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "site/src/i18n/data.en.ts":
                return original_read(path) + "\nconst stale = '6 core modules';\n"
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_public_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("site/src/i18n/data.en.ts", str(context.exception))
        self.assertIn("6 core modules", str(context.exception))

    def test_public_claims_reject_sonarqube_without_confirmation_claim(self):
        """SonarQube/Docker no debe prometer ejecucion sin confirmacion humana."""
        self._skip_without_site()
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "site/src/i18n/data.en.ts":
                return (
                    original_read(path)
                    + "\nconst stale = 'start SonarQube without asking the user for confirmation';\n"
                )
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_public_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("site/src/i18n/data.en.ts", str(context.exception))
        self.assertIn("without asking the user for confirmation", str(context.exception))

    def test_public_claims_reject_sonarqube_end_to_end_docker_claim(self):
        """La landing no debe afirmar SonarQube Docker real sin evidencia externa."""
        self._skip_without_site()
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "site/src/i18n/data.en.ts":
                return original_read(path) + "\nconst stale = 'Verified end-to-end with Docker';\n"
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_public_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("site/src/i18n/data.en.ts", str(context.exception))
        self.assertIn("Verified end-to-end with Docker", str(context.exception))

    def test_public_claims_reject_changelog_docker_without_prompt_claim(self):
        """El changelog publico no debe reintroducir Docker sin confirmacion."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "CHANGELOG.md":
                return original_read(path) + "\nSonarQube sin prompt de confirmación al usuario\n"
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_public_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("CHANGELOG.md", str(context.exception))
        self.assertIn("sin prompt de confirmación al usuario", str(context.exception))

    def test_public_claims_reject_stale_manual_matrix_option_count(self):
        """El changelog no debe quedarse con el conteo antiguo de opciones manuales."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "CHANGELOG.md":
                return original_read(path).replace(
                    "42 публичные опции и 4 runtime-контракта `/update`",
                    "22 opciones/variantes documentadas",
                    1,
                )
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_public_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("CHANGELOG.md", str(context.exception))
        self.assertIn("42 публичные опции", str(context.exception))
        self.assertIn("4 runtime-контракта", str(context.exception))

    def test_public_claims_reject_keyword_based_dynamic_composition(self):
        """La composición dinámica publica no debe prometer matching por keywords."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "README.md":
                return original_read(path) + "\nmatching con keywords contextuales\n"
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_public_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("README.md", str(context.exception))
        self.assertIn("keywords contextuales", str(context.exception))

    def test_public_claims_reject_manual_only_skill_drift(self):
        """Los skills delicados no deben volver a activacion automatica."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "skills/sonarqube/SKILL.md":
                return text.replace("disable-model-invocation: true\n", "")
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_public_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("skills/sonarqube/SKILL.md", str(context.exception))
        self.assertIn("explicit manual activation", str(context.exception))

    def test_config_contracts_cover_all_public_sections(self):
        """El comando config debe exponer las 7 secciones reales del runtime."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_config_contracts()

        self.assertIn("7 config sections aligned with runtime", result)
        self.assertIn("automatic detection covers promised stacks", result)
        self.assertIn("main config menu exposes exit and canonical sections", result)
        self.assertIn("config docs and command cover canonical helpers", result)
        self.assertIn("AskUserQuestion config/optional uses current questions[] and multiSelect", result)

    def test_config_contracts_reject_obsolete_ask_user_question_examples(self):
        """Los ejemplos de AskUserQuestion deben usar el schema actual."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "commands/ajustes.md":
                return original_read(path).replace(
                    "AskUserQuestion({\n"
                    "  questions: [\n"
                    "    {\n"
                    "      question: \"Хочешь активировать CTO как внешнее второе мнение?\",\n"
                    "      header: \"Auditoria\",\n"
                    "      multiSelect: false,\n"
                    "      options: [\n"
                    "        { label: \"Seguir sin activar más\", description: \"Перейти к следующей группе\" },\n"
                    "        { label: \"CTO\", description: \"<контекстная причина>\" }\n"
                    "      ]\n"
                    "    }\n"
                    "  ]\n"
                    "})",
                    "AskUserQuestion({\n"
                    "  question: \"Хочешь активировать CTO как внешнее второе мнение?\",\n"
                    "  header: \"Auditoria\",\n"
                    "  options: [\n"
                    "    { label: \"Seguir sin activar más\", description: \"Перейти к следующей группе\" }\n"
                    "  ]\n"
                    "})",
                )
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_config_contracts()
        finally:
            release_audit._read = original_read

        self.assertIn("Obsolete AskUserQuestion", str(context.exception))
        self.assertIn("questions: [", str(context.exception))
        self.assertIn("multiSelect: false", str(context.exception))

    def test_flow_gate_claims_cover_designer_and_autopilot_boundaries(self):
        """Los claims de Designer, gates y autopilot deben ejercitar orquestador real."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_flow_gate_claims()

        self.assertIn("feature keeps 7 phases with conditional Designer", result)
        self.assertIn("free gates documented as evidence without human approval", result)
        self.assertIn("automatic gates block red tests and failed security", result)
        self.assertIn("autopilot does not skip automatic gates or human deploy", result)

    def test_flow_gate_claims_reject_lax_free_gate_docs(self):
        """Las docs no deben volver a convertir gate libre en aprobacion ceremonial."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "docs/flows.md":
                return text.replace(
                    "Проходится, когда результат ответственного агента положительный и есть прямое подтверждение ожидаемого артефакта или чек-листа.",
                    "Проходится всегда, когда результат положительный.",
                    1,
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_flow_gate_claims()
        finally:
            release_audit._read = original_read

        self.assertIn("docs/flows.md", str(context.exception))
        self.assertIn("free gate", str(context.exception))

    def test_hook_contracts_keep_exec_form_and_fail_closed_guards(self):
        """Los hooks deben usar exec form y conservar bloqueos exit 2."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_hook_contracts()

        self.assertIn("10 visible hooks registered", result)
        self.assertIn("declared hook scripts exist and cover the 9 visible ones", result)
        self.assertIn("exec form without shell wrappers or unquoted paths", result)
        self.assertIn("blocking hooks keep exit 2", result)
        self.assertIn("hooks with exit 2 do not emit JSON that Claude Code ignores", result)
        self.assertIn("events SessionStart, SessionEnd, UserPromptSubmit, PreToolUse and PostToolUse", result)
        self.assertIn("events without matcher do not declare an ignored matcher", result)
        self.assertIn("hooks do not use if outside tool events", result)
        self.assertIn("synchronous hooks declare integer timeout <= 10 seconds", result)
        self.assertIn("hook docs use current decision/hookSpecificOutput", result)

    def test_hook_contracts_reject_if_on_non_tool_event(self):
        """Claude solo evalúa if en eventos de herramienta."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == "hooks/hooks.json":
                data = dict(data)
                hooks = {
                    event: [
                        {
                            **group,
                            "hooks": [dict(hook) for hook in group.get("hooks", [])],
                        }
                        for group in groups
                    ]
                    for event, groups in data["hooks"].items()
                }
                hooks["UserPromptSubmit"][0]["hooks"][0]["if"] = "Bash(*)"
                data["hooks"] = hooks
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_hook_contracts()
        finally:
            release_audit._json = original_json

        self.assertIn("declares an if that Claude Code does not evaluate", str(context.exception))
        self.assertIn("UserPromptSubmit", str(context.exception))

    def test_hook_contracts_reject_matcher_on_event_that_ignores_it(self):
        """Claude ignora matcher en algunos eventos; no debemos dar falsa precision."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == "hooks/hooks.json":
                data = dict(data)
                hooks = {
                    event: [dict(group) for group in groups]
                    for event, groups in data["hooks"].items()
                }
                hooks["UserPromptSubmit"][0]["matcher"] = "Bash"
                data["hooks"] = hooks
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_hook_contracts()
        finally:
            release_audit._json = original_json

        self.assertIn("matcher that Claude Code ignores", str(context.exception))
        self.assertIn("UserPromptSubmit", str(context.exception))

    def test_hook_contracts_reject_user_prompt_expansion_event(self):
        """0.7.0 no publica UserPromptExpansion; un evento extra desalinearia el inventario."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == "hooks/hooks.json":
                data = dict(data)
                hooks = dict(data["hooks"])
                hooks["UserPromptExpansion"] = hooks["UserPromptSubmit"]
                data["hooks"] = hooks
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_hook_contracts()
        finally:
            release_audit._json = original_json

        self.assertIn("Hook events out of sync", str(context.exception))
        self.assertIn("UserPromptExpansion", str(context.exception))

    def test_hook_contracts_require_session_start(self):
        """SessionStart sigue siendo evento obligatorio del plugin."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == "hooks/hooks.json":
                data = dict(data)
                hooks = dict(data["hooks"])
                hooks.pop("SessionStart", None)
                data["hooks"] = hooks
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_hook_contracts()
        finally:
            release_audit._json = original_json

        self.assertIn("Hook events out of sync", str(context.exception))
        self.assertIn("SessionStart", str(context.exception))

    def test_hook_contracts_reject_slow_sync_hooks(self):
        """Los hooks síncronos deben tener timeout explicito y conservador."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == "hooks/hooks.json":
                data = dict(data)
                hooks = {
                    event: [
                        {
                            **group,
                            "hooks": [dict(hook) for hook in group.get("hooks", [])],
                        }
                        for group in groups
                    ]
                    for event, groups in data["hooks"].items()
                }
                hooks["UserPromptSubmit"][0]["hooks"][0]["timeout"] = 15
                data["hooks"] = hooks
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_hook_contracts()
        finally:
            release_audit._json = original_json

        self.assertIn("synchronous hook exceeds timeout 10s", str(context.exception))
        self.assertIn("activity-capture.py", str(context.exception))

    def test_hook_contracts_reject_sync_hooks_without_timeout(self):
        """Un hook síncrono sin timeout puede dejar la sesión bloqueada."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == "hooks/hooks.json":
                data = dict(data)
                hooks = {
                    event: [
                        {
                            **group,
                            "hooks": [dict(hook) for hook in group.get("hooks", [])],
                        }
                        for group in groups
                    ]
                    for event, groups in data["hooks"].items()
                }
                hooks["UserPromptSubmit"][0]["hooks"][0].pop("timeout", None)
                data["hooks"] = hooks
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_hook_contracts()
        finally:
            release_audit._json = original_json

        self.assertIn("synchronous hook without integer timeout", str(context.exception))
        self.assertIn("activity-capture.py", str(context.exception))

    def test_hook_contracts_reject_boolean_sync_timeout(self):
        """Un timeout booleano no es un entero valido para hooks."""
        release_audit = _load_release_audit_module()
        original_json = release_audit._json

        def fake_json(path):
            data = original_json(path)
            if path == "hooks/hooks.json":
                data = dict(data)
                hooks = {
                    event: [
                        {
                            **group,
                            "hooks": [dict(hook) for hook in group.get("hooks", [])],
                        }
                        for group in groups
                    ]
                    for event, groups in data["hooks"].items()
                }
                hooks["UserPromptSubmit"][0]["hooks"][0]["timeout"] = True
                data["hooks"] = hooks
            return data

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_hook_contracts()
        finally:
            release_audit._json = original_json

        self.assertIn("synchronous hook without integer timeout", str(context.exception))
        self.assertIn("activity-capture.py", str(context.exception))

    def test_hook_contracts_reject_spanish_decision_key_in_docs(self):
        """La doc de hooks no debe enseñar claves JSON que Claude Code no entiende."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "docs/hooks.md":
                return text + '\nEjemplo obsoleto: {"decisión": "block"}\n'
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_hook_contracts()
        finally:
            release_audit._read = original_read

        self.assertIn("decisión", str(context.exception))

    def test_hook_contracts_reject_nested_event_specific_hook_output_docs(self):
        """La doc no debe enseñar hookSpecificOutput.<Evento>.additionalContext."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "docs/hooks.md":
                return text + "\nEjemplo viejo: hookSpecificOutput.PreCompact.additionalContext\n"
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_hook_contracts()
        finally:
            release_audit._read = original_read

        message = str(context.exception)
        self.assertIn("hookSpecificOutput nested", message)
        self.assertIn("PreCompact", message)

    def test_packaging_contracts_exclude_local_artifacts(self):
        """El paquete seco no debe incluir caches, sesiones locales ni tests."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_packaging_contracts()

        self.assertIn(f"npm pack dry-run {release_audit.VERSION} valid", result)
        self.assertIn("package without local caches or tests", result)
        self.assertIn("package without .claude/.crupier or manual evidence", result)
        self.assertIn("package without publishable symlinks outside the plugin", result)
        self.assertIn("package contains 18 namespaced commands, 10 agents and 11 skills", result)
        self.assertIn("package contains 8 artifact templates", result)
        self.assertIn("package contains the Designer visual runtime", result)

    def test_packaging_contracts_reject_publishable_symlink_problem(self):
        """El gate de empaquetado debe fallar si el escaneo de symlinks detecta problemas."""
        release_audit = _load_release_audit_module()
        original_symlink_scan = release_audit._publishable_symlink_problems

        release_audit._publishable_symlink_problems = lambda: [
            "templates/external.md es un symlink fuera del plugin: '../external.md'"
        ]
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_packaging_contracts()
        finally:
            release_audit._publishable_symlink_problems = original_symlink_scan

        self.assertIn("Publishable symlinks incompatible", str(context.exception))
        self.assertIn("templates/external.md", str(context.exception))

    def test_publishable_symlink_scan_rejects_external_target(self):
        """Claude salta symlinks fuera del plugin al copiar a cache; no pueden ser superficie."""
        release_audit = _load_release_audit_module()
        original_root = release_audit.ROOT
        original_roots = release_audit.PUBLISHABLE_SYMLINK_ROOTS

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "plugin"
            external = Path(tmpdir) / "external.md"
            (workspace / "templates").mkdir(parents=True)
            external.write_text("outside\n", encoding="utf-8")
            os.symlink(external, workspace / "templates" / "external.md")
            release_audit.ROOT = workspace
            release_audit.PUBLISHABLE_SYMLINK_ROOTS = ("templates",)
            try:
                problems = release_audit._publishable_symlink_problems()
            finally:
                release_audit.ROOT = original_root
                release_audit.PUBLISHABLE_SYMLINK_ROOTS = original_roots

        self.assertTrue(any("symlink outside the plugin" in problem for problem in problems), problems)

    def test_publishable_symlink_scan_rejects_broken_link(self):
        """Un symlink roto puede pasar desapercibido hasta instalación; se bloquea antes."""
        release_audit = _load_release_audit_module()
        original_root = release_audit.ROOT
        original_roots = release_audit.PUBLISHABLE_SYMLINK_ROOTS

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir) / "plugin"
            (workspace / "templates").mkdir(parents=True)
            os.symlink(workspace / "templates" / "missing.md", workspace / "templates" / "broken.md")
            release_audit.ROOT = workspace
            release_audit.PUBLISHABLE_SYMLINK_ROOTS = ("templates",)
            try:
                problems = release_audit._publishable_symlink_problems()
            finally:
                release_audit.ROOT = original_root
                release_audit.PUBLISHABLE_SYMLINK_ROOTS = original_roots

        self.assertTrue(any("broken symlink" in problem for problem in problems), problems)

    def test_packaging_contracts_reject_crupier_artifacts(self):
        """El paquete seco no debe arrastrar auditorias locales de .crupier."""
        release_audit = _load_release_audit_module()
        original_pack = release_audit._npm_pack_dry_run_package
        base_package = original_pack()
        leaked = dict(base_package)
        leaked["files"] = list(base_package["files"]) + [
            {"path": ".crupier/audits/project_doctor.json", "size": 2}
        ]

        release_audit._npm_pack_dry_run_package = lambda: leaked
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_packaging_contracts()
        finally:
            release_audit._npm_pack_dry_run_package = original_pack

        self.assertIn(".crupier/audits/project_doctor.json", str(context.exception))

    def test_packaging_contracts_reject_missing_template(self):
        """Las plantillas citadas por agentes y skills son superficie publicable."""
        release_audit = _load_release_audit_module()
        original_pack = release_audit._npm_pack_dry_run_package
        base_package = original_pack()
        missing_template = dict(base_package)
        missing_template["files"] = [
            entry
            for entry in base_package["files"]
            if entry.get("path") != "templates/prd.md"
        ]

        release_audit._npm_pack_dry_run_package = lambda: missing_template
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_packaging_contracts()
        finally:
            release_audit._npm_pack_dry_run_package = original_pack

        self.assertIn("templates/prd.md", str(context.exception))

    def test_packaging_contracts_reject_missing_designer_visual_runtime(self):
        """El companion visual de Designer debe viajar en el paquete instalable."""
        release_audit = _load_release_audit_module()
        original_pack = release_audit._npm_pack_dry_run_package
        base_package = original_pack()
        missing_visual = dict(base_package)
        missing_visual["files"] = [
            entry
            for entry in base_package["files"]
            if entry.get("path") != "visual/scripts/start-server.sh"
        ]

        release_audit._npm_pack_dry_run_package = lambda: missing_visual
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_packaging_contracts()
        finally:
            release_audit._npm_pack_dry_run_package = original_pack

        self.assertIn("visual/scripts/start-server.sh", str(context.exception))

    def test_published_package_secret_scan_uses_canonical_patterns(self):
        """El artefacto publicable no debe contener patrones reales de secretos."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_published_secret_scan()

        self.assertIn("publishable package without real secret patterns", result)

    def test_install_update_contracts_use_explicit_safe_scopes(self):
        """Install/update deben usar scopes explícitos y mantener gate humana."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_install_update_contracts()

        self.assertIn("installers use explicit user scope", result)
        self.assertIn("installers verify user scope after install", result)
        self.assertIn("installers clean inherited local/project scopes before the user install", result)
        self.assertIn("installers do not touch ~/.claude/skills or install a global /alfred alias", result)
        self.assertNotIn("instalación local que limpiar", release_audit._read("uninstall.sh"))
        self.assertIn("update keeps semver and human menu, normalizes to user scope and documents reload/restart", result)

    def test_install_update_contracts_reject_new_stateful_cli_without_user_scope(self):
        """El gate debe detectar rutas nuevas aunque los comandos canonicos existan."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "install.sh":
                return text + '\nclaude plugin marketplace add "${REPO}"\n'
            return text

        try:
            release_audit._read = fake_read
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_install_update_contracts()
        finally:
            release_audit._read = original_read

        self.assertIn("CLI plugin without explicit user scope", str(context.exception))
        self.assertIn("install.sh", str(context.exception))

    def test_human_contracts_cover_questions_uat_and_honesty(self):
        """El release no puede perder menus humanos ni antifingimiento."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_human_contracts()

        self.assertIn("AskUserQuestion limited to real ambiguity and human gates", result)
        self.assertIn("UAT requires explicit human instruction", result)
        self.assertIn("anti-pretending centralized in commands and the Alfred agent", result)

    def test_audit_docs_require_manual_matrix_for_all_public_commands(self):
        """La matriz manual debe cubrir comandos y opciones publicas."""
        release_audit = _load_release_audit_module()

        result = release_audit.check_audit_docs()

        self.assertIn("manual matrix covers 18 public routes", result)
        self.assertIn("commands/ documented as supported flat skills", result)
        self.assertIn("manual matrix covers 40 public options", result)
        self.assertIn("manual matrix validates option IDs against public commands", result)
        self.assertIn("manual review report shows weak or repeated human notes", result)
        self.assertIn("manual review gate requires a current preflight before approval", result)
        self.assertIn("manual matrix links contracts to the correct command", result)
        self.assertIn("manual matrix validates prompts against declared commands", result)
        self.assertIn("manual matrix binds each argument-hint to a covered option", result)
        self.assertIn("manual matrix validates update runtime contracts", result)
        self.assertIn("manual matrix covers 4 runtime contracts", result)
        self.assertIn("manual smoke has a real auth preflight and fail-fast evidence", result)
        self.assertIn("manual evidence and templates are written with 0600 permissions", result)
        self.assertIn("manual evidence ignored by git and npm", result)
        self.assertIn("docs/project operating state ignored by git and npm", result)
        self.assertIn("manual evidence sanitizes previews with core/secrets.py", result)
        self.assertIn("manual review gate requires explicit human approval", result)
        self.assertIn("manual review gate rejects evidence/review with secrets", result)
        self.assertIn("manual review gate does not create templates from evidence with secrets", result)
        self.assertIn("manual review gate binds evidence_file to the validated JSON", result)
        self.assertIn("plugin_surface.sha256 is required in human review, not frozen in docs", result)
        self.assertIn("manual review gate validates review metadata against the current matrix", result)
        self.assertIn("manual review gate validates coverage maps against the current matrix", result)
        self.assertIn("manual/preflight npm scripts aligned", result)
        self.assertIn("prepublish:prepare generates manual evidence before the human review", result)
        self.assertIn("prepublish validates already reviewed manual evidence without regenerating it", result)
        self.assertIn("plugin details documents the human displayName", result)
        self.assertIn("official docs revalidated 2026-08-15", result)
        self.assertIn("release readiness keeps human and external pending items", result)
        self.assertIn("human review runbook documents criteria and blockers", result)

    def test_audit_docs_require_safe_external_preflight_runner(self):
        """Los pendientes externos deben tener evidencia sin efectos por defecto."""
        release_audit = _load_release_audit_module()
        package = release_audit._json("package.json")

        result = release_audit.check_audit_docs()

        self.assertIn("release readiness keeps human and external pending items", result)
        self.assertEqual(
            package["scripts"]["release:audit:external:preflight"],
            "python3 scripts/external_live_smoke.py --output docs/external-live-smoke-0.7.0.json",
        )
        self.assertIn("docs/external-live-smoke*.json", release_audit._read(".gitignore"))
        self.assertIn("docs/external-live-smoke*.json", release_audit._read(".npmignore"))

    def test_audit_docs_reject_prepare_without_evidence_generation(self):
        """La preparación debe escribir evidencia antes de que exista revisión humana."""
        release_audit = _load_release_audit_module()
        package = release_audit._json("package.json")
        original_json = release_audit._json

        def fake_json(path):
            if path == "package.json":
                mutated = dict(package)
                scripts = dict(mutated["scripts"])
                scripts["release:audit:prepublish:prepare"] = (
                    "npm run release:audit:full && "
                    "npm run release:audit:manual:preflight"
                )
                mutated["scripts"] = scripts
                return mutated
            return original_json(path)

        release_audit._json = fake_json
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._json = original_json

        self.assertIn("release:audit:prepublish:prepare", str(context.exception))
        self.assertIn("release:audit:manual:evidence", str(context.exception))

    def test_audit_docs_reject_manual_evidence_missing_from_gitignore_or_npmignore(self):
        """Los JSON de evidencia manual no deben aparecer en git ni en npm pack."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read_without_gitignore(path):
            text = original_read(path)
            if path == ".gitignore":
                return text.replace("docs/manual-smoke*.json\n", "")
            return text

        release_audit._read = fake_read_without_gitignore
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._read = original_read

        self.assertIn("docs/manual-smoke*.json", str(context.exception))

        def fake_read_without_npmignore(path):
            text = original_read(path)
            if path == ".npmignore":
                return text.replace("docs/manual-smoke*.json\n", "")
            return text

        release_audit._read = fake_read_without_npmignore
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._read = original_read

        self.assertIn("docs/manual-smoke*.json", str(context.exception))

    def test_audit_docs_reject_manual_reports_missing_from_gitignore_or_npmignore(self):
        """Los reportes Markdown de evidencia manual tampoco deben empaquetarse."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read_without_gitignore(path):
            text = original_read(path)
            if path == ".gitignore":
                return text.replace("docs/manual-smoke*.md\n", "")
            return text

        release_audit._read = fake_read_without_gitignore
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._read = original_read

        self.assertIn("docs/manual-smoke*.md", str(context.exception))

    def test_audit_docs_reject_project_state_missing_from_gitignore_or_npmignore(self):
        """Los artefactos operativos docs/project/ no forman parte del release."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read_without_gitignore(path):
            text = original_read(path)
            if path == ".gitignore":
                return text.replace("docs/project/\n", "")
            return text

        release_audit._read = fake_read_without_gitignore
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._read = original_read

        self.assertIn("docs/project/", str(context.exception))

        def fake_read_without_npmignore(path):
            text = original_read(path)
            if path == ".npmignore":
                return text.replace("docs/project/\n", "")
            return text

        release_audit._read = fake_read_without_npmignore
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._read = original_read

        self.assertIn("docs/project/", str(context.exception))

        def fake_read_without_npmignore(path):
            text = original_read(path)
            if path == ".npmignore":
                return text.replace("docs/manual-smoke*.md\n", "")
            return text

        release_audit._read = fake_read_without_npmignore
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._read = original_read

        self.assertIn("docs/manual-smoke*.md", str(context.exception))

    def test_audit_docs_reject_stale_plugin_details_display_name(self):
        """La pagina viva debe documentar el displayName visible en Claude Code."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "docs/release.md":
                return text.replace(
                    'displayName: "Alfred Dev"',
                    'displayName: "alfred-dev"',
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._read = original_read

        self.assertIn("human displayName", str(context.exception))

    def test_audit_docs_reject_frozen_plugin_surface_hash(self):
        """docs/release.md no debe congelar plugin_surface.sha256 de una run concreta."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "docs/release.md":
                return text + "\nplugin_surface.sha256=" + ("0" * 64) + "\n"
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._read = original_read

        self.assertIn("must not freeze plugin_surface.sha256", str(context.exception))

    def test_audit_docs_reject_architecture_claiming_all_hooks_have_matcher(self):
        """La arquitectura no debe prometer matcher universal en hooks."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "docs/architecture.md":
                return text.replace(
                    "`matcher` необязателен",
                    "у каждого хука есть matcher",
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._read = original_read

        self.assertIn("docs/architecture.md", str(context.exception))
        self.assertIn("`matcher` необязателен", str(context.exception))

    def test_audit_docs_reject_precompact_ignored_matcher_claim(self):
        """PreCompact soporta matcher; Alfred lo omite para cubrir manual y auto."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            text = original_read(path)
            if path == "docs/architecture.md":
                return text.replace(
                    "В `PreCompact` Alfred опускает `matcher`, чтобы покрыть и ручную, и автоматическую компактизацию.",
                    "В `PreCompact` Alfred не объявляет `matcher`, потому что Claude Code его игнорирует.",
                )
            return text

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._read = original_read

        self.assertIn("PreCompact ignores matcher", str(context.exception))

    def test_argument_hint_commands_are_covered_by_manual_options(self):
        """Todo comando con argument-hint/$ARGUMENTS debe tener opcion manual."""
        release_audit = _load_release_audit_module()
        manual_smoke = _load_manual_smoke_module()

        argument_commands = release_audit._public_argument_commands()
        aliases = getattr(manual_smoke, "_PUBLIC_COMMAND_ALIASES", {})
        option_commands = set()
        for key in manual_smoke.OPTION_CONTRACTS:
            prefix = key.split(":", 1)[0]
            option_commands.add(prefix)
            mapped = aliases.get(prefix)
            if mapped:
                option_commands.add(mapped)

        self.assertEqual(
            argument_commands,
            {
                "alfred",
                "discuss",
                "feature",
                "fix",
                "cto",
                "map-codebase",
                "quick",
                "spike",
                "sync-github",
                "uat",
                "memory-ui",
            },
        )
        self.assertEqual(sorted(argument_commands - option_commands), [])

    def test_new_argument_hint_without_manual_option_is_rejected(self):
        """Si un comando nuevo acepta argumentos, la matriz manual debe crecer."""
        release_audit = _load_release_audit_module()
        original_read = release_audit._read

        def fake_read(path):
            if path == "commands/pause.md":
                return (
                    "---\n"
                    "description: \"Pausa\"\n"
                    "argument-hint: \"[filtro opcional]\"\n"
                    "---\n"
                    "# /alfred-dev:pause\n\n"
                    "Filtro: $ARGUMENTS\n"
                )
            return original_read(path)

        release_audit._read = fake_read
        try:
            with self.assertRaises(release_audit.AuditError) as context:
                release_audit.check_audit_docs()
        finally:
            release_audit._read = original_read

        self.assertIn("pause", str(context.exception))

    def test_option_contract_shape_rejects_typos(self):
        """Los IDs de opciones deben apuntar a comandos reales y config exacta."""
        release_audit = _load_release_audit_module()
        manual_smoke = _load_manual_smoke_module()

        bad_contracts = tuple(manual_smoke.OPTION_CONTRACTS) + (
            "statuz:filter",
            "config:fantasma",
        )
        fake_manual_smoke = type("FakeManualSmoke", (), {"OPTION_CONTRACTS": bad_contracts})
        option_coverage = {key: ["case"] for key in bad_contracts}

        with self.assertRaises(release_audit.AuditError) as context:
            release_audit._validate_manual_option_contract_shape(
                fake_manual_smoke,
                option_coverage,
            )

        message = str(context.exception)
        self.assertIn("statuz", message)
        self.assertIn("config:fantasma", message)

    def test_option_contract_shape_requires_explicit_cto_all_scope(self):
        """CTO debe probar --scope all explicito, no solo el default all."""
        release_audit = _load_release_audit_module()
        manual_smoke = _load_manual_smoke_module()

        bad_contracts = tuple(
            key for key in manual_smoke.OPTION_CONTRACTS
            if key != "cto:scope-all"
        )
        fake_manual_smoke = type("FakeManualSmoke", (), {"OPTION_CONTRACTS": bad_contracts})
        option_coverage = {key: ["case"] for key in bad_contracts}

        with self.assertRaises(release_audit.AuditError) as context:
            release_audit._validate_manual_option_contract_shape(
                fake_manual_smoke,
                option_coverage,
            )

        self.assertIn("cto:scope-all", str(context.exception))

    def test_option_contract_shape_requires_human_permission_menus(self):
        """Los menus AskUserQuestion de permisos/gates son opciones publicas."""
        release_audit = _load_release_audit_module()
        manual_smoke = _load_manual_smoke_module()

        bad_contracts = tuple(
            key for key in manual_smoke.OPTION_CONTRACTS
            if key != "audit:sonarqube-docker-install-menu"
        )
        fake_manual_smoke = type("FakeManualSmoke", (), {"OPTION_CONTRACTS": bad_contracts})
        option_coverage = {key: ["case"] for key in bad_contracts}

        with self.assertRaises(release_audit.AuditError) as context:
            release_audit._validate_manual_option_contract_shape(
                fake_manual_smoke,
                option_coverage,
            )

        self.assertIn("audit:sonarqube-docker-install-menu", str(context.exception))

    def test_runtime_contract_shape_rejects_typos(self):
        """Los contratos runtime deben apuntar a /update y scopes conocidos."""
        release_audit = _load_release_audit_module()
        manual_smoke = _load_manual_smoke_module()

        bad_contracts = tuple(manual_smoke.RUNTIME_CONTRACTS) + (
            "updat:scope-local-to-user",
            "update:scope-worktree",
        )
        fake_manual_smoke = type("FakeManualSmoke", (), {"RUNTIME_CONTRACTS": bad_contracts})
        runtime_coverage = {key: ["case"] for key in bad_contracts}

        with self.assertRaises(release_audit.AuditError) as context:
            release_audit._validate_manual_runtime_contract_shape(
                fake_manual_smoke,
                runtime_coverage,
            )

        message = str(context.exception)
        self.assertIn("updat", message)
        self.assertIn("scope-worktree", message)

    def test_case_contract_links_reject_wrong_command_case(self):
        """Una opcion cubierta por un caso de otro comando no debe pasar."""
        release_audit = _load_release_audit_module()
        manual_smoke = _load_manual_smoke_module()

        bad_option_case = manual_smoke.ManualCase(
            "wrong-option",
            "/alfred-dev:help",
            "No debe cubrir CTO.",
            commands=("help",),
            option_keys=("cto:scope-tests",),
        )
        fake_manual_smoke = type("FakeManualSmoke", (), {"CASES": (bad_option_case,)})

        with self.assertRaises(release_audit.AuditError) as option_context:
            release_audit._validate_manual_case_contract_links(fake_manual_smoke)

        bad_runtime_case = manual_smoke.ManualCase(
            "wrong-runtime",
            "/alfred-dev:status",
            "No debe cubrir update.",
            commands=("status",),
            runtime_keys=("update:scope-local-to-user",),
        )
        fake_manual_smoke = type("FakeManualSmoke", (), {"CASES": (bad_runtime_case,)})

        with self.assertRaises(release_audit.AuditError) as runtime_context:
            release_audit._validate_manual_case_contract_links(fake_manual_smoke)

        self.assertIn("wrong-option", str(option_context.exception))
        self.assertIn("cto:scope-tests", str(option_context.exception))
        self.assertIn("wrong-runtime", str(runtime_context.exception))
        self.assertIn("update:scope-local-to-user", str(runtime_context.exception))

    def test_case_prompt_must_invoke_declared_command(self):
        """El prompt real del caso debe usar el slash command declarado."""
        release_audit = _load_release_audit_module()
        manual_smoke = _load_manual_smoke_module()

        wrong_prompt_case = manual_smoke.ManualCase(
            "wrong-prompt",
            "/alfred-dev:help",
            "No debe declarar CTO si el prompt ejecuta help.",
            commands=("cto",),
            option_keys=("cto:scope-tests",),
        )
        fake_manual_smoke = type("FakeManualSmoke", (), {"CASES": (wrong_prompt_case,)})

        with self.assertRaises(release_audit.AuditError) as context:
            release_audit._validate_manual_case_contract_links(fake_manual_smoke)

        message = str(context.exception)
        self.assertIn("wrong-prompt", message)
        self.assertIn("prompt does not invoke", message)
        self.assertIn("help", message)

    def test_case_prompt_accepts_global_alfred_alias_for_alfred_command(self):
        """El alias /alfred cubre el contrato manual del comando contextual."""
        release_audit = _load_release_audit_module()
        manual_smoke = _load_manual_smoke_module()

        alias_case = manual_smoke.ManualCase(
            "alfred-alias",
            "/alfred que toca hacer ahora?",
            "Debe aceptar el alias corto como invocacion de Alfred.",
            commands=("alfred",),
            option_keys=("alfred:optional-prompt",),
        )
        fake_manual_smoke = type("FakeManualSmoke", (), {"CASES": (alias_case,)})

        release_audit._validate_manual_case_contract_links(fake_manual_smoke)

    def test_installed_cache_freshness_detects_worktree_drift(self):
        """El smoke Claude no debe aceptar una cache instalada stale."""
        release_audit = _load_release_audit_module()
        original_installed = release_audit.INSTALLED_PLUGIN_DIR
        freshness_files = set(release_audit._iter_installed_cache_freshness_files())
        self.assertIn(".mcp.json", freshness_files)
        self.assertIn("package.json", freshness_files)
        self.assertIn("core/continuity.py", freshness_files)
        self.assertIn("templates/prd.md", freshness_files)
        self.assertIn("skills/pr-workflow/SKILL.md", freshness_files)
        self.assertIn("scripts/claude_auth_recovery.py", freshness_files)
        self.assertNotIn("skills/alfred/alfred/SKILL.md", freshness_files)

        def seed_cache(tmpdir: str) -> Path:
            cache = Path(tmpdir) / "cache"
            release_audit.INSTALLED_PLUGIN_DIR = cache
            for relative in freshness_files:
                source = release_audit.ROOT / relative
                target = cache / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
            return cache

        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                cache = seed_cache(tmpdir)
                transient_pyc = release_audit.ROOT / "hooks" / "__pycache__" / "transient.cpython-314.pyc"
                try:
                    transient_pyc.parent.mkdir(exist_ok=True)
                    transient_pyc.write_bytes(b"transient")

                    result = release_audit.check_installed_cache_freshness()
                    self.assertIn("installed 0.7.0 cache is complete", result[0])
                    self.assertIn("matches the worktree", result[0])
                finally:
                    transient_pyc.unlink(missing_ok=True)

                (cache / "agents" / "cto.md").write_text("stale cto\n", encoding="utf-8")
                with self.assertRaises(release_audit.AuditError) as context:
                    release_audit.check_installed_cache_freshness()

            self.assertIn("does not match", str(context.exception))
            self.assertIn("agents/cto.md", str(context.exception))

            with tempfile.TemporaryDirectory() as tmpdir:
                cache = seed_cache(tmpdir)
                (cache / "core" / "continuity.py").write_text("stale core\n", encoding="utf-8")
                with self.assertRaises(release_audit.AuditError) as context:
                    release_audit.check_installed_cache_freshness()

            self.assertIn("core/continuity.py", str(context.exception))

            with tempfile.TemporaryDirectory() as tmpdir:
                cache = seed_cache(tmpdir)
                (cache / "templates" / "prd.md").write_text("stale template\n", encoding="utf-8")
                with self.assertRaises(release_audit.AuditError) as context:
                    release_audit.check_installed_cache_freshness()

            self.assertIn("templates/prd.md", str(context.exception))
        finally:
            release_audit.INSTALLED_PLUGIN_DIR = original_installed


if __name__ == "__main__":
    unittest.main()
