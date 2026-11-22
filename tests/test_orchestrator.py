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
    run_flow, _validate_equipo_sesion, _KNOWN_OPTIONAL_AGENTS,
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
        config["agentes_opcionales"][agent_name] = True
    return save_project_config(
        project_dir,
        config,
        notes=notes,
        include_defaults=False,
    )


class TestFlows(unittest.TestCase):
    def test_feature_flow_has_7_phases(self):
        self.assertEqual(len(FLOWS["feature"]["fases"]), 7)

    def test_fix_flow_has_3_phases(self):
        self.assertEqual(len(FLOWS["fix"]["fases"]), 3)

    def test_quick_flow_has_2_phases(self):
        self.assertEqual(len(FLOWS["quick"]["fases"]), 2)

    def test_all_flows_defined(self):
        expected = {"feature", "fix", "quick", "spike", "ship", "audit"}
        self.assertEqual(set(FLOWS.keys()), expected)

    def test_architecture_gate_is_usuario_seguridad(self):
        """The arquitectura phase must have the usuario+seguridad gate."""
        fase_arq = FLOWS["feature"]["fases"][2]
        self.assertEqual(fase_arq["nombre"], "arquitectura")
        self.assertEqual(fase_arq["gate_tipo"], "usuario+seguridad")

    def test_optional_integrations_cover_known_optional_agents(self):
        self.assertEqual(set(OPTIONAL_INTEGRATIONS.keys()), _KNOWN_OPTIONAL_AGENTS)


