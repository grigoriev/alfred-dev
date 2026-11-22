#!/usr/bin/env python3
"""Tests for the flow orchestrator."""

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.continuity import (
    CURRENT_RELATIVE_PATH,
    PROGRESS_MD_RELATIVE_PATH,
    TRACEABILITY_MD_RELATIVE_PATH,
    UAT_JSON_RELATIVE_PATH,
    UAT_MD_RELATIVE_PATH,
    load_kanban_board,
    write_uat_files,
)
from core.config_loader import load_config, save_project_config
from core.orchestrator import (
    FLOWS, create_session, advance_phase, check_gate,
    load_state, save_state, get_effective_agents,
    run_flow, _validate_session_team, _KNOWN_OPTIONAL_AGENTS,
    OPTIONAL_INTEGRATIONS,
    should_retry_phase, reset_phase_iterations,
    is_autopilot_gate_passable, run_flow_autopilot,
    MAX_PHASE_ITERATIONS,
)


def _save_project_config_with_optionals(
    project_dir: str,
    enabled_optionals,
    *,
    notes: str = "Temporary config for the test.",
) -> str:
    """Save a minimal local config that enables the given optional agents."""
    config = load_config("/path/that/does/not/exist")
    for agent_name in enabled_optionals:
        config["optional_agents"][agent_name] = True
    return save_project_config(
        project_dir,
        config,
        notes=notes,
        include_defaults=False,
    )


class TestFlows(unittest.TestCase):
    def test_feature_flow_has_7_phases(self):
        self.assertEqual(len(FLOWS["feature"]["phases"]), 7)

    def test_fix_flow_has_3_phases(self):
        self.assertEqual(len(FLOWS["fix"]["phases"]), 3)

    def test_quick_flow_has_2_phases(self):
        self.assertEqual(len(FLOWS["quick"]["phases"]), 2)

    def test_all_flows_defined(self):
        expected = {"feature", "fix", "quick", "spike", "ship", "audit"}
        self.assertEqual(set(FLOWS.keys()), expected)

    def test_architecture_gate_is_user_security(self):
        """The architecture phase must have the user+security gate."""
        phase_arq = FLOWS["feature"]["phases"][2]
        self.assertEqual(phase_arq["name"], "architecture")
        self.assertEqual(phase_arq["gate_type"], "user+security")

    def test_optional_integrations_cover_known_optional_agents(self):
        self.assertEqual(set(OPTIONAL_INTEGRATIONS.keys()), _KNOWN_OPTIONAL_AGENTS)


