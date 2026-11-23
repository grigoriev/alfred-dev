#!/usr/bin/env python3
"""Tests for the plugin config loader."""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.config_loader import (
    apply_config_section_update,
    build_config_section_change_preview,
    build_config_section_menu,
    build_config_section_summaries,
    build_session_team_from_config,
    build_project_session_team,
    DEFAULT_CONFIG,
    detect_stack,
    ensure_bootstrap_local_config,
    get_active_optional_agents,
    has_frontend,
    is_autopilot_configured,
    is_autopilot_enabled_for_project,
    load_config,
    load_project_config,
    render_config_markdown,
    save_config,
    save_project_config,
    suggest_optional_agents,
    update_config_section,
    update_project_config_section,
)
from core.optional_agents import (
    build_optional_agent_menu_option,
    build_optional_agent_group_menu,
    build_optional_agent_group_menus,
    get_optional_integrations,
    get_optional_agent_names,
    get_optional_agents_by_group,
    get_optional_agent_display_label,
    get_optional_agent_specialty,
    get_static_suggestible_agent_names,
)


class TestLoadConfig(unittest.TestCase):
    def test_returns_defaults_when_no_file(self):
        config = load_config("/path/that/does/not/exist")
        self.assertEqual(
            config["autonomy"],
            {
                "product": "autonomous",
                "architecture": "autonomous",
                "development": "autonomous",
                "quality": "autonomous",
                "documentation": "autonomous",
                "delivery": "autonomous",
            },
        )
        self.assertEqual(config["personality"], {"verbosity": "normal", "language": "ru"})
        self.assertEqual(config["memory"]["sync_commits_limit"], 10)
        self.assertFalse(config["memory"]["enabled"])

    def test_loads_yaml_frontmatter(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nautonomy:\n  product: autonomous\n---\n# Заметки\n")
            f.flush()
            config = load_config(f.name)
        os.unlink(f.name)
        self.assertEqual(config["autonomy"]["product"], "autonomous")
        self.assertEqual(config["autonomy"]["architecture"], "autonomous")

    def test_extracts_notes_section(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\nautonomy:\n  product: interactive\n---\n## Заметки\nPrefer Hono over Express.\n")
            f.flush()
            config = load_config(f.name)
        os.unlink(f.name)
        self.assertIn("Prefer Hono", config["notes"])

    def test_maps_legacy_autonomy_domains_to_current_phases(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(
                "---\n"
                "autonomy:\n"
                "  security: semi-autonomous\n"
                "  refactor: interactive\n"
                "  docs: interactive\n"
                "  devops: semi-autonomous\n"
                "  tests: interactive\n"
                "---\n"
            )
            f.flush()
            config = load_config(f.name)
        os.unlink(f.name)
        self.assertEqual(config["autonomy"]["development"], "interactive")
        self.assertEqual(config["autonomy"]["documentation"], "interactive")
        self.assertEqual(config["autonomy"]["delivery"], "semi-autonomous")
        self.assertEqual(config["autonomy"]["quality"], "interactive")
        self.assertEqual(config["autonomy"]["architecture"], "semi-autonomous")

    def test_parses_frontmatter_after_leading_blank_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("\n\n---\npersonality:\n  verbosity: high\n---\n")
            f.flush()
            config = load_config(f.name)
        os.unlink(f.name)
        self.assertEqual(config["personality"]["verbosity"], "high")

    def test_load_project_config_applies_detected_stack_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            with open(os.path.join(tmpdir, "package.json"), "w", encoding="utf-8") as f:
                json.dump({"name": "demo", "dependencies": {"next": "^15.0.0"}}, f)
            config = load_project_config(tmpdir)
        self.assertEqual(config["project"]["runtime"], "node")
        self.assertEqual(config["project"]["framework"], "next")

    def test_load_project_config_preserves_explicit_project_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = os.path.join(tmpdir, ".claude")
            os.makedirs(claude_dir, exist_ok=True)
            with open(os.path.join(tmpdir, "package.json"), "w", encoding="utf-8") as f:
                json.dump({"name": "demo", "dependencies": {"next": "^15.0.0"}}, f)
            with open(
                os.path.join(claude_dir, "alfred-dev.local.md"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write("---\nproject:\n  framework: hono\n---\n")
            config = load_project_config(tmpdir)
        self.assertEqual(config["project"]["runtime"], "node")
        self.assertEqual(config["project"]["framework"], "hono")

    def test_is_autopilot_configured_checks_all_phases(self):
        self.assertTrue(is_autopilot_configured(DEFAULT_CONFIG))
        config = load_config("/path/that/does/not/exist")
        config["autonomy"]["quality"] = "interactive"
        self.assertFalse(is_autopilot_configured(config))

    def test_is_autopilot_enabled_for_project_reads_state_flag(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = os.path.join(tmpdir, ".claude")
            os.makedirs(claude_dir, exist_ok=True)
            state_path = os.path.join(claude_dir, "alfred-dev-state.json")
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump({"autopilot": True}, f)
            self.assertTrue(is_autopilot_enabled_for_project(tmpdir))

    def test_get_active_optional_agents_returns_enabled_agents_in_catalog_order(self):
        config = load_config("/path/that/does/not/exist")
        config["optional_agents"]["cto"] = True
        self.assertEqual(
            get_active_optional_agents(config),
            ["cto"],
        )

    def test_build_session_team_from_config_returns_none_without_runtime_flags(self):
        config = load_config("/path/that/does/not/exist")
        config["optional_agents"]["cto"] = False
        self.assertIsNone(build_session_team_from_config(config))

    def test_build_session_team_from_config_keeps_cto_off_by_default(self):
        config = load_config("/path/that/does/not/exist")
        self.assertFalse(config["optional_agents"]["cto"])
        self.assertIsNone(build_session_team_from_config(config))

    def test_build_session_team_from_config_preserves_catalog_and_memory(self):
        config = load_config("/path/that/does/not/exist")
        config["optional_agents"]["cto"] = True
        config["memory"]["enabled"] = True

        team = build_session_team_from_config(config)

        self.assertEqual(team["source"], "persisted_config")
        self.assertTrue(team["active_optionals"]["cto"])
        self.assertTrue(team["infra"]["memory"])

    def test_legacy_lucius_key_is_accepted_as_cto(self):
        """Existing projects with `optional_agents.lucius` keep working."""
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = os.path.join(tmpdir, ".claude")
            os.makedirs(claude_dir, exist_ok=True)
            with open(
                os.path.join(claude_dir, "alfred-dev.local.md"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write("---\noptional_agents:\n  lucius: true\n---\n")

            config = load_project_config(tmpdir)
            team = build_project_session_team(tmpdir)

        self.assertTrue(config["optional_agents"]["cto"])
        self.assertNotIn("lucius", config["optional_agents"])
        self.assertEqual(get_active_optional_agents(config), ["cto"])
        self.assertTrue(team["active_optionals"]["cto"])
        # Direct alias without normalization, and priority of the canonical key.
        self.assertEqual(get_active_optional_agents({"optional_agents": {"lucius": True}}), ["cto"])
        self.assertEqual(
            get_active_optional_agents({"optional_agents": {"cto": False, "lucius": True}}),
            [],
        )

    def test_build_project_session_team_reads_local_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = os.path.join(tmpdir, ".claude")
            os.makedirs(claude_dir, exist_ok=True)
            with open(
                os.path.join(claude_dir, "alfred-dev.local.md"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    "---\n"
                    "optional_agents:\n"
                    "  cto: true\n"
                    "memory:\n"
                    "  enabled: true\n"
                    "---\n"
                )

            team = build_project_session_team(tmpdir)

        self.assertEqual(team["source"], "persisted_config")
        self.assertTrue(team["active_optionals"]["cto"])
        self.assertTrue(team["infra"]["memory"])

    def test_render_config_markdown_serializes_canonical_frontmatter_and_notes(self):
        config = load_config("/path/that/does/not/exist")
        config["optional_agents"]["cto"] = True
        config["personality"]["language"] = "es"
        content = render_config_markdown(config, notes="Prefer Netlify over Vercel.")

        self.assertTrue(content.startswith("---\nautonomy:\n"))
        self.assertIn("cto: true", content)
        self.assertIn("## Заметки", content)
        self.assertIn("Prefer Netlify over Vercel.", content)
        self.assertNotIn("\nnotes:", content)

    def test_save_config_roundtrips_with_load_config(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            path = f.name

        try:
            config = load_config("/path/that/does/not/exist")
            config["autonomy"]["quality"] = "interactive"
            config["optional_agents"]["cto"] = True
            config["memory"]["enabled"] = True
            save_config(path, config, notes="Review the copy before publishing.")

            reloaded = load_config(path)
        finally:
            os.unlink(path)

        self.assertEqual(reloaded["autonomy"]["quality"], "interactive")
        self.assertTrue(reloaded["optional_agents"]["cto"])
        self.assertTrue(reloaded["memory"]["enabled"])
        self.assertIn("Review the copy", reloaded["notes"])

    def test_save_project_config_writes_canonical_local_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config("/path/that/does/not/exist")
            config["optional_agents"]["cto"] = True

            path = save_project_config(
                tmpdir,
                config,
                notes="Keep the tone friendly.",
            )
            reloaded = load_config(path)

        self.assertTrue(path.endswith(os.path.join(".claude", "alfred-dev.local.md")))
        self.assertTrue(reloaded["optional_agents"]["cto"])
        self.assertIn("tone friendly", reloaded["notes"])

    def test_ensure_bootstrap_local_config_creates_minimal_canonical_file(self):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            path = f.name
        os.unlink(path)
        try:
            changed = ensure_bootstrap_local_config(path)
            reloaded = load_config(path)
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
        finally:
            os.unlink(path)

        self.assertTrue(changed)
        self.assertTrue(reloaded["memory"]["enabled"])
        self.assertEqual(reloaded["autonomy"]["product"], "autonomous")
        self.assertIn("Ты можешь настроить его через `/alfred-dev:config`.", content)

    def test_ensure_bootstrap_local_config_respects_explicit_memory_disable(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("---\nmemory:\n  enabled: false\n---\n")
            path = f.name
        try:
            changed = ensure_bootstrap_local_config(path)
            reloaded = load_config(path)
        finally:
            os.unlink(path)

        self.assertTrue(changed)
        self.assertFalse(reloaded["memory"]["enabled"])
        self.assertEqual(reloaded["autonomy"]["documentation"], "autonomous")

    def test_ensure_bootstrap_local_config_wraps_body_only_content(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write("# Заметки\n\nmemory:\n  enabled: true\n")
            path = f.name
        try:
            changed = ensure_bootstrap_local_config(path)
            reloaded = load_config(path)
            with open(path, "r", encoding="utf-8") as fh:
                content = fh.read()
        finally:
            os.unlink(path)

        self.assertTrue(changed)
        self.assertTrue(content.startswith("---\nautonomy:\n"))
        self.assertTrue(reloaded["memory"]["enabled"])

    def test_build_config_section_summaries_describe_effective_state(self):
        config = load_config("/path/that/does/not/exist")
        config["autonomy"]["product"] = "interactive"
        config["autonomy"]["quality"] = "semi-autonomous"
        config["optional_agents"]["cto"] = True
        config["memory"]["enabled"] = True

        summaries = build_config_section_summaries(config)

        self.assertEqual(
            [section["section"] for section in summaries],
            [
                "autonomy",
                "project",
                "optional_agents",
                "memory",
                "compliance",
                "integrations",
                "personality",
            ],
        )
        autonomy = next(section for section in summaries if section["section"] == "autonomy")
        agents = next(section for section in summaries if section["section"] == "optional_agents")
        memory = next(section for section in summaries if section["section"] == "memory")

        self.assertIn("интерактивных", autonomy["summary"])
        self.assertIn("Активных: 1", agents["summary"])
        self.assertIn("CTO", agents["summary"])
        self.assertIn("Активна с нативной синхронизацией", memory["summary"])

    def test_build_config_section_menu_uses_current_summaries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "package.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "name": "demo",
                        "dependencies": {"next": "^15.0.0", "@prisma/client": "^6.0.0"},
                        "devDependencies": {"vitest": "^3.0.0", "vite": "^6.0.0"},
                    },
                    f,
                )
            config = load_config("/path/that/does/not/exist")
            config["optional_agents"]["cto"] = True
            menu = build_config_section_menu(config, project_dir=tmpdir)

        labels = [option["label"] for option in menu["options"]]
        project_option = next(
            option for option in menu["options"]
            if option["label"] == "Проект"
        )
        agents_option = next(
            option for option in menu["options"]
            if option["label"] == "Опциональные агенты"
        )

        self.assertEqual(menu["header"], "Config")
        self.assertEqual(menu["question"], "Какую секцию хочешь изменить сейчас?")
        self.assertEqual(menu["questions"][0]["header"], "Config")
        self.assertEqual(menu["questions"][0]["question"], menu["question"])
        self.assertEqual(menu["questions"][0]["options"], menu["options"])
        self.assertEqual(menu["questions"][0]["multiSelect"], False)
        self.assertEqual(labels[0], "Выйти без изменений")
        self.assertIn("Автономность по фазам", labels)
        self.assertIn("Проект", labels)
        self.assertIn("Опциональные агенты", labels)
        self.assertIn("next", project_option["description"])
        self.assertIn("Определён автоматически.", project_option["description"])
        self.assertIn("CTO", agents_option["description"])

    def test_apply_config_section_update_normalizes_and_preserves_rest(self):
        config = load_config("/path/that/does/not/exist")
        config["memory"]["enabled"] = True

        updated = apply_config_section_update(
            config,
            "autonomy",
            {
                "product": "interactive",
                "documentation": "semi autonomous",
            },
        )

        self.assertEqual(updated["autonomy"]["product"], "interactive")
        self.assertEqual(updated["autonomy"]["documentation"], "semi-autonomous")
        self.assertEqual(updated["autonomy"]["quality"], "autonomous")
        self.assertTrue(updated["memory"]["enabled"])

    def test_apply_config_section_update_keeps_optional_catalog_complete(self):
        config = load_config("/path/that/does/not/exist")

        updated = apply_config_section_update(
            config,
            "optional_agents",
            {"cto": False},
        )

        self.assertFalse(updated["optional_agents"]["cto"])
        self.assertEqual(
            set(updated["optional_agents"].keys()),
            set(get_optional_agent_names()),
        )

    def test_all_config_sections_preview_and_persist_round_trip(self):
        updates = {
            "autonomy": {
                "product": "interactive",
                "quality": "semi-autonomous",
            },
            "project": {
                "runtime": "node",
                "language": "typescript",
                "framework": "next",
                "test_runner": "vitest",
                "bundler": "vite",
            },
            "optional_agents": {
                "cto": True,
            },
            "memory": {
                "enabled": True,
                "sync_commits_limit": 3,
                "retention_days": 30,
            },
            "compliance": {
                "style": "strict",
                "lint": False,
                "format_on_save": False,
            },
            "integrations": {
                "git": False,
                "ci": True,
                "deploy": True,
            },
            "personality": {
                "verbosity": "high",
                "language": "en",
            },
        }

        for section_name, patch in updates.items():
            with self.subTest(section=section_name):
                base_config = load_config("/path/that/does/not/exist")
                preview = build_config_section_change_preview(
                    base_config,
                    section_name,
                    patch,
                )

                self.assertTrue(preview["changed"], msg=preview)
                self.assertEqual(preview["section"], section_name)
                for key, value in patch.items():
                    self.assertEqual(preview["updated_config"][section_name][key], value)

                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".md",
                    delete=False,
                    encoding="utf-8",
                ) as f:
                    f.write(
                        "---\n"
                        "memory:\n"
                        "  enabled: false\n"
                        "---\n\n"
                        "## Заметки\n\n"
                        "Stable note.\n"
                    )
                    path = f.name

                try:
                    persisted_preview = update_config_section(
                        path,
                        section_name,
                        patch,
                        include_defaults=False,
                    )
                    reloaded = load_config(path)
                finally:
                    os.unlink(path)

                self.assertEqual(persisted_preview["section"], section_name)
                for key, value in patch.items():
                    self.assertEqual(reloaded[section_name][key], value)
                self.assertIn("Stable note", reloaded["notes"])

    def test_build_config_section_change_preview_reports_before_and_after(self):
        config = load_config("/path/that/does/not/exist")
        preview = build_config_section_change_preview(
            config,
            "memory",
            {"enabled": True},
        )

        self.assertTrue(preview["changed"])
        self.assertEqual(preview["label"], "Постоянная память")
        self.assertIn("Неактивна", preview["before"]["summary"])
        self.assertIn("Активна с нативной синхронизацией", preview["after"]["summary"])
        self.assertTrue(preview["updated_config"]["memory"]["enabled"])

    def test_build_config_section_change_preview_detects_noop_updates(self):
        config = load_config("/path/that/does/not/exist")
        preview = build_config_section_change_preview(
            config,
            "integrations",
            {"git": True},
        )

        self.assertFalse(preview["changed"])
        self.assertEqual(
            preview["before"]["details"],
            preview["after"]["details"],
        )

    def test_update_config_section_persists_one_section_and_keeps_notes(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(
                "---\n"
                "memory:\n"
                "  enabled: false\n"
                "---\n\n"
                "## Заметки\n\n"
                "Keep a friendly tone.\n"
            )
            path = f.name

        try:
            preview = update_config_section(
                path,
                "memory",
                {"enabled": True},
                include_defaults=False,
            )
            reloaded = load_config(path)
        finally:
            os.unlink(path)

        self.assertTrue(preview["changed"])
        self.assertTrue(reloaded["memory"]["enabled"])
        self.assertIn("Keep a friendly tone", reloaded["notes"])

    def test_update_project_config_section_writes_project_local_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = os.path.join(tmpdir, ".claude")
            os.makedirs(claude_dir, exist_ok=True)
            with open(
                os.path.join(claude_dir, "alfred-dev.local.md"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write("---\nintegrations:\n  ci: false\n---\n")

            preview = update_project_config_section(
                tmpdir,
                "integrations",
                {"ci": True},
                include_defaults=False,
            )
            reloaded = load_project_config(tmpdir)

        self.assertTrue(preview["changed"])
        self.assertTrue(reloaded["integrations"]["ci"])


class TestDetectStack(unittest.TestCase):
    def test_detects_node_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = {"name": "test", "dependencies": {"next": "^14.0.0"}}
            with open(os.path.join(tmpdir, "package.json"), "w") as f:
                json.dump(pkg, f)
            with open(os.path.join(tmpdir, "tsconfig.json"), "w") as f:
                json.dump({}, f)
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["runtime"], "node")
        self.assertEqual(stack["language"], "typescript")

    def test_detects_python_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "pyproject.toml"), "w") as f:
                f.write("[project]\nname = 'test'\n")
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["language"], "python")

    def test_returns_unknown_for_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["language"], "unknown")

    def test_prefers_frontend_framework_when_node_project_is_mixed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg = {
                "name": "test",
                "dependencies": {"react": "^18.0.0", "express": "^5.0.0"},
            }
            with open(os.path.join(tmpdir, "package.json"), "w") as f:
                json.dump(pkg, f)
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["framework"], "react")

    def test_has_frontend_accepts_common_framework_aliases(self):
        self.assertTrue(has_frontend({"framework": "nextjs"}))
        self.assertTrue(has_frontend({"framework": "next.js"}))
        self.assertTrue(has_frontend({"framework": "reactjs"}))

    def test_python_detection_ignores_stub_packages(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "requirements.txt"), "w") as f:
                f.write("django-stubs==5.0.0\npytest==8.0.0\n")
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["framework"], "unknown")
        self.assertEqual(stack["orm"], "none")
        self.assertEqual(stack["test_runner"], "pytest")

    def test_detects_jvm_maven_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "pom.xml"), "w", encoding="utf-8") as f:
                f.write(
                    "<project><dependencies>"
                    "<dependency><groupId>org.springframework.boot</groupId>"
                    "<artifactId>spring-boot-starter-web</artifactId></dependency>"
                    "<dependency><groupId>org.junit.jupiter</groupId>"
                    "<artifactId>junit-jupiter</artifactId></dependency>"
                    "</dependencies></project>"
                )
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["runtime"], "jvm")
        self.assertEqual(stack["language"], "java")
        self.assertEqual(stack["framework"], "spring-boot")
        self.assertEqual(stack["test_runner"], "junit")

    def test_jvm_manifest_wins_over_asset_only_package_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "pom.xml"), "w", encoding="utf-8") as f:
                f.write(
                    "<project><dependencies>"
                    "<dependency><groupId>org.springframework.boot</groupId>"
                    "<artifactId>spring-boot-starter-web</artifactId></dependency>"
                    "</dependencies></project>"
                )
            pkg = {
                "name": "app-frontend",
                "dependencies": {"htmx.org": "2.0.0", "alpinejs": "3.0.0"},
                "devDependencies": {"tailwindcss": "4.0.0"},
            }
            with open(os.path.join(tmpdir, "package.json"), "w", encoding="utf-8") as f:
                json.dump(pkg, f)
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["runtime"], "jvm")
        self.assertEqual(stack["language"], "java")
        self.assertEqual(stack["framework"], "spring-boot")

    def test_node_wins_when_package_json_declares_a_framework(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "pom.xml"), "w", encoding="utf-8") as f:
                f.write("<project></project>")
            with open(os.path.join(tmpdir, "package.json"), "w", encoding="utf-8") as f:
                json.dump({"name": "ui", "dependencies": {"react": "^18.0.0"}}, f)
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["runtime"], "node")
        self.assertEqual(stack["framework"], "react")

    def test_node_wins_over_requirements_txt_alone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "requirements.txt"), "w", encoding="utf-8") as f:
                f.write("pre-commit==4.0.0\n")
            with open(os.path.join(tmpdir, "package.json"), "w", encoding="utf-8") as f:
                json.dump({"name": "tool"}, f)
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["runtime"], "node")

    def test_detects_kotlin_gradle_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "build.gradle.kts"), "w", encoding="utf-8") as f:
                f.write(
                    "plugins { kotlin(\"jvm\") version \"2.0.0\" }\n"
                    "dependencies { implementation(\"io.quarkus:quarkus-rest\") }\n"
                )
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["runtime"], "jvm")
        self.assertEqual(stack["language"], "kotlin")
        self.assertEqual(stack["framework"], "quarkus")

    def test_detects_php_composer_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "composer.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "require": {
                            "laravel/framework": "^11.0",
                            "doctrine/orm": "^3.0",
                        },
                        "require-dev": {
                            "pestphp/pest": "^2.0",
                        },
                    },
                    f,
                )
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["runtime"], "php")
        self.assertEqual(stack["language"], "php")
        self.assertEqual(stack["framework"], "laravel")
        self.assertEqual(stack["orm"], "doctrine")
        self.assertEqual(stack["test_runner"], "pest")

    def test_detects_dotnet_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "App.csproj"), "w", encoding="utf-8") as f:
                f.write(
                    "<Project Sdk=\"Microsoft.NET.Sdk.Web\">"
                    "<ItemGroup>"
                    "<PackageReference Include=\"Microsoft.EntityFrameworkCore\" Version=\"8.0.0\" />"
                    "<PackageReference Include=\"xunit\" Version=\"2.8.0\" />"
                    "</ItemGroup>"
                    "</Project>"
                )
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["runtime"], "dotnet")
        self.assertEqual(stack["language"], "csharp")
        self.assertEqual(stack["framework"], "aspnet")
        self.assertEqual(stack["orm"], "entity-framework")
        self.assertEqual(stack["test_runner"], "xunit")

    def test_detects_swift_package_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "Package.swift"), "w", encoding="utf-8") as f:
                f.write(
                    "let package = Package(\n"
                    "  dependencies: [.package(url: \"https://github.com/vapor/vapor\", from: \"4.0.0\")],\n"
                    "  targets: [.testTarget(name: \"AppTests\", dependencies: [\"App\"])]\n"
                    ")\n"
                )
            stack = detect_stack(tmpdir)
        self.assertEqual(stack["runtime"], "swift")
        self.assertEqual(stack["language"], "swift")
        self.assertEqual(stack["framework"], "vapor")
        self.assertEqual(stack["test_runner"], "swift-test")