class TestSession(unittest.TestCase):
    def test_create_session(self):
        session = create_session("feature", "Authentication system")
        self.assertEqual(session["comando"], "feature")
        self.assertEqual(session["fase_actual"], "producto")
        self.assertEqual(session["fase_numero"], 0)
        self.assertEqual(len(session["fases_completadas"]), 0)

    def test_save_and_load_state(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            session = create_session("fix", "Login bug")
            save_state(session, state_path)
            loaded = load_state(state_path)
            self.assertEqual(loaded["comando"], "fix")
            self.assertEqual(loaded["descripcion"], "Login bug")
        finally:
            os.unlink(state_path)

    def test_create_quick_session(self):
        session = create_session("quick", "Small login tweak")
        self.assertEqual(session["comando"], "quick")
        self.assertEqual(session["fase_actual"], "ejecucion_acotada")
        self.assertEqual(session["fase_numero"], 0)

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
        producto_task = next(task for task in board["in-progress"] if task["title"].startswith("feature:producto"))
        self.assertEqual(main_task["task_type"], "main")
        self.assertEqual(verify_task["task_type"], "verify")
        self.assertEqual(producto_task["task_type"], "phase")

    def test_save_state_syncs_completed_session_to_done_and_keeps_verify(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("fix", "Login bug")
            save_state(session, state_path)
            while session["fase_actual"] != "completado":
                session = advance_phase(session, resultado="aprobado", artefactos=[])

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
            while session["fase_actual"] != "completado":
                session = advance_phase(session, resultado="aprobado", artefactos=[])
            save_state(session, state_path)

            loaded = load_state(state_path)
            write_uat_files(tmpdir, raw_request="rechazado smoke roto")
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

        self.assertEqual(set(loaded["kanban_phase_task_ids"].keys()), {"diagnostico", "correccion", "validacion"})
        self.assertTrue(any(task["title"].startswith("fix:diagnostico") for task in board["in-progress"]))
        self.assertTrue(any(task["title"].startswith("fix:correccion") for task in board["backlog"]))
        self.assertTrue(any(task["title"].startswith("fix:validacion") for task in board["backlog"]))

    def test_save_state_updates_phase_tasks_when_advancing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("fix", "Login bug")
            save_state(session, state_path)
            session = load_state(state_path)
            session = advance_phase(session, resultado="aprobado", artefactos=["docs/diag.md"])

            save_state(session, state_path)

            board = load_kanban_board(tmpdir)

        diagnostico = next(task for task in board["done"] if task["title"].startswith("fix:diagnostico"))
        self.assertIn("результатом 'одобрено'", diagnostico["notes"])
        self.assertIn("Артефакты:", diagnostico["body"])
        self.assertIn("docs/diag.md", diagnostico["body"])
        self.assertTrue(any(task["title"].startswith("fix:correccion") for task in board["in-progress"]))

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
        self.assertIn("Рекомендуемая следующая команда: /alfred-dev:retomar", current)
        self.assertIn("Незакрытая gate: `usuario`.", current)
        self.assertIn("Завершено фаз: 0/7.", progress)
        self.assertIn("Видимый kanban:", progress)
        self.assertIn("## Фазы процесса", progress)
        self.assertIn("`producto` -> `в работе` · gate `usuario`", progress)
        self.assertIn("Незакрытая gate:", traceability)
        self.assertIn("Главный риск:", traceability)
        self.assertIn("## Критерии и подтверждения по фазам", traceability)
        self.assertIn("### `producto`", traceability)
        self.assertIn(
            "Видимые критерии: Анализ требований и определение функционального объёма новой feature; Закрыть gate `usuario` без открытых блокеров.",
            traceability,
        )
        self.assertIn("## Ручная проверка", traceability)
        self.assertIn(CURRENT_RELATIVE_PATH, loaded["artefactos"])
        self.assertIn(PROGRESS_MD_RELATIVE_PATH, loaded["artefactos"])
        self.assertIn(TRACEABILITY_MD_RELATIVE_PATH, loaded["artefactos"])

    def test_save_state_updates_operational_docs_after_completion_and_uat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("quick", "Small login tweak")
            save_state(session, state_path)
            while session["fase_actual"] != "completado":
                session = advance_phase(session, resultado="aprobado", artefactos=["docs/change.md"])
            save_state(session, state_path)
            write_uat_files(tmpdir, raw_request="aprobado smoke manual correcto")

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
        self.assertIn("`ejecucion_acotada` -> `одобрено`", progress)
        self.assertIn("Текущая UAT: одобрена.", traceability)
        self.assertIn("## Ручная проверка", traceability)
        self.assertIn("Статус verify: `done`.", traceability)
        self.assertIn("docs/change.md", traceability)
        self.assertIn(UAT_MD_RELATIVE_PATH, traceability)
        self.assertIn(UAT_MD_RELATIVE_PATH, loaded["artefactos"])
        self.assertIn(UAT_JSON_RELATIVE_PATH, loaded["artefactos"])

    def test_save_state_operational_docs_show_active_optional_agents_for_phase(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("feature", "New checkout")
            session["fase_actual"] = "calidad"
            session["fase_numero"] = 4
            session["equipo_sesion"] = {
                "opcionales_activos": {
                    "cto": True,
                },
                "infra": {
                    "memoria": False,
                    "gui": False,
                },
                "fuente": "composicion_dinamica",
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
            "`calidad` -> `в работе` · gate `automatico+seguridad` · опциональные последовательно: `cto`",
            progress,
        )
        self.assertIn("- Опциональные последовательно: `cto`.", traceability)

    def test_save_state_operational_docs_show_release_optionals_for_ship(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("ship", "Release 1.2.0")
            session["equipo_sesion"] = {
                "opcionales_activos": {
                    "cto": True,
                },
                "infra": {
                    "memoria": False,
                    "gui": False,
                },
                "fuente": "composicion_dinamica",
            }

            expectations = [
                ("auditoria_final", 0, "последовательно: `cto`"),
            ]

            for phase_name, phase_number, expected_summary in expectations:
                session["fase_actual"] = phase_name
                session["fase_numero"] = phase_number
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

        self.assertEqual(persisted["equipo_sesion"]["fuente"], "config_persistida")
        self.assertEqual(set(persisted["equipo_sesion"]["opcionales_activos"]), {"cto"})
        self.assertTrue(persisted["equipo_sesion"]["opcionales_activos"]["cto"])
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", current)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", progress)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", traceability)
        self.assertIn(
            "`calidad` -> `ожидает` · gate `automatico+seguridad` · опциональные последовательно: `cto`",
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

        self.assertEqual(persisted["equipo_sesion"]["fuente"], "config_persistida")
        self.assertEqual(set(persisted["equipo_sesion"]["opcionales_activos"]), {"cto"})
        self.assertTrue(persisted["equipo_sesion"]["opcionales_activos"]["cto"])
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", current)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", progress)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", traceability)
        self.assertIn(
            "`validacion` -> `ожидает` · gate `automatico+seguridad` · опциональные последовательно: `cto`",
            progress,
        )
        self.assertIn("- Опциональные последовательно: `cto`.", traceability)

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

        self.assertEqual(persisted["equipo_sesion"]["fuente"], "config_persistida")
        self.assertEqual(set(persisted["equipo_sesion"]["opcionales_activos"]), {"cto"})
        self.assertTrue(persisted["equipo_sesion"]["opcionales_activos"]["cto"])
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", current)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", progress)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", traceability)
        self.assertIn("Активные опциональные специалисты: последовательно: `cto`.", current)
        self.assertIn(
            "`auditoria_final` -> `в работе` · gate `automatico+seguridad` · опциональные последовательно: `cto`",
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

        self.assertEqual(persisted["equipo_sesion"]["fuente"], "config_persistida")
        self.assertEqual(set(persisted["equipo_sesion"]["opcionales_activos"]), {"cto"})
        self.assertTrue(persisted["equipo_sesion"]["opcionales_activos"]["cto"])
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", current)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", progress)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", traceability)
        self.assertIn(
            "`validacion_rapida` -> `ожидает` · gate `automatico+seguridad` · опциональные последовательно: `cto`",
            progress,
        )
        self.assertIn("- Опциональные последовательно: `cto`.", traceability)

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

        self.assertEqual(persisted["equipo_sesion"]["fuente"], "config_persistida")
        self.assertEqual(set(persisted["equipo_sesion"]["opcionales_activos"]), {"cto"})
        self.assertTrue(persisted["equipo_sesion"]["opcionales_activos"]["cto"])
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", current)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", progress)
        self.assertIn("- Источник runtime-команды: сохранённая конфигурация.", traceability)
        self.assertIn("Активные опциональные специалисты: последовательно: `cto`.", current)
        self.assertIn(
            "`auditoria_paralela` -> `в работе` · gate `automatico+seguridad` · опциональные последовательно: `cto`",
            progress,
        )
        self.assertIn("- Опциональные последовательно: `cto`.", traceability)

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

        self.assertEqual(persisted["equipo_sesion"]["fuente"], "config_persistida")
        self.assertEqual(set(persisted["equipo_sesion"]["opcionales_activos"]), {"cto"})
        self.assertTrue(persisted["equipo_sesion"]["opcionales_activos"]["cto"])
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
        self.assertIn("`exploracion` -> `в работе` · gate `libre`", progress)
        self.assertIn("`conclusiones` -> `ожидает` · gate `usuario`", progress)

    def test_save_state_operational_docs_show_cto_for_audit(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("audit", "Annual audit")
            session["fase_actual"] = "auditoria_paralela"
            session["fase_numero"] = 0
            session["equipo_sesion"] = {
                "opcionales_activos": {
                    "cto": True,
                },
                "infra": {
                    "memoria": False,
                    "gui": False,
                },
                "fuente": "composicion_dinamica",
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
            session = advance_phase(session, resultado="aprobado", artefactos=[])

            save_state(session, state_path)

            board = load_kanban_board(tmpdir)

        producto = next(task for task in board["done"] if task["title"].startswith("feature:producto"))
        estilo = next(task for task in board["done"] if task["title"].startswith("feature:estilo_visual"))
        self.assertIn("результатом 'одобрено'", producto["notes"])
        self.assertIn("пропущена", estilo["notes"])
        self.assertIn("Gate: usuario", producto["body"])
        self.assertIn("Статус фазы: пропущена", estilo["body"])
        self.assertTrue(any(task["title"].startswith("feature:arquitectura") for task in board["in-progress"]))

    def test_ship_empaquetado_has_no_optional_agents(self):
        effective = get_effective_agents(
            "empaquetado",
            {"cto": True},
        )
        self.assertEqual(effective["paralelo"], [])
        self.assertEqual(effective["secuencial"], [])

    def test_ship_empaquetado_gate_is_automatico_seguridad(self):
        empaquetado = FLOWS["ship"]["fases"][2]
        self.assertEqual(empaquetado["nombre"], "empaquetado")
        self.assertEqual(empaquetado["gate_tipo"], "automatico+seguridad")

    def test_save_state_phase_task_body_includes_gate_and_iterations(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, ".claude"), exist_ok=True)
            state_path = os.path.join(tmpdir, ".claude", "alfred-dev-state.json")
            session = create_session("feature", "Authentication system")
            session["iteraciones_fase"] = 2
            session = advance_phase(session, resultado="aprobado", artefactos=["docs/producto.md"])

            save_state(session, state_path)

            board = load_kanban_board(tmpdir)

        producto = next(task for task in board["done"] if task["title"].startswith("feature:producto"))
        self.assertIn("Gate: usuario", producto["body"])
        self.assertIn("Внутренних итераций: 2", producto["body"])
        self.assertIn("docs/producto.md", producto["body"])

    def test_save_state_enriches_estilo_visual_with_artifact_and_choice_evidence(self):
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
            session = advance_phase(session, resultado="aprobado", artefactos=["docs/producto.md"])
            session = advance_phase(session, resultado="aprobado", artefactos=[])

            save_state(session, state_path)

            persisted = load_state(state_path)
            board = load_kanban_board(tmpdir)

        estilo_phase = next(
            phase for phase in persisted["fases_completadas"] if phase["nombre"] == "estilo_visual"
        )
        self.assertIn("docs/style-direction.md", estilo_phase["artefactos"])
        self.assertIn("docs/style-direction.md", persisted["artefactos"])

        estilo_task = next(task for task in board["done"] if task["title"].startswith("feature:estilo_visual"))
        self.assertIn("docs/style-direction.md", estilo_task["body"])
        self.assertIn("Warm editorial", estilo_task["notes"])
        self.assertIn("Визуальный выбор", estilo_task["evidence"])


class TestGates(unittest.TestCase):
    def test_gate_passes_with_correct_result(self):
        session = create_session("feature", "Test feature")
        result = check_gate(session, resultado="aprobado")
        self.assertTrue(result["passed"])

    def test_gate_fails_with_incorrect_result(self):
        session = create_session("feature", "Test feature")
        result = check_gate(session, resultado="rechazado")
        self.assertFalse(result["passed"])

    def test_automatic_gate_fails_when_tests_fail(self):
        """Automatic gates block if the tests fail."""
        session = create_session("feature", "Test")
        # Advance to the desarrollo phase (automatic gate)
        session = advance_phase(session)  # producto -> estilo_visual
        session = advance_phase(session)  # estilo_visual -> arquitectura
        session = advance_phase(session)  # arquitectura -> desarrollo
        result = check_gate(session, resultado="aprobado", tests_ok=False)
        self.assertFalse(result["passed"])
        self.assertIn("тесты", result["reason"].lower())

    def test_automatic_gate_passes_when_tests_ok(self):
        """Automatic gates pass if the tests and the result are OK."""
        session = create_session("feature", "Test")
        session = advance_phase(session)  # producto -> estilo_visual
        session = advance_phase(session)  # estilo_visual -> arquitectura
        session = advance_phase(session)  # arquitectura -> desarrollo
        result = check_gate(session, resultado="aprobado", tests_ok=True)
        self.assertTrue(result["passed"])

    def test_security_gate_fails_when_security_fails(self):
        """Gates with security block if security_ok is False."""
        session = create_session("feature", "Test")
        session = advance_phase(session)  # producto -> estilo_visual
        session = advance_phase(session)  # estilo_visual -> arquitectura
        session = advance_phase(session)  # arquitectura -> desarrollo
        session = advance_phase(session)  # desarrollo -> calidad
        # calidad phase: automatico+seguridad gate
        result = check_gate(session, resultado="aprobado", security_ok=False)
        self.assertFalse(result["passed"])
        self.assertIn("безопасности", result["reason"].lower())

    def test_advance_phase_propagates_tests_ok(self):
        """advance_phase passes tests_ok to check_gate."""
        session = create_session("feature", "Test")
        session = advance_phase(session)  # producto -> estilo_visual
        session = advance_phase(session)  # estilo_visual -> arquitectura
        session = advance_phase(session)  # arquitectura -> desarrollo
        # Try to advance desarrollo with red tests
        with self.assertRaises(RuntimeError):
            advance_phase(session, resultado="aprobado", tests_ok=False)


class TestAdvancePhase(unittest.TestCase):
    def test_advance_moves_to_next_phase(self):
        session = create_session("feature", "Test")
        session = advance_phase(session, resultado="aprobado", artefactos=[])
        self.assertEqual(session["fase_actual"], "estilo_visual")
        self.assertEqual(session["fase_numero"], 1)
        self.assertEqual(len(session["fases_completadas"]), 1)

    def test_cannot_advance_past_last_phase(self):
        session = create_session("spike", "Research")
        session = advance_phase(session, resultado="aprobado", artefactos=[])
        session = advance_phase(session, resultado="aprobado", artefactos=[])
        self.assertEqual(session["fase_actual"], "completado")


# --- Shared fixture for equipo_sesion ---
# A valid session team with dynamic composition.
# The validation and run_flow tests use it as a reference.
VALID_EQUIPO_SESION = {
    "opcionales_activos": {
        "cto": True,
    },
    "infra": {
        "memoria": True,
        "gui": False,
    },
    "fuente": "composicion_dinamica",
}


class TestValidateEquipoSesion(unittest.TestCase):
    """Validation of the session team structure."""

    def test_tc20_valid_complete_dict(self):
        """TC-20: a valid complete dict returns True."""
        self.assertTrue(_validate_equipo_sesion(VALID_EQUIPO_SESION))

    def test_tc21_empty_dict(self):
        """TC-21: an empty dict returns False."""
        self.assertFalse(_validate_equipo_sesion({}))

    def test_tc22_extra_optional_agent_is_accepted_with_warning(self):
        """TC-22: an extra agent is accepted (True) but writes a warning to stderr."""
        import copy
        import io
        malo = copy.deepcopy(VALID_EQUIPO_SESION)
        malo["opcionales_activos"]["made-up-agent"] = True
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            result = _validate_equipo_sesion(malo)
        finally:
            sys.stderr = old_stderr
        self.assertTrue(result)
        self.assertIn("made-up-agent", captured.getvalue())

    def test_tc22b_missing_optional_agent_fails(self):
        """TC-22b: if a known agent is missing, return False."""
        import copy
        malo = copy.deepcopy(VALID_EQUIPO_SESION)
        del malo["opcionales_activos"]["cto"]
        self.assertFalse(_validate_equipo_sesion(malo))

    def test_tc22c_legacy_lucius_key_is_accepted_as_cto(self):
        """TC-22c: old states with `lucius` are normalized to `cto`."""
        import copy
        legacy = copy.deepcopy(VALID_EQUIPO_SESION)
        legacy["opcionales_activos"]["lucius"] = legacy["opcionales_activos"].pop("cto")
        self.assertTrue(_validate_equipo_sesion(legacy))
        self.assertIn("cto", legacy["opcionales_activos"])
        self.assertNotIn("lucius", legacy["opcionales_activos"])

    def test_tc23_non_bool_optional_value(self):
        """TC-23: a non-boolean value in the optional agents returns False."""
        import copy
        malo = copy.deepcopy(VALID_EQUIPO_SESION)
        malo["opcionales_activos"]["cto"] = "yes"
        self.assertFalse(_validate_equipo_sesion(malo))

    def test_tc23b_persisted_source_is_also_valid(self):
        """TC-23b: the persisted config uses the same runtime contract."""
        import copy
        persisted = copy.deepcopy(VALID_EQUIPO_SESION)
        persisted["fuente"] = "config_persistida"
        self.assertTrue(_validate_equipo_sesion(persisted))


class TestRunFlow(unittest.TestCase):
    """Tests for run_flow, which creates a session with a team."""

    def test_tc15_without_equipo_sesion(self):
        """TC-15: run_flow without equipo_sesion creates a session with equipo_sesion=None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            session = run_flow("feature", "New feature", project_dir=tmpdir)
        self.assertIn("equipo_sesion", session)
        self.assertIsNone(session["equipo_sesion"])
        self.assertIsNone(session["equipo_sesion_error"])

    def test_tc16_with_valid_equipo_sesion(self):
        """TC-16: run_flow with a valid equipo_sesion injects it into the session."""
        session = run_flow("feature", "New feature", equipo_sesion=VALID_EQUIPO_SESION)
        self.assertEqual(session["equipo_sesion"], VALID_EQUIPO_SESION)
        self.assertIsNone(session["equipo_sesion_error"])

    def test_tc17_invalid_equipo_sesion_falls_back_to_none_with_error(self):
        """TC-17: run_flow with an invalid equipo_sesion falls back to None and records the reason."""
        import io
        captured = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = captured
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                session = run_flow(
                    "feature",
                    "Test",
                    equipo_sesion={"bad": True},
                    project_dir=tmpdir,
                )
        finally:
            sys.stderr = old_stderr
        self.assertIsNone(session["equipo_sesion"])
        self.assertIn("Alfred Dev", captured.getvalue())
        # Verify that the session records the reason for the rejection
        self.assertIsNotNone(session["equipo_sesion_error"])
        self.assertIn("не прошла проверку", session["equipo_sesion_error"])

    def test_tc18_unknown_command_raises_valueerror(self):
        """TC-18: run_flow with an unknown command raises ValueError."""
        with self.assertRaises(ValueError):
            run_flow("made-up", "Does not exist")

    def test_tc19_end_to_end_integration(self):
        """TC-19: run_flow -> extract optional agents -> get_effective_agents."""
        session = run_flow("feature", "New module", equipo_sesion=VALID_EQUIPO_SESION)
        opcionales = session["equipo_sesion"]["opcionales_activos"]
        arquitectura = get_effective_agents("arquitectura", opcionales)
        calidad = get_effective_agents("calidad", opcionales)
        self.assertEqual(arquitectura["paralelo"], [])
        self.assertEqual(arquitectura["secuencial"], [])
        self.assertIn("cto", calidad["secuencial"])

    def test_tc24_backward_compat_get_effective_agents_with_none(self):
        """TC-24: get_effective_agents(fase, None) still works."""
        result = get_effective_agents("calidad", None)
        self.assertEqual(result, {"paralelo": [], "secuencial": []})

    def test_run_flow_detects_stack_and_injects_it_into_session(self):
        with patch(
            "core.config_loader.detect_stack",
            return_value={"runtime": "python", "framework": "fastapi", "lenguaje": "python"},
        ):
            session = run_flow("feature", "API backend")
        self.assertEqual(session["stack"]["framework"], "fastapi")

    def test_run_flow_skips_estilo_visual_when_detected_stack_has_no_frontend(self):
        with patch(
            "core.config_loader.detect_stack",
            return_value={"runtime": "python", "framework": "fastapi", "lenguaje": "python"},
        ):
            session = run_flow("feature", "API backend")

        session = advance_phase(session, resultado="aprobado")
        self.assertEqual(session["fase_actual"], "arquitectura")
        skipped = [f for f in session["fases_completadas"] if f["nombre"] == "estilo_visual"]
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["resultado"], "saltada")

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
                    "agentes_opcionales:\n"
                    "  cto: true\n"
                    "memoria:\n"
                    "  enabled: true\n"
                    "---\n"
                )

            session = run_flow(
                "ship",
                "Release 2.0.0",
                project_dir=tmpdir,
            )

        self.assertIsNotNone(session["equipo_sesion"])
        self.assertEqual(session["equipo_sesion"]["fuente"], "config_persistida")
        self.assertEqual(set(session["equipo_sesion"]["opcionales_activos"]), {"cto"})
        self.assertTrue(session["equipo_sesion"]["opcionales_activos"]["cto"])
        self.assertTrue(session["equipo_sesion"]["infra"]["memoria"])

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
                    "agentes_opcionales:\n"
                    "  cto: true\n"
                    "---\n"
                )

            session = run_flow(
                "ship",
                "Release 2.1.0",
                equipo_sesion={"bad": True},
                project_dir=tmpdir,
            )

        self.assertEqual(session["equipo_sesion"]["fuente"], "config_persistida")
        self.assertTrue(session["equipo_sesion"]["opcionales_activos"]["cto"])
        self.assertIsNotNone(session["equipo_sesion_error"])
        self.assertIn("Применена сохранённая конфигурация", session["equipo_sesion_error"])

    def test_quick_flow_uses_optional_agents_on_light_phases(self):
        """quick includes CTO only in validacion_rapida."""
        opcionales = {
            **VALID_EQUIPO_SESION["opcionales_activos"],
            "cto": True,
        }
        ejecucion = get_effective_agents("ejecucion_acotada", opcionales)
        validacion = get_effective_agents("validacion_rapida", opcionales)
        self.assertEqual(ejecucion["paralelo"], [])
        self.assertEqual(ejecucion["secuencial"], [])
        self.assertIn("cto", validacion["secuencial"])

    def test_fix_flow_uses_optional_agents_on_bug_phases(self):
        """fix includes CTO only in validacion."""
        opcionales = {
            **VALID_EQUIPO_SESION["opcionales_activos"],
            "cto": True,
        }
        diagnostico = get_effective_agents("diagnostico", opcionales)
        correccion = get_effective_agents("correccion", opcionales)
        validacion = get_effective_agents("validacion", opcionales)

        self.assertEqual(diagnostico["paralelo"], [])
        self.assertEqual(diagnostico["secuencial"], [])
        self.assertEqual(correccion["paralelo"], [])
        self.assertEqual(correccion["secuencial"], [])
        self.assertIn("cto", validacion["secuencial"])

    def test_unknown_optional_flags_are_ignored_by_effective_agents(self):
        """Removed optional agents do not come back even if the state has them."""
        opcionales = {
            "cto": True,
            "copywriter": True,
            "github-manager": True,
        }
        calidad = get_effective_agents("calidad", opcionales)
        documentacion = get_effective_agents("documentacion", opcionales)
        empaquetado = get_effective_agents("empaquetado", opcionales)
        self.assertEqual(calidad["secuencial"], ["cto"])
        self.assertEqual(documentacion["paralelo"], [])
        self.assertEqual(empaquetado["secuencial"], [])

    def test_cto_runs_as_external_audit_in_quality_closures(self):
        """CTO joins the closing phases as a sequential external audit."""
        opcionales = {
            **VALID_EQUIPO_SESION["opcionales_activos"],
            "cto": True,
        }
        calidad = get_effective_agents("calidad", opcionales)
        auditoria = get_effective_agents("auditoria_final", opcionales)
        self.assertIn("cto", calidad["secuencial"])
        self.assertIn("cto", auditoria["secuencial"])

    def test_ship_and_audit_use_release_optional_agents(self):
        """ship and audit include CTO in the audit phases."""
        opcionales = {
            **VALID_EQUIPO_SESION["opcionales_activos"],
            "cto": True,
        }
        auditoria_final = get_effective_agents("auditoria_final", opcionales)
        documentacion = get_effective_agents("documentacion", opcionales)
        empaquetado = get_effective_agents("empaquetado", opcionales)
        despliegue = get_effective_agents("despliegue", opcionales)
        auditoria_paralela = get_effective_agents("auditoria_paralela", opcionales)

        self.assertIn("cto", auditoria_final["secuencial"])
        self.assertEqual(documentacion["paralelo"], [])
        self.assertEqual(empaquetado["secuencial"], [])
        self.assertEqual(despliegue["secuencial"], [])
        self.assertIn("cto", auditoria_paralela["secuencial"])


class TestIterativeLoop(unittest.TestCase):
    """Tests for the iterative loop inside phases (v0.4.0)."""

    def test_should_retry_when_gate_fails(self):
        """If the gate fails and iterations remain, recommend a retry."""
        session = create_session("feature", "Test loop")
        # Phase 0 = producto, gate_tipo = usuario
        result = should_retry_phase(session, resultado="rechazado")
        self.assertEqual(result["action"], "retry")
        self.assertEqual(result["iteration"], 1)

    def test_should_advance_when_gate_passes(self):
        """If the gate passes, recommend to advance."""
        session = create_session("feature", "Test loop")
        result = should_retry_phase(session, resultado="aprobado")
        self.assertEqual(result["action"], "advance")

    def test_should_escalate_after_max_iterations(self):
        """When iterations run out, recommend escalation to the user."""
        session = create_session("feature", "Test loop")
        session["iteraciones_fase"] = MAX_PHASE_ITERATIONS
        result = should_retry_phase(session, resultado="rechazado")
        self.assertEqual(result["action"], "escalate")

    def test_iteration_counter_increments(self):
        """The iteration counter increments with each retry."""
        session = create_session("feature", "Test loop")
        session["iteraciones_fase"] = 0
        should_retry_phase(session, resultado="rechazado")
        self.assertEqual(session["iteraciones_fase"], 1)
        should_retry_phase(session, resultado="rechazado")
        self.assertEqual(session["iteraciones_fase"], 2)

    def test_reset_phase_iterations(self):
        """The reset sets the counter to 0."""
        session = create_session("feature", "Test loop")
        session["iteraciones_fase"] = 3
        reset_phase_iterations(session)
        self.assertEqual(session["iteraciones_fase"], 0)

    def test_advance_phase_resets_iterations(self):
        """Advancing the phase resets the counter automatically."""
        session = create_session("feature", "Test loop")
        session["iteraciones_fase"] = 3
        session = advance_phase(session, resultado="aprobado")
        self.assertEqual(session.get("iteraciones_fase", 0), 0)

    def test_advance_phase_preserves_iterations(self):
        """advance_phase stores the iteration counter in the completed phase."""
        session = create_session("feature", "Test iterations")
        session["iteraciones_fase"] = 3
        session = advance_phase(session, resultado="aprobado")
        fase_completada = session["fases_completadas"][-1]
        self.assertEqual(fase_completada["iteraciones"], 3)

    def test_should_retry_invalid_session_state_escalates_instead_of_retrying(self):
        session = create_session("feature", "Test loop")
        session["fase_numero"] = -1
        result = should_retry_phase(session, resultado="rechazado")
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
                    "agentes_opcionales:\n"
                    "  cto: true\n"
                    "---\n"
                )

            session = run_flow_autopilot("ship", "Automatic release", project_dir=tmpdir)

        self.assertTrue(session["autopilot"])
        self.assertEqual(session["equipo_sesion"]["fuente"], "config_persistida")
        self.assertTrue(session["equipo_sesion"]["opcionales_activos"]["cto"])
        self.assertEqual(session["iteraciones_fase"], 0)
        self.assertEqual(session["max_iteraciones_fase"], MAX_PHASE_ITERATIONS)

    def test_autopilot_approves_user_gates(self):
        """In autopilot, user gates are approved automatically."""
        session = create_session("feature", "Test autopilot")
        # Phase 0 = producto, gate_tipo = usuario
        result = is_autopilot_gate_passable(session)
        self.assertTrue(result["passed"])
        self.assertIn("autopilot", result["reason"])

    def test_autopilot_evaluates_automatic_gates(self):
        """In autopilot, automatic gates are evaluated normally."""
        session = create_session("feature", "Test autopilot")
        # Advance to phase 3 = desarrollo, gate_tipo = automatico
        session = advance_phase(session, resultado="aprobado")  # producto -> estilo_visual
        session = advance_phase(session, resultado="aprobado")  # estilo_visual -> arquitectura
        session = advance_phase(session, resultado="aprobado")  # arquitectura -> desarrollo
        result = is_autopilot_gate_passable(session, tests_ok=False)
        self.assertFalse(result["passed"])

    def test_autopilot_evaluates_security_gates(self):
        """In autopilot, security gates are evaluated normally."""
        session = create_session("feature", "Test autopilot")
        session = advance_phase(session, resultado="aprobado")  # producto -> estilo_visual
        session = advance_phase(session, resultado="aprobado")  # estilo_visual -> arquitectura
        session = advance_phase(session, resultado="aprobado")  # arquitectura -> desarrollo
        session = advance_phase(session, resultado="aprobado", tests_ok=True)  # desarrollo -> calidad
        # Phase 4 = calidad, gate_tipo = automatico+seguridad
        result = is_autopilot_gate_passable(session, security_ok=False)
        self.assertFalse(result["passed"])

    def test_autopilot_invalid_command(self):
        """Autopilot with an invalid command raises ValueError."""
        with self.assertRaises(ValueError):
            run_flow_autopilot("nonexistent", "Test")

    def test_autopilot_gate_completed_session(self):
        """is_autopilot_gate_passable does not fail with a completed session."""
        session = create_session("spike", "Test")
        session = advance_phase(session, resultado="aprobado")
        session = advance_phase(session, resultado="aprobado")
        # Now fase_actual == "completado"
        result = is_autopilot_gate_passable(session)
        self.assertTrue(result["passed"])

    def test_autopilot_usuario_seguridad_auto_approves_user_part(self):
        """In autopilot, GATE_USUARIO_SEGURIDAD approves the user part
        but evaluates the security part. This test documents the behavior."""
        session = create_session("feature", "Test autopilot")
        session = advance_phase(session, resultado="aprobado")  # producto -> estilo_visual
        session = advance_phase(session, resultado="aprobado")  # estilo_visual -> arquitectura
        # Now in the arquitectura phase with the GATE_USUARIO_SEGURIDAD gate
        # With security OK: must pass
        result = is_autopilot_gate_passable(session, security_ok=True)
        self.assertTrue(result["passed"])
        # With security KO: must fail
        result = is_autopilot_gate_passable(session, security_ok=False)
        self.assertFalse(result["passed"])

    def test_autopilot_ship_deploy_keeps_user_confirmation_mandatory(self):
        session = create_session("ship", "Release autopilot")
        session = advance_phase(session, resultado="aprobado", tests_ok=True, security_ok=True)
        session = advance_phase(session, resultado="aprobado")
        session = advance_phase(session, resultado="aprobado", tests_ok=True, security_ok=True)

        self.assertEqual(session["fase_actual"], "despliegue")
        result = is_autopilot_gate_passable(session, security_ok=True)
        self.assertFalse(result["passed"])
        self.assertIn("явного подтверждения пользователя", result["reason"])


class TestCompletedSessionGuards(unittest.TestCase):
    """Verify that check_gate does not raise IndexError with completed sessions."""

    def test_check_gate_completed_session(self):
        """check_gate returns passed=True for completed sessions."""
        session = create_session("spike", "Research")
        session = advance_phase(session, resultado="aprobado")
        session = advance_phase(session, resultado="aprobado")
        self.assertEqual(session["fase_actual"], "completado")
        result = check_gate(session, resultado="aprobado")
        self.assertTrue(result["passed"])

    def test_check_gate_overflowed_fase_numero(self):
        """An out-of-range index must be rejected as an invalid state."""
        session = create_session("spike", "Test")
        session["fase_numero"] = 999
        result = check_gate(session, resultado="aprobado")
        self.assertFalse(result["passed"])
        self.assertIn("вне диапазона", result["reason"])

    def test_check_gate_negative_fase_numero_is_invalid(self):
        session = create_session("feature", "Test")
        session["fase_numero"] = -1
        result = check_gate(session, resultado="aprobado")
        self.assertFalse(result["passed"])
        self.assertIn("отрицательным", result["reason"])

    def test_advance_phase_rejects_invalid_phase_index(self):
        session = create_session("feature", "Test")
        session["fase_numero"] = -1
        with self.assertRaises(RuntimeError):
            advance_phase(session, resultado="aprobado")


class TestLoadStateValidation(unittest.TestCase):
    def test_load_state_rejects_negative_phase_index(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            state_path = f.name
        try:
            with open(state_path, "w", encoding="utf-8") as fh:
                json.dump(
                    {
                        "comando": "feature",
                        "fase_actual": "producto",
                        "fase_numero": -1,
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
                        "comando": "feature",
                        "fase_actual": "producto",
                        "fase_numero": 3,
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
                        "comando": "spike",
                        "fase_actual": "completado",
                        "fase_numero": len(FLOWS["spike"]["fases"]),
                    },
                    fh,
                )
            loaded = load_state(state_path)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded["fase_actual"], "completado")
        finally:
            os.unlink(state_path)


if __name__ == "__main__":
    unittest.main()