class TestSession(unittest.TestCase):
    def test_create_session(self):
        session = create_session("feature", "Authentication system")
        self.assertEqual(session["command"], "feature")
        self.assertEqual(session["current_phase"], "product")
        self.assertEqual(session["phase_number"], 0)
        self.assertEqual(len(session["completed_phases"]), 0)

    def test_save_and_load_state(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            session = create_session("fix", "Login bug")
            save_state(session, state_path)
            loaded = load_state(state_path)
            self.assertEqual(loaded["command"], "fix")
            self.assertEqual(loaded["description"], "Login bug")
        finally:
            os.unlink(state_path)

    def test_create_quick_session(self):
        session = create_session("quick", "Small login tweak")
        self.assertEqual(session["command"], "quick")
        self.assertEqual(session["current_phase"], "scoped_execution")
        self.assertEqual(session["phase_number"], 0)

    def test_create_session_accepts_optional_stack(self):
        session = create_session(
            "feature",
            "Authentication system",
            stack={"runtime": "python", "framework": "fastapi"},
        )
        self.assertEqual(session["stack"]["framework"], "fastapi")

    def test_save_state_syncs_active_session_to_kanban(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("feature", "Authentication system")

            save_state(session, state_path)

            loaded = load_state(state_path)
            board = load_kanban_board(tmpdir)

        self.assertTrue(loaded["kanban_task_id"].startswith("T-"))
        self.assertTrue(loaded["kanban_verify_task_id"].startswith("T-"))
        self.assertTrue(any(task["id"] == loaded["kanban_task_id"] for task in board["in-progress"]))
        self.assertTrue(any(task["id"] == loaded["kanban_verify_task_id"] for task in board["backlog"]))

    def test_save_state_assigns_task_types_to_runtime_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("feature", "Authentication system")

            save_state(session, state_path)

            loaded = load_state(state_path)
            board = load_kanban_board(tmpdir)

        main_task = next(task for task in board["in-progress"] if task["id"] == loaded["kanban_task_id"])
        verify_task = next(task for task in board["backlog"] if task["id"] == loaded["kanban_verify_task_id"])
        product_task = next(task for task in board["in-progress"] if task["title"].startswith("feature:product"))
        self.assertEqual(main_task["task_type"], "main")
        self.assertEqual(verify_task["task_type"], "verify")
        self.assertEqual(product_task["task_type"], "phase")

    def test_save_state_syncs_completed_session_to_done_and_keeps_verify(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("fix", "Login bug")
            save_state(session, state_path)
            while session["current_phase"] != "completed":
                session = advance_phase(session, result="approved", artifacts=[])

            save_state(session, state_path)

            loaded = load_state(state_path)
            board = load_kanban_board(tmpdir)

        self.assertTrue(any(task["id"] == loaded["kanban_task_id"] for task in board["done"]))
        self.assertFalse(any(task["id"] == loaded["kanban_task_id"] for task in board["in-progress"]))
        self.assertTrue(any(task["id"] == loaded["kanban_verify_task_id"] for task in board["backlog"]))

    def test_save_state_respects_rejected_uat_and_blocks_main_task(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("feature", "Checkout")
            save_state(session, state_path)
            while session["current_phase"] != "completed":
                session = advance_phase(session, result="approved", artifacts=[])
            save_state(session, state_path)

            loaded = load_state(state_path)
            write_uat_files(tmpdir, raw_request="rejected smoke roto")
            save_state(loaded, state_path)

            reloaded = load_state(state_path)
            board = load_kanban_board(tmpdir)

        self.assertTrue(any(task["id"] == reloaded["kanban_task_id"] for task in board["blocked"]))
        self.assertFalse(any(task["id"] == reloaded.get("kanban_verify_task_id", "") for task in board["backlog"]))

    def test_save_state_creates_phase_tasks_for_flow(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("fix", "Login bug")

            save_state(session, state_path)

            loaded = load_state(state_path)
            board = load_kanban_board(tmpdir)

        self.assertEqual(set(loaded["kanban_phase_task_ids"].keys()), {"diagnosis", "correction", "validation"})
        self.assertTrue(any(task["title"].startswith("fix:diagnosis") for task in board["in-progress"]))
        self.assertTrue(any(task["title"].startswith("fix:correction") for task in board["backlog"]))
        self.assertTrue(any(task["title"].startswith("fix:validation") for task in board["backlog"]))

    def test_save_state_updates_phase_tasks_when_advancing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("fix", "Login bug")
            save_state(session, state_path)
            session = load_state(state_path)
            session = advance_phase(session, result="approved", artifacts=["docs/diag.md"])

            save_state(session, state_path)

            board = load_kanban_board(tmpdir)

        diagnosis = next(task for task in board["done"] if task["title"].startswith("fix:diagnosis"))
        self.assertIn("результатом 'одобрено'", diagnosis["notes"])
        self.assertIn("Артефакты:", diagnosis["body"])
        self.assertIn("docs/diag.md", diagnosis["body"])
        self.assertTrue(any(task["title"].startswith("fix:correction") for task in board["in-progress"]))

    def test_save_state_generates_operational_docs_automatically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("feature", "Authentication system")

            save_state(session, state_path)

            with open(os.path.join(tmpdir, CURRENT_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                current = fh.read()
            with open(os.path.join(tmpdir, PROGRESS_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                progress = fh.read()
            with open(os.path.join(tmpdir, TRACEABILITY_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                traceability = fh.read()
            loaded = load_state(state_path)

        self.assertIn("Процесс: `feature`.", current)
        self.assertIn("Рекомендуемая следующая команда: /alfred-dev:resume", current)
        self.assertIn("Незакрытая gate: `user`.", current)
        self.assertIn("Завершено фаз: 0/7.", progress)
        self.assertIn("Видимый kanban:", progress)
        self.assertIn("## Фазы процесса", progress)
        self.assertIn("`product` -> `в работе` · gate `user`", progress)
        self.assertIn("Незакрытая gate:", traceability)
        self.assertIn("Главный риск:", traceability)
        self.assertIn("## Критерии и подтверждения по фазам", traceability)
        self.assertIn("### `product`", traceability)
        self.assertIn(
            "Видимые критерии: Анализ требований и определение функционального объёма новой feature; Закрыть gate `user` без открытых блокеров.",
            traceability,
        )
        self.assertIn("## Ручная проверка", traceability)
        self.assertIn(CURRENT_RELATIVE_PATH, loaded["artifacts"])
        self.assertIn(PROGRESS_MD_RELATIVE_PATH, loaded["artifacts"])
        self.assertIn(TRACEABILITY_MD_RELATIVE_PATH, loaded["artifacts"])

    def test_save_state_updates_operational_docs_after_completion_and_uat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("quick", "Small login tweak")
            save_state(session, state_path)
            while session["current_phase"] != "completed":
                session = advance_phase(session, result="approved", artifacts=["docs/change.md"])
            save_state(session, state_path)
            write_uat_files(tmpdir, raw_request="approved smoke manual correcto")

            with open(os.path.join(tmpdir, CURRENT_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                current = fh.read()
            with open(os.path.join(tmpdir, PROGRESS_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                progress = fh.read()
            with open(os.path.join(tmpdir, TRACEABILITY_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                traceability = fh.read()
            loaded = load_state(state_path)

        self.assertIn("Статус: завершено и проверено.", current)
        self.assertIn("Рекомендуемая следующая команда: /alfred", current)
        self.assertIn("Проверка/UAT: одобрена.", progress)
        self.assertIn("Накоплено артефактов: 6.", progress)
        self.assertIn("## Фазы процесса", progress)
        self.assertIn("`scoped_execution` -> `одобрено`", progress)
        self.assertIn("Текущая UAT: одобрена.", traceability)
        self.assertIn("## Ручная проверка", traceability)
        self.assertIn("Статус verify: `done`.", traceability)
        self.assertIn("docs/change.md", traceability)
        self.assertIn(UAT_MD_RELATIVE_PATH, traceability)
        self.assertIn(UAT_MD_RELATIVE_PATH, loaded["artifacts"])
        self.assertIn(UAT_JSON_RELATIVE_PATH, loaded["artifacts"])

    def test_save_state_operational_docs_show_active_optional_agents_for_phase(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("feature", "New checkout")
            session["current_phase"] = "quality"
            session["phase_number"] = 4
            session["session_team"] = {
                "active_optionals": {
                    "cto": True,
                },
                "infra": {
                    "memory": False,
                    "gui": False,
                },
                "source": "dynamic_composition",
            }

            save_state(session, state_path)

            with open(os.path.join(tmpdir, CURRENT_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                current = fh.read()
            with open(os.path.join(tmpdir, PROGRESS_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                progress = fh.read()
            with open(os.path.join(tmpdir, TRACEABILITY_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                traceability = fh.read()

        self.assertIn(
            "Активные опциональные специалисты: последовательно: `cto`.",
            current,
        )
        self.assertIn(
            "`quality` -> `в работе` · gate `automatic+security` · опциональные последовательно: `cto`",
            progress,
        )
        self.assertIn("- Опциональные последовательно: `cto`.", traceability)

    def test_save_state_operational_docs_show_release_optionals_for_ship(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("ship", "Release 1.2.0")
            session["session_team"] = {
                "active_optionals": {
                    "cto": True,
                },
                "infra": {
                    "memory": False,
                    "gui": False,
                },
                "source": "dynamic_composition",
            }

            expectations = [
                ("final_audit", 0, "последовательно: `cto`"),
            ]

            for phase_name, phase_number, expected_summary in expectations:
                session["current_phase"] = phase_name
                session["phase_number"] = phase_number
                save_state(session, state_path)

                with open(os.path.join(tmpdir, CURRENT_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                    current = fh.read()
                with open(os.path.join(tmpdir, PROGRESS_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                    progress = fh.read()
                with open(os.path.join(tmpdir, TRACEABILITY_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                    traceability = fh.read()

                self.assertIn(expected_summary, current)
                self.assertIn(expected_summary, progress)
                if "параллельно" in expected_summary:
                    self.assertIn(
                        f"- Опциональные параллельно: `{expected_summary.split('`')[1]}`.",
                        traceability,
                    )
                else:
                    self.assertIn(
                        f"- Опциональные последовательно: `{expected_summary.split('`')[1]}`.",
                        traceability,
                    )

    def test_feature_flow_uses_persisted_optional_agents_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            with open(os.path.join(tmpdir, "package.json"), "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "name": "demo",
                        "dependencies": {
                            "react": "^19.0.0",
                            "express": "^5.0.0",
                        },
                    },
                    fh,
                )
            _save_project_config_with_optionals(
                tmpdir,
                ["cto"],
            )
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")

            session = run_flow("feature", "New checkout", project_dir=tmpdir)
            save_state(session, state_path)

            persisted = load_state(state_path)
            with open(os.path.join(tmpdir, CURRENT_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                current = fh.read()
            with open(os.path.join(tmpdir, PROGRESS_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                progress = fh.read()
            with open(os.path.join(tmpdir, TRACEABILITY_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                traceability = fh.read()

        self.assertEqual(persisted["session_team"]["source"], "persisted_config")
        self.assertEqual(set(persisted["session_team"]["active_optionals"]), {"cto"})
        self.assertTrue(persisted["session_team"]["active_optionals"]["cto"])
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", current)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", progress)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", traceability)
        self.assertIn(
            "`quality` -> `ожидает` · gate `automatic+security` · опциональные последовательно: `cto`",
            progress,
        )
        self.assertIn("- Опциональные последовательно: `cto`.", traceability)

    def test_fix_flow_uses_persisted_optional_agents_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            _save_project_config_with_optionals(
                tmpdir,
                ["cto"],
            )
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")

            session = run_flow("fix", "Checkout regression", project_dir=tmpdir)
            save_state(session, state_path)

            persisted = load_state(state_path)
            with open(os.path.join(tmpdir, CURRENT_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                current = fh.read()
            with open(os.path.join(tmpdir, PROGRESS_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                progress = fh.read()
            with open(os.path.join(tmpdir, TRACEABILITY_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                traceability = fh.read()

        self.assertEqual(persisted["session_team"]["source"], "persisted_config")
        self.assertEqual(set(persisted["session_team"]["active_optionals"]), {"cto"})
        self.assertTrue(persisted["session_team"]["active_optionals"]["cto"])
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", current)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", progress)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", traceability)
        # CTO reviews only a finished feature, so it skips the validation phase.
        self.assertNotIn("опциональные последовательно: `cto`", progress)
        self.assertNotIn("- Опциональные последовательно: `cto`.", traceability)

    def test_ship_flow_uses_persisted_optional_agents_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            _save_project_config_with_optionals(
                tmpdir,
                ["cto"],
            )
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")

            session = run_flow("ship", "Release 2.0.0", project_dir=tmpdir)
            save_state(session, state_path)

            persisted = load_state(state_path)
            with open(os.path.join(tmpdir, CURRENT_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                current = fh.read()
            with open(os.path.join(tmpdir, PROGRESS_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                progress = fh.read()
            with open(os.path.join(tmpdir, TRACEABILITY_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                traceability = fh.read()

        self.assertEqual(persisted["session_team"]["source"], "persisted_config")
        self.assertEqual(set(persisted["session_team"]["active_optionals"]), {"cto"})
        self.assertTrue(persisted["session_team"]["active_optionals"]["cto"])
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", current)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", progress)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", traceability)
        self.assertIn("Активные опциональные специалисты: последовательно: `cto`.", current)
        self.assertIn(
            "`final_audit` -> `в работе` · gate `automatic+security` · опциональные последовательно: `cto`",
            progress,
        )
        self.assertIn("- Опциональные последовательно: `cto`.", traceability)

    def test_quick_flow_uses_persisted_optional_agents_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            _save_project_config_with_optionals(
                tmpdir,
                ["cto"],
            )
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")

            session = run_flow("quick", "Fine tuning", project_dir=tmpdir)
            save_state(session, state_path)

            persisted = load_state(state_path)
            with open(os.path.join(tmpdir, CURRENT_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                current = fh.read()
            with open(os.path.join(tmpdir, PROGRESS_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                progress = fh.read()
            with open(os.path.join(tmpdir, TRACEABILITY_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                traceability = fh.read()

        self.assertEqual(persisted["session_team"]["source"], "persisted_config")
        self.assertEqual(set(persisted["session_team"]["active_optionals"]), {"cto"})
        self.assertTrue(persisted["session_team"]["active_optionals"]["cto"])
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", current)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", progress)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", traceability)
        # CTO reviews only a finished feature, so it skips the quick_validation phase.
        self.assertNotIn("опциональные последовательно: `cto`", progress)
        self.assertNotIn("- Опциональные последовательно: `cto`.", traceability)

    def test_audit_flow_uses_persisted_optional_agents_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            _save_project_config_with_optionals(
                tmpdir,
                ["cto"],
            )
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")

            session = run_flow("audit", "Annual audit", project_dir=tmpdir)
            save_state(session, state_path)

            persisted = load_state(state_path)
            with open(os.path.join(tmpdir, CURRENT_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                current = fh.read()
            with open(os.path.join(tmpdir, PROGRESS_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                progress = fh.read()
            with open(os.path.join(tmpdir, TRACEABILITY_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                traceability = fh.read()

        self.assertEqual(persisted["session_team"]["source"], "persisted_config")
        self.assertEqual(set(persisted["session_team"]["active_optionals"]), {"cto"})
        self.assertTrue(persisted["session_team"]["active_optionals"]["cto"])
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", current)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", progress)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", traceability)
        # CTO reviews only a finished feature, so it skips the audit flow.
        self.assertNotIn("Активные опциональные специалисты: последовательно: `cto`.", current)
        self.assertNotIn("опциональные последовательно: `cto`", progress)
        self.assertIn("- Опциональные агенты в этом процессе только по запросу: `cto`.", traceability)

    def test_spike_flow_marks_persisted_optionals_as_on_demand_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            _save_project_config_with_optionals(
                tmpdir,
                ["cto"],
            )
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")

            session = run_flow("spike", "Evaluate Bun for jobs", project_dir=tmpdir)
            save_state(session, state_path)

            persisted = load_state(state_path)
            with open(os.path.join(tmpdir, CURRENT_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                current = fh.read()
            with open(os.path.join(tmpdir, PROGRESS_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                progress = fh.read()
            with open(os.path.join(tmpdir, TRACEABILITY_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                traceability = fh.read()

        self.assertEqual(persisted["session_team"]["source"], "persisted_config")
        self.assertEqual(set(persisted["session_team"]["active_optionals"]), {"cto"})
        self.assertTrue(persisted["session_team"]["active_optionals"]["cto"])
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", current)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", progress)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", traceability)
        self.assertIn(
            "- Опциональные агенты в этом процессе только по запросу: `cto`.",
            current,
        )
        self.assertIn(
            "- Опциональные агенты в этом процессе только по запросу: `cto`.",
            progress,
        )
        self.assertIn(
            "- Опциональные агенты в этом процессе только по запросу: `cto`.",
            traceability,
        )
        self.assertIn("`exploration` -> `в работе` · gate `free`", progress)
        self.assertIn("`conclusions` -> `ожидает` · gate `user`", progress)

    def test_save_state_operational_docs_show_cto_for_ship(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("ship", "Release")
            session["current_phase"] = "final_audit"
            session["phase_number"] = 0
            session["session_team"] = {
                "active_optionals": {
                    "cto": True,
                },
                "infra": {
                    "memory": False,
                    "gui": False,
                },
                "source": "dynamic_composition",
            }

            save_state(session, state_path)

            with open(os.path.join(tmpdir, CURRENT_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                current = fh.read()
            with open(os.path.join(tmpdir, PROGRESS_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                progress = fh.read()
            with open(os.path.join(tmpdir, TRACEABILITY_MD_RELATIVE_PATH), "r", encoding="utf-8") as fh:
                traceability = fh.read()

        self.assertIn("Активные опциональные специалисты: последовательно: `cto`.", current)
        self.assertIn("последовательно: `cto`", progress)
        self.assertIn("- Опциональные последовательно: `cto`.", traceability)

    def test_save_state_marks_skipped_phase_task_as_done(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session(
                "feature",
                "Authentication system",
                stack={"runtime": "python", "framework": "fastapi"},
            )
            save_state(session, state_path)
            session = load_state(state_path)
            session = advance_phase(session, result="approved", artifacts=[])

            save_state(session, state_path)

            board = load_kanban_board(tmpdir)

        product = next(task for task in board["done"] if task["title"].startswith("feature:product"))
        style = next(task for task in board["done"] if task["title"].startswith("feature:visual_style"))
        self.assertIn("результатом 'одобрено'", product["notes"])
        self.assertIn("пропущена", style["notes"])
        self.assertIn("Gate: user", product["body"])
        self.assertIn("Статус фазы: пропущена", style["body"])
        self.assertTrue(any(task["title"].startswith("feature:architecture") for task in board["in-progress"]))

    def test_ship_packaging_has_no_optional_agents(self):
        effective = get_effective_agents(
            "packaging",
            {"cto": True},
        )
        self.assertEqual(effective["parallel"], [])
        self.assertEqual(effective["sequential"], [])

    def test_ship_packaging_gate_is_automatic_security(self):
        packaging = FLOWS["ship"]["phases"][2]
        self.assertEqual(packaging["name"], "packaging")
        self.assertEqual(packaging["gate_type"], "automatic+security")

    def test_save_state_phase_task_body_includes_gate_and_iterations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("feature", "Authentication system")
            session["phase_iterations"] = 2
            session = advance_phase(session, result="approved", artifacts=["docs/product.md"])

            save_state(session, state_path)

            board = load_kanban_board(tmpdir)

        product = next(task for task in board["done"] if task["title"].startswith("feature:product"))
        self.assertIn("Gate: user", product["body"])
        self.assertIn("Внутренних итераций: 2", product["body"])
        self.assertIn("docs/product.md", product["body"])

    def test_save_state_enriches_visual_style_with_artifact_and_choice_evidence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            os.makedirs(os.path.join(tmpdir, "docs"), exist_ok=True)
            os.makedirs(
                os.path.join(tmpdir, ".alfred-dev", "visual", "session-1", "state"),
                exist_ok=True,
            )
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")

            with open(os.path.join(tmpdir, "docs", "style-direction.md"), "w", encoding="utf-8") as fh:
                fh.write("# Style direction\n")
            with open(
                os.path.join(tmpdir, ".alfred-dev", "visual", "session-1", "state", "events"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write(
                    '{"type":"click","choice":"B","label":"Warm editorial","ts":"2026-04-07T10:00:02Z"}\n'
                )

            session = create_session("feature", "Authentication system")
            session = advance_phase(session, result="approved", artifacts=["docs/product.md"])
            session = advance_phase(session, result="approved", artifacts=[])

            save_state(session, state_path)

            persisted = load_state(state_path)
            board = load_kanban_board(tmpdir)

        style_phase = next(
            phase for phase in persisted["completed_phases"] if phase["name"] == "visual_style"
        )
        self.assertIn("docs/style-direction.md", style_phase["artifacts"])
        self.assertIn("docs/style-direction.md", persisted["artifacts"])

        style_task = next(task for task in board["done"] if task["title"].startswith("feature:visual_style"))
        self.assertIn("docs/style-direction.md", style_task["body"])
        self.assertIn("Warm editorial", style_task["notes"])
        self.assertIn("Визуальный выбор", style_task["evidence"])


class TestGates(unittest.TestCase):
    def test_gate_passes_with_correct_result(self):
        session = create_session("feature", "Test feature")
        result = check_gate(session, result="approved")
        self.assertTrue(result["passed"])

    def test_gate_fails_with_incorrect_result(self):
        session = create_session("feature", "Test feature")
        result = check_gate(session, result="rejected")
        self.assertFalse(result["passed"])

    def test_automatic_gate_fails_when_tests_fail(self):
        """Automatic gates block if the tests fail."""
        session = create_session("feature", "Test")
        # Advance to the development phase (automatic gate)
        session = advance_phase(session)  # product -> visual_style
        session = advance_phase(session)  # visual_style -> architecture
        session = advance_phase(session)  # architecture -> development
        result = check_gate(session, result="approved", tests_ok=False)
        self.assertFalse(result["passed"])
        self.assertIn("тесты", result["reason"].lower())

    def test_automatic_gate_passes_when_tests_ok(self):
        """Automatic gates pass if the tests and the result are OK."""
        session = create_session("feature", "Test")
        session = advance_phase(session)  # product -> visual_style
        session = advance_phase(session)  # visual_style -> architecture
        session = advance_phase(session)  # architecture -> development
        result = check_gate(session, result="approved", tests_ok=True)
        self.assertTrue(result["passed"])

    def test_security_gate_fails_when_security_fails(self):
        """Gates with security block if security_ok is False."""
        session = create_session("feature", "Test")
        session = advance_phase(session)  # product -> visual_style
        session = advance_phase(session)  # visual_style -> architecture
        session = advance_phase(session)  # architecture -> development
        session = advance_phase(session)  # development -> quality
        # quality phase: automatic+security gate
        result = check_gate(session, result="approved", security_ok=False)
        self.assertFalse(result["passed"])
        self.assertIn("безопасности", result["reason"].lower())

    def test_advance_phase_propagates_tests_ok(self):
        """advance_phase passes tests_ok to check_gate."""
        session = create_session("feature", "Test")
        session = advance_phase(session)  # product -> visual_style
        session = advance_phase(session)  # visual_style -> architecture
        session = advance_phase(session)  # architecture -> development
        # Try to advance development with red tests
        with self.assertRaises(RuntimeError):
            advance_phase(session, result="approved", tests_ok=False)


class TestAdvancePhase(unittest.TestCase):
    def test_advance_moves_to_next_phase(self):
        session = create_session("feature", "Test")
        session = advance_phase(session, result="approved", artifacts=[])
        self.assertEqual(session["current_phase"], "visual_style")
        self.assertEqual(session["phase_number"], 1)
        self.assertEqual(len(session["completed_phases"]), 1)

    def test_cannot_advance_past_last_phase(self):
        session = create_session("spike", "Research")
        session = advance_phase(session, result="approved", artifacts=[])
        session = advance_phase(session, result="approved", artifacts=[])
        self.assertEqual(session["current_phase"], "completed")


# --- Shared fixture for team_session ---
# A valid session team with dynamic composition.
# The validation and run_flow tests use it as a reference.
VALID_SESSION_TEAM = {
    "active_optionals": {
        "cto": True,
    },
    "infra": {
        "memory": True,
        "gui": False,
    },
    "source": "dynamic_composition",
}


class TestValidateEquipoSesion(unittest.TestCase):
    """Validation of the session team structure."""

    def test_tc20_valid_complete_dict(self):
        """TC-20: a valid complete dict returns True."""
        self.assertTrue(_validate_session_team(VALID_SESSION_TEAM))

    def test_tc21_empty_dict(self):
        """TC-21: an empty dict returns False."""
        self.assertFalse(_validate_session_team({}))

    def test_tc22_extra_optional_agent_is_accepted_with_warning(self):
        """TC-22: an extra agent is accepted (True) but writes a warning to stderr."""
        import copy
        import io
        malo = copy.deepcopy(VALID_SESSION_TEAM)
        malo["active_optionals"]["made-up-agent"] = True
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            result = _validate_session_team(malo)
        finally:
            sys.stderr = old_stderr
        self.assertTrue(result)
        self.assertIn("made-up-agent", captured.getvalue())

    def test_tc22b_missing_optional_agent_fails(self):
        """TC-22b: if a known agent is missing, return False."""
        import copy
        malo = copy.deepcopy(VALID_SESSION_TEAM)
        del malo["active_optionals"]["cto"]
        self.assertFalse(_validate_session_team(malo))

    def test_tc22c_legacy_lucius_key_is_accepted_as_cto(self):
        """TC-22c: old states with `lucius` are normalized to `cto`."""
        import copy
        legacy = copy.deepcopy(VALID_SESSION_TEAM)
        legacy["active_optionals"]["lucius"] = legacy["active_optionals"].pop("cto")
        self.assertTrue(_validate_session_team(legacy))
        self.assertIn("cto", legacy["active_optionals"])
        self.assertNotIn("lucius", legacy["active_optionals"])

    def test_tc23_non_bool_optional_value(self):
        """TC-23: a non-boolean value in the optional agents returns False."""
        import copy
        malo = copy.deepcopy(VALID_SESSION_TEAM)
        malo["active_optionals"]["cto"] = "yes"
        self.assertFalse(_validate_session_team(malo))

    def test_tc23b_persisted_source_is_also_valid(self):
        """TC-23b: the persisted config uses the same runtime contract."""
        import copy
        persisted = copy.deepcopy(VALID_SESSION_TEAM)
        persisted["source"] = "persisted_config"
        self.assertTrue(_validate_session_team(persisted))


class TestRunFlow(unittest.TestCase):
    """Tests for run_flow, which creates a session with a team."""

    def test_tc15_without_team_session(self):
        """TC-15: run_flow without session_team takes the team from the default config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = run_flow("feature", "New feature", project_dir=tmpdir)
        self.assertIn("session_team", session)
        self.assertTrue(session["session_team"]["active_optionals"]["cto"])
        self.assertEqual(session["session_team"]["source"], "persisted_config")
        self.assertIsNone(session["session_team_error"])

    def test_tc16_with_valid_team_session(self):
        """TC-16: run_flow with a valid session_team injects it into the session."""
        session = run_flow("feature", "New feature", session_team=VALID_SESSION_TEAM)
        self.assertEqual(session["session_team"], VALID_SESSION_TEAM)
        self.assertIsNone(session["session_team_error"])

    def test_tc17_invalid_team_session_falls_back_to_config_with_error(self):
        """TC-17: run_flow with an invalid session_team falls back to the config and records the reason."""
        import io
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                session = run_flow(
                    "feature",
                    "Test",
                    session_team={"bad": True},
                    project_dir=tmpdir,
                )
        finally:
            sys.stderr = old_stderr
        self.assertEqual(session["session_team"]["source"], "persisted_config")
        self.assertIn("Alfred Dev", captured.getvalue())
        # Verify that the session records the reason for the rejection
        self.assertIsNotNone(session["session_team_error"])
        self.assertIn("не прошла проверку", session["session_team_error"])

    def test_tc18_unknown_command_raises_valueerror(self):
        """TC-18: run_flow with an unknown command raises ValueError."""
        with self.assertRaises(ValueError):
            run_flow("made-up", "Does not exist")

    def test_tc19_end_to_end_integration(self):
        """TC-19: run_flow -> extract optional agents -> get_effective_agents."""
        session = run_flow("feature", "New module", session_team=VALID_SESSION_TEAM)
        optionals = session["session_team"]["active_optionals"]
        architecture = get_effective_agents("architecture", optionals)
        quality = get_effective_agents("quality", optionals)
        self.assertEqual(architecture["parallel"], [])
        self.assertEqual(architecture["sequential"], [])
        self.assertIn("cto", quality["sequential"])

    def test_tc24_backward_compat_get_effective_agents_with_none(self):
        """TC-24: get_effective_agents(phase, None) still works."""
        result = get_effective_agents("quality", None)
        self.assertEqual(result, {"parallel": [], "sequential": []})

    def test_run_flow_detects_stack_and_injects_it_into_session(self):
        with patch(
            "core.config_loader.detect_stack",
            return_value={"runtime": "python", "framework": "fastapi", "language": "python"},
        ):
            session = run_flow("feature", "API backend")
        self.assertEqual(session["stack"]["framework"], "fastapi")

    def test_run_flow_skips_visual_style_when_detected_stack_has_no_frontend(self):
        with patch(
            "core.config_loader.detect_stack",
            return_value={"runtime": "python", "framework": "fastapi", "language": "python"},
        ):
            session = run_flow("feature", "API backend")

        session = advance_phase(session, result="approved")
        self.assertEqual(session["current_phase"], "architecture")
        skipped = [f for f in session["completed_phases"] if f["name"] == "visual_style"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["result"], "skipped")

    def test_run_flow_uses_persisted_project_config_when_no_ephemeral_team_is_passed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = os.path.join(tmpdir, ".claude")
            os.makedirs(claude_dir, exist_ok=True)
            with open(
                os.path.join(claude_dir, "alfred-dev.local.md"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write(
                    "---\n"
                    "optional_agents:\n"
                    "  cto: true\n"
                    "memory:\n"
                    "  enabled: true\n"
                    "---\n"
                )

            session = run_flow(
                "ship",
                "Release 2.0.0",
                project_dir=tmpdir,
            )

        self.assertIsNotNone(session["session_team"])
        self.assertEqual(session["session_team"]["source"], "persisted_config")
        self.assertEqual(set(session["session_team"]["active_optionals"]), {"cto"})
        self.assertTrue(session["session_team"]["active_optionals"]["cto"])
        self.assertTrue(session["session_team"]["infra"]["memory"])

    def test_run_flow_invalid_ephemeral_team_falls_back_to_persisted_project_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = os.path.join(tmpdir, ".claude")
            os.makedirs(claude_dir, exist_ok=True)
            with open(
                os.path.join(claude_dir, "alfred-dev.local.md"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write(
                    "---\n"
                    "optional_agents:\n"
                    "  cto: true\n"
                    "---\n"
                )

            session = run_flow(
                "ship",
                "Release 2.1.0",
                session_team={"bad": True},
                project_dir=tmpdir,
            )

        self.assertEqual(session["session_team"]["source"], "persisted_config")
        self.assertTrue(session["session_team"]["active_optionals"]["cto"])
        self.assertIsNotNone(session["session_team_error"])
        self.assertIn("Применена сохранённая конфигурация", session["session_team_error"])

    def test_quick_flow_uses_optional_agents_on_light_phases(self):
        """quick never includes CTO: it reviews only a finished feature."""
        optionals = {
            **VALID_SESSION_TEAM["active_optionals"],
            "cto": True,
        }
        ejecucion = get_effective_agents("scoped_execution", optionals)
        validation = get_effective_agents("quick_validation", optionals)
        self.assertEqual(ejecucion["parallel"], [])
        self.assertEqual(ejecucion["sequential"], [])
        self.assertNotIn("cto", validation["sequential"])

    def test_fix_flow_uses_optional_agents_on_bug_phases(self):
        """fix never includes CTO: it reviews only a finished feature."""
        optionals = {
            **VALID_SESSION_TEAM["active_optionals"],
            "cto": True,
        }
        diagnosis = get_effective_agents("diagnosis", optionals)
        correction = get_effective_agents("correction", optionals)
        validation = get_effective_agents("validation", optionals)

        self.assertEqual(diagnosis["parallel"], [])
        self.assertEqual(diagnosis["sequential"], [])
        self.assertEqual(correction["parallel"], [])
        self.assertEqual(correction["sequential"], [])
        self.assertNotIn("cto", validation["sequential"])

    def test_unknown_optional_flags_are_ignored_by_effective_agents(self):
        """Removed optional agents do not come back even if the state has them."""
        optionals = {
            "cto": True,
            "copywriter": True,
            "github-manager": True,
        }
        quality = get_effective_agents("quality", optionals)
        documentation = get_effective_agents("documentation", optionals)
        packaging = get_effective_agents("packaging", optionals)
        self.assertEqual(quality["sequential"], ["cto"])
        self.assertEqual(documentation["parallel"], [])
        self.assertEqual(packaging["sequential"], [])

    def test_cto_runs_as_external_audit_in_quality_closures(self):
        """CTO joins the closing phases as a sequential external audit."""
        optionals = {
            **VALID_SESSION_TEAM["active_optionals"],
            "cto": True,
        }
        quality = get_effective_agents("quality", optionals)
        auditoria = get_effective_agents("final_audit", optionals)
        self.assertIn("cto", quality["sequential"])
        self.assertIn("cto", auditoria["sequential"])

    def test_ship_and_audit_use_release_optional_agents(self):
        """ship includes CTO in the final audit; audit does not include it."""
        optionals = {
            **VALID_SESSION_TEAM["active_optionals"],
            "cto": True,
        }
        final_audit = get_effective_agents("final_audit", optionals)
        documentation = get_effective_agents("documentation", optionals)
        packaging = get_effective_agents("packaging", optionals)
        deployment = get_effective_agents("deployment", optionals)
        parallel_audit = get_effective_agents("parallel_audit", optionals)

        self.assertIn("cto", final_audit["sequential"])
        self.assertEqual(documentation["parallel"], [])
        self.assertEqual(packaging["sequential"], [])
        self.assertEqual(deployment["sequential"], [])
        self.assertNotIn("cto", parallel_audit["sequential"])


class TestIterativeLoop(unittest.TestCase):
    """Tests for the iterative loop inside phases (v0.4.0)."""

    def test_should_retry_when_gate_fails(self):
        """If the gate fails and iterations remain, recommend a retry."""
        session = create_session("feature", "Test loop")
        # Phase 0 = product, gate_type = user
        result = should_retry_phase(session, result="rejected")
        self.assertEqual(result["action"], "retry")
        self.assertEqual(result["iteration"], 1)

    def test_should_advance_when_gate_passes(self):
        """If the gate passes, recommend to advance."""
        session = create_session("feature", "Test loop")
        result = should_retry_phase(session, result="approved")
        self.assertEqual(result["action"], "advance")

    def test_should_escalate_after_max_iterations(self):
        """When iterations run out, recommend escalation to the user."""
        session = create_session("feature", "Test loop")
        session["phase_iterations"] = MAX_PHASE_ITERATIONS
        result = should_retry_phase(session, result="rejected")
        self.assertEqual(result["action"], "escalate")

    def test_iteration_counter_increments(self):
        """The iteration counter increments with each retry."""
        session = create_session("feature", "Test loop")
        session["phase_iterations"] = 0
        should_retry_phase(session, result="rejected")
        self.assertEqual(session["phase_iterations"], 1)
        should_retry_phase(session, result="rejected")
        self.assertEqual(session["phase_iterations"], 2)

    def test_reset_phase_iterations(self):
        """The reset sets the counter to 0."""
        session = create_session("feature", "Test loop")
        session["phase_iterations"] = 3
        reset_phase_iterations(session)
        self.assertEqual(session["phase_iterations"], 0)

    def test_advance_phase_resets_iterations(self):
        """Advancing the phase resets the counter automatically."""
        session = create_session("feature", "Test loop")
        session["phase_iterations"] = 3
        session = advance_phase(session, result="approved")
        self.assertEqual(session.get("phase_iterations", 0), 0)

    def test_advance_phase_preserves_iterations(self):
        """advance_phase stores the iteration counter in the completed phase."""
        session = create_session("feature", "Test iterations")
        session["phase_iterations"] = 3
        session = advance_phase(session, result="approved")
        completed_phase = session["completed_phases"][-1]
        self.assertEqual(completed_phase["iterations"], 3)

    def test_should_retry_invalid_session_state_escalates_instead_of_retrying(self):
        session = create_session("feature", "Test loop")
        session["phase_number"] = -1
        result = should_retry_phase(session, result="rejected")
        self.assertEqual(result["action"], "escalate")
        self.assertIn("Недопустимое", result["reason"])


class TestAutopilot(unittest.TestCase):
    """Tests for autopilot mode (v0.4.0)."""

    def test_run_flow_autopilot_creates_session(self):
        """Autopilot mode creates a session with the flag set."""
        session = run_flow_autopilot("feature", "Automatic login")
        self.assertTrue(session["autopilot"])

    def test_run_flow_autopilot_uses_persisted_project_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            claude_dir = os.path.join(tmpdir, ".claude")
            os.makedirs(claude_dir, exist_ok=True)
            with open(
                os.path.join(claude_dir, "alfred-dev.local.md"),
                "w",
                encoding="utf-8",
            ) as fh:
                fh.write(
                    "---\n"
                    "optional_agents:\n"
                    "  cto: true\n"
                    "---\n"
                )

            session = run_flow_autopilot("ship", "Automatic release", project_dir=tmpdir)

        self.assertTrue(session["autopilot"])
        self.assertEqual(session["session_team"]["source"], "persisted_config")
        self.assertTrue(session["session_team"]["active_optionals"]["cto"])
        self.assertEqual(session["phase_iterations"], 0)
        self.assertEqual(session["max_phase_iterations"], MAX_PHASE_ITERATIONS)

    def test_autopilot_approves_user_gates(self):
        """In autopilot, user gates are approved automatically."""
        session = create_session("feature", "Test autopilot")
        # Phase 0 = product, gate_type = user
        result = is_autopilot_gate_passable(session)
        self.assertTrue(result["passed"])
        self.assertIn("autopilot", result["reason"])

    def test_autopilot_evaluates_automatic_gates(self):
        """In autopilot, automatic gates are evaluated normally."""
        session = create_session("feature", "Test autopilot")
        # Advance to phase 3 = development, gate_type = automatic
        session = advance_phase(session, result="approved")  # product -> visual_style
        session = advance_phase(session, result="approved")  # visual_style -> architecture
        session = advance_phase(session, result="approved")  # architecture -> development
        result = is_autopilot_gate_passable(session, tests_ok=False)
        self.assertFalse(result["passed"])

    def test_autopilot_evaluates_security_gates(self):
        """In autopilot, security gates are evaluated normally."""
        session = create_session("feature", "Test autopilot")
        session = advance_phase(session, result="approved")  # product -> visual_style
        session = advance_phase(session, result="approved")  # visual_style -> architecture
        session = advance_phase(session, result="approved")  # architecture -> development
        session = advance_phase(session, result="approved", tests_ok=True)  # development -> quality
        # Phase 4 = quality, gate_type = automatic+security
        result = is_autopilot_gate_passable(session, security_ok=False)
        self.assertFalse(result["passed"])

    def test_autopilot_invalid_command(self):
        """Autopilot with an invalid command raises ValueError."""
        with self.assertRaises(ValueError):
            run_flow_autopilot("nonexistent", "Test")

    def test_autopilot_gate_completed_session(self):
        """is_autopilot_gate_passable does not fail with a completed session."""
        session = create_session("spike", "Test")
        session = advance_phase(session, result="approved")
        session = advance_phase(session, result="approved")
        # Now current_phase == "completed"
        result = is_autopilot_gate_passable(session)
        self.assertTrue(result["passed"])

    def test_autopilot_user_security_auto_approves_user_part(self):
        """In autopilot, GATE_USER_SECURITY approves the user part
        but evaluates the security part. This test documents the behavior."""
        session = create_session("feature", "Test autopilot")
        session = advance_phase(session, result="approved")  # product -> visual_style
        session = advance_phase(session, result="approved")  # visual_style -> architecture
        # Now in the architecture phase with the GATE_USER_SECURITY gate
        # With security OK: must pass
        result = is_autopilot_gate_passable(session, security_ok=True)
        self.assertTrue(result["passed"])
        # With security KO: must fail
        result = is_autopilot_gate_passable(session, security_ok=False)
        self.assertFalse(result["passed"])

    def test_autopilot_ship_deploy_keeps_user_confirmation_mandatory(self):
        session = create_session("ship", "Release autopilot")
        session = advance_phase(session, result="approved", tests_ok=True, security_ok=True)
        session = advance_phase(session, result="approved")
        session = advance_phase(session, result="approved", tests_ok=True, security_ok=True)

        self.assertEqual(session["current_phase"], "deployment")
        result = is_autopilot_gate_passable(session, security_ok=True)
        self.assertFalse(result["passed"])
        self.assertIn("явного подтверждения пользователя", result["reason"])


class TestCompletedSessionGuards(unittest.TestCase):
    """Verify that check_gate does not raise IndexError with completed sessions."""

    def test_check_gate_completed_session(self):
        """check_gate returns passed=True for completed sessions."""
        session = create_session("spike", "Research")
        session = advance_phase(session, result="approved")
        session = advance_phase(session, result="approved")
        self.assertEqual(session["current_phase"], "completed")
        result = check_gate(session, result="approved")
        self.assertTrue(result["passed"])

    def test_check_gate_overflowed_phase_number(self):
        """An out-of-range index must be rejected as an invalid state."""
        session = create_session("spike", "Test")
        session["phase_number"] = 999
        result = check_gate(session, result="approved")
        self.assertFalse(result["passed"])
        self.assertIn("вне диапазона", result["reason"])

    def test_check_gate_negative_phase_number_is_invalid(self):
        session = create_session("feature", "Test")
        session["phase_number"] = -1
        result = check_gate(session, result="approved")
        self.assertFalse(result["passed"])
        self.assertIn("отрицательным", result["reason"])

    def test_advance_phase_rejects_invalid_phase_index(self):
        session = create_session("feature", "Test")
        session["phase_number"] = -1
        with self.assertRaises(RuntimeError):
            advance_phase(session, result="approved")


class TestLoadStateValidation(unittest.TestCase):
    def test_load_state_rejects_negative_phase_index(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            with open(state_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "command": "feature",
                        "current_phase": "product",
                        "phase_number": -1,
                    },
                    fh,
                )
            self.assertIsNone(load_state(state_path))
        finally:
            os.unlink(state_path)

    def test_load_state_rejects_phase_name_mismatch(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            with open(state_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "command": "feature",
                        "current_phase": "product",
                        "phase_number": 3,
                    },
                    fh,
                )
            self.assertIsNone(load_state(state_path))
        finally:
            os.unlink(state_path)

    def test_load_state_accepts_coherent_completed_session(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            with open(state_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "command": "spike",
                        "current_phase": "completed",
                        "phase_number": len(FLOWS["spike"]["phases"]),
                    },
                    fh,
                )
            loaded = load_state(state_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["current_phase"], "completed")
        finally:
            os.unlink(state_path)


if __name__ == "__main__":
    unittest.main()