class TestOptionalAgents(unittest.TestCase):
    """Tests for the reduced optional agent catalog (CTO only)."""

    def test_default_config_has_optional_agents(self):
        self.assertIn("optional_agents", DEFAULT_CONFIG)
        agents = DEFAULT_CONFIG["optional_agents"]
        self.assertEqual(set(agents.keys()), {"cto"})
        self.assertFalse(agents["cto"])

    def test_optional_agent_catalog_keeps_group_distribution(self):
        grouped = get_optional_agents_by_group()
        self.assertEqual(list(grouped), ["audit"])
        self.assertEqual(grouped["audit"], ["cto"])

    def test_build_group_menus_returns_audit_only(self):
        menus = build_optional_agent_group_menus()
        self.assertEqual([menu["group"] for menu in menus], ["audit"])
        labels = [option["label"] for option in menus[0]["options"]]
        self.assertEqual(labels[0], "Продолжить без включения")
        self.assertIn("CTO", labels)

    def test_static_suggestions_exclude_cto(self):
        self.assertEqual(get_static_suggestible_agent_names(), ())

    def test_suggest_empty_for_any_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            suggestions = suggest_optional_agents(tmpdir)
        self.assertEqual(suggestions, [])

    def test_legacy_optional_flags_are_ignored(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write("---\noptional_agents:\n  data-engineer: true\n  cto: true\n---\n")
            f.flush()
            config = load_config(f.name)
        os.unlink(f.name)
        self.assertTrue(config["optional_agents"]["cto"])
        self.assertNotIn("data-engineer", config["optional_agents"])


class TestConfigCli(unittest.TestCase):
    def test_summary_headless_renders_menu_and_bootstraps_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable,
                    os.path.join(os.path.dirname(__file__), "..", "core", "config_cli.py"),
                    tmpdir,
                    "--headless",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("CONFIG_HEADLESS_MENU", result.stdout)
            self.assertIn("Автономность", result.stdout)
            self.assertIn("Личность", result.stdout)
            self.assertTrue(
                os.path.isfile(os.path.join(tmpdir, ".claude", "alfred-dev.local.md"))
            )



if __name__ == "__main__":
    unittest.main()
