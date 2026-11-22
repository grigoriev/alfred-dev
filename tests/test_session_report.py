#!/usr/bin/env python3
"""Tests for the session report generator."""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.session_report import (
    generate_report,
    _section_phases,
    _section_evidence,
    _section_team,
    _section_artifacts,
    _section_mode,
    _section_iterations,
    _estimate_duration,
)


class TestSectionPhases(unittest.TestCase):
    """Check the generation of the phases section."""

    def test_no_phases(self):
        session = {"completed_phases": []}
        result = _section_phases(session)
        self.assertIn("не завершено ни одной фазы", result)

    def test_with_phases(self):
        session = {
            "completed_phases": [
                {"name": "product", "result": "approved", "artifacts": ["prd.md"]},
                {"name": "architecture", "result": "approved", "artifacts": []},
            ],
            "current_phase": "development",
        }
        result = _section_phases(session)
        self.assertIn("product", result)
        self.assertIn("architecture", result)
        self.assertIn("prd.md", result)
        self.assertIn("остановлен в фазе **development**", result)

    def test_completed_flow(self):
        session = {
            "completed_phases": [{"name": "single", "result": "approved"}],
            "current_phase": "completed",
        }
        result = _section_phases(session)
        self.assertIn("процесс завершён", result)

    def test_escapes_markdown_table_cells(self):
        session = {
            "completed_phases": [
                {
                    "name": "product | visual\nfinal",
                    "result": "approved\nwith caveat",
                    "artifacts": ["docs/style|direction.md", "docs/\nbrief.md"],
                }
            ],
            "current_phase": "development",
        }
        result = _section_phases(session)
        self.assertIn("product \\| visual final", result)
        self.assertIn("approved with caveat", result)
        self.assertIn("docs/style\\|direction.md, docs/ brief.md", result)


class TestSectionEvidence(unittest.TestCase):
    """Check the generation of the evidence section."""

    def test_no_evidence_data(self):
        result = _section_evidence(None)
        self.assertEqual(result, "")

    def test_no_tests_run(self):
        evidence = {"has_evidence": False, "records": []}
        result = _section_evidence(evidence)
        self.assertIn("тесты не запускались", result)

    def test_with_evidence(self):
        evidence = {
            "has_evidence": True,
            "all_passing": True,
            "count": 2,
            "records": [
                {"timestamp": "2026-03-13T10:00:00+00:00", "command": "pytest -v", "result": "pass"},
                {"timestamp": "2026-03-13T10:05:00+00:00", "command": "pytest -v", "result": "pass"},
            ],
        }
        result = _section_evidence(evidence)
        self.assertIn("Прогонов тестов: **2**", result)
        self.assertIn("все зелёные", result)

    def test_with_failures(self):
        evidence = {
            "has_evidence": True,
            "all_passing": False,
            "count": 1,
            "records": [
                {"timestamp": "2026-03-13T10:00:00+00:00", "command": "pytest", "result": "fail"},
            ],
        }
        result = _section_evidence(evidence)
        self.assertIn("есть ошибки", result)
        self.assertIn("ОШИБКА", result)

    def test_normalizes_commands_for_table(self):
        evidence = {
            "has_evidence": True,
            "all_passing": False,
            "records": [
                {
                    "timestamp": "2026-03-13T10:00:00+00:00",
                    "command": "pytest -k `login | signup`\n-v",
                    "result": "fail",
                }
            ],
        }
        result = _section_evidence(evidence)
        self.assertIn("`pytest -k 'login \\| signup' -v`", result)


class TestSectionTeam(unittest.TestCase):
    """Check the generation of the team section."""

    def test_no_team(self):
        session = {}
        result = _section_team(session)
        self.assertEqual(result, "")

    def test_with_optionals(self):
        session = {
            "command": "fix",
            "session_team": {
                "source": "persisted_config",
                "active_optionals": {
                    "data-engineer": True,
                    "github-manager": True,
                    "librarian": True,
                    "ux-reviewer": False,
                    "performance-engineer": True,
                },
            },
        }
        result = _section_team(session)
        self.assertIn("Источник runtime: **сохранённая конфигурация**.", result)
        self.assertIn("data-engineer", result)
        self.assertIn("github-manager", result)
        self.assertIn("librarian", result)
        self.assertIn("performance-engineer", result)
        self.assertNotIn("ux-reviewer", result)
        self.assertIn("Опциональные агенты только по запросу в этом процессе:", result)
        self.assertIn("- github-manager", result)
        self.assertIn("- librarian", result)


class TestSectionArtifacts(unittest.TestCase):
    """Check the generation of the artifacts section."""

    def test_no_artifacts(self):
        result = _section_artifacts({"artifacts": []})
        self.assertEqual(result, "")

    def test_with_artifacts(self):
        result = _section_artifacts({"artifacts": ["prd.md", "adr-001.md"]})
        self.assertIn("prd.md", result)
        self.assertIn("adr-001.md", result)

    def test_normalizes_artifact_paths(self):
        result = _section_artifacts({"artifacts": ["docs/\nstyle`direction`.md"]})
        self.assertIn("`docs/ style'direction'.md`", result)


class TestEstimateDuration(unittest.TestCase):
    """Check the duration estimate."""

    def test_missing_timestamps(self):
        result = _estimate_duration({})
        self.assertEqual(result, "нет данных")

    def test_short_duration(self):
        session = {
            "created_at": "2026-03-13T10:00:00+00:00",
            "updated_at": "2026-03-13T10:00:30+00:00",
        }
        result = _estimate_duration(session)
        self.assertIn("30 сек.", result)

    def test_minutes_duration(self):
        session = {
            "created_at": "2026-03-13T10:00:00+00:00",
            "updated_at": "2026-03-13T10:15:00+00:00",
        }
        result = _estimate_duration(session)
        self.assertIn("15 мин.", result)

    def test_hours_duration(self):
        session = {
            "created_at": "2026-03-13T10:00:00+00:00",
            "updated_at": "2026-03-13T12:30:00+00:00",
        }
        result = _estimate_duration(session)
        self.assertIn("2 ч 30 мин.", result)

    def test_negative_duration_returns_unavailable(self):
        session = {
            "created_at": "2026-03-13T10:05:00+00:00",
            "updated_at": "2026-03-13T10:00:00+00:00",
        }
        result = _estimate_duration(session)
        self.assertEqual(result, "нет данных")


class TestGenerateReport(unittest.TestCase):
    """Check the full report generation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_generates_file(self):
        session = {
            "command": "feature",
            "description": "Login with OAuth",
            "current_phase": "completed",
            "completed_phases": [
                {"name": "product", "result": "approved"},
            ],
            "artifacts": ["prd.md"],
            "created_at": "2026-03-13T10:00:00+00:00",
            "updated_at": "2026-03-13T10:30:00+00:00",
        }
        report_path = generate_report(session, project_dir=self.tmpdir)
        self.assertTrue(os.path.isfile(report_path))

        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("feature", content)
        self.assertIn("Login with OAuth", content)
        self.assertIn("product", content)
        self.assertIn("prd.md", content)

    def test_report_in_correct_directory(self):
        session = {
            "command": "fix",
            "description": "Critical bug",
            "current_phase": "completed",
            "completed_phases": [],
            "artifacts": [],
            "created_at": "2026-03-13T10:00:00+00:00",
            "updated_at": "2026-03-13T10:05:00+00:00",
        }
        report_path = generate_report(session, project_dir=self.tmpdir)
        self.assertIn("docs/alfred-reports", report_path)
        self.assertTrue(report_path.endswith("-fix.md"))


class TestFilenameSanitization(unittest.TestCase):
    """Check that the command name is sanitized in the file name."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_path_traversal_sanitized(self):
        """A command with path traversal characters does not escape the directory."""
        session = {
            "command": "../../etc/passwd",
            "description": "Path traversal attempt",
            "current_phase": "completed",
            "completed_phases": [],
            "artifacts": [],
            "created_at": "2026-03-13T10:00:00+00:00",
            "updated_at": "2026-03-13T10:05:00+00:00",
        }
        report_path = generate_report(session, project_dir=self.tmpdir)
        # The file must be inside docs/alfred-reports/
        self.assertIn("docs/alfred-reports", report_path)
        # The file name must not contain ".."
        filename = os.path.basename(report_path)
        self.assertNotIn("..", filename)
        self.assertTrue(os.path.isfile(report_path))

    def test_special_chars_sanitized(self):
        """Special characters in the command are replaced with _."""
        session = {
            "command": "feat/login & rm -rf",
            "description": "Command with odd chars",
            "current_phase": "completed",
            "completed_phases": [],
            "artifacts": [],
            "created_at": "2026-03-13T10:00:00+00:00",
            "updated_at": "2026-03-13T10:05:00+00:00",
        }
        report_path = generate_report(session, project_dir=self.tmpdir)
        filename = os.path.basename(report_path)
        self.assertNotIn("/", filename)
        self.assertNotIn("&", filename)
        self.assertTrue(os.path.isfile(report_path))


class TestSectionMode(unittest.TestCase):
    """Check the session mode section."""

    def test_autopilot(self):
        session = {"autopilot": True}
        result = _section_mode(session)
        self.assertIn("autopilot", result.lower())

    def test_interactive(self):
        session = {}
        result = _section_mode(session)
        self.assertIn("интерактивный", result.lower())


class TestSectionIterations(unittest.TestCase):
    """Check the iterations-per-phase section."""

    def test_with_iterations(self):
        session = {
            "completed_phases": [
                {"name": "product", "result": "approved", "iterations": 0},
                {"name": "development", "result": "approved", "iterations": 3},
            ],
        }
        result = _section_iterations(session)
        self.assertIn("development", result)
        self.assertIn("3", result)

    def test_without_iterations(self):
        session = {
            "completed_phases": [
                {"name": "product", "result": "approved", "iterations": 0},
            ],
        }
        result = _section_iterations(session)
        self.assertEqual(result, "")

    def test_escapes_phase_names(self):
        session = {
            "completed_phases": [
                {"name": "quality | uat\nfinal", "result": "approved", "iterations": 2},
            ],
        }
        result = _section_iterations(session)
        self.assertIn("quality \\| uat final", result)


class TestGenerateReportExtended(unittest.TestCase):
    """Tests for the new generate_report features."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dynamic_version_from_plugin_json(self):
        """The report reads the version from plugin.json at runtime."""
        import json as _json
        plugin_path = os.path.join(
            os.path.dirname(__file__), "..", ".claude-plugin", "plugin.json"
        )
        with open(plugin_path) as pf:
            expected_version = _json.load(pf)["version"]

        session = {
            "command": "feature",
            "description": "Test version",
            "current_phase": "completed",
            "completed_phases": [],
            "artifacts": [],
            "created_at": "2026-03-14T10:00:00+00:00",
            "updated_at": "2026-03-14T10:05:00+00:00",
        }
        report_path = generate_report(session, project_dir=self.tmpdir)
        with open(report_path) as f:
            content = f.read()
        self.assertIn(f"Alfred Dev v{expected_version}", content)

    def test_interrupted_report(self):
        session = {
            "command": "feature",
            "description": "Interrupted test",
            "current_phase": "development",
            "completed_phases": [],
            "artifacts": [],
            "created_at": "2026-03-14T10:00:00+00:00",
            "updated_at": "2026-03-14T10:15:00+00:00",
        }
        report_path = generate_report(session, project_dir=self.tmpdir, completed=False)
        with open(report_path) as f:
            content = f.read()
        self.assertIn("прервана", content.lower())
        self.assertIn("## Краткое резюме", content)
        self.assertIn("Команда: `/alfred-dev:resume`", content)

    def test_header_fields_are_single_line(self):
        session = {
            "command": "feature\nwith noise",
            "description": "Line 1\n\nLine 2",
            "current_phase": "completed",
            "completed_phases": [],
            "artifacts": [],
            "created_at": "2026-03-14T10:00:00+00:00",
            "updated_at": "2026-03-14T10:15:00+00:00",
        }
        report_path = generate_report(session, project_dir=self.tmpdir)
        with open(report_path, encoding="utf-8") as f:
            content = f.read()
        self.assertIn("# Отчёт о сессии: feature with noise", content)
        self.assertIn("**Описание:** Line 1 Line 2", content)

    def test_filenames_do_not_collide_within_same_second(self):
        class SequencedDateTime(datetime):
            _values = [
                datetime(2026, 3, 14, 10, 0, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 14, 10, 0, 0, 111111, tzinfo=timezone.utc),
                datetime(2026, 3, 14, 10, 0, 0, 0, tzinfo=timezone.utc),
                datetime(2026, 3, 14, 10, 0, 0, 222222, tzinfo=timezone.utc),
            ]

            @classmethod
            def now(cls, tz=None):
                value = cls._values.pop(0)
                return value if tz is None else value.astimezone(tz)

        session = {
            "command": "feature",
            "description": "collision",
            "current_phase": "completed",
            "completed_phases": [],
            "artifacts": [],
            "created_at": "2026-03-14T10:00:00+00:00",
            "updated_at": "2026-03-14T10:15:00+00:00",
        }
        with patch("core.session_report.datetime", SequencedDateTime):
            report_a = generate_report(session, project_dir=self.tmpdir)
            report_b = generate_report(session, project_dir=self.tmpdir)

        self.assertNotEqual(report_a, report_b)
        self.assertTrue(os.path.isfile(report_a))
        self.assertTrue(os.path.isfile(report_b))

    def test_completed_report_without_uat_recommends_verify(self):
        session = {
            "command": "feature",
            "description": "Login with OAuth",
            "current_phase": "completed",
            "completed_phases": [
                {
                    "name": "product",
                    "result": "approved",
                    "iterations": 1,
                    "completed_at": "2026-03-14T10:10:00+00:00",
                },
                {
                    "name": "visual_style",
                    "result": "skipped",
                    "iterations": 0,
                    "completed_at": "2026-03-14T10:12:00+00:00",
                },
            ],
            "artifacts": ["prd.md", "docs/style-direction.md"],
            "created_at": "2026-03-14T10:00:00+00:00",
            "updated_at": "2026-03-14T10:15:00+00:00",
        }
        report_path = generate_report(session, project_dir=self.tmpdir)
        with open(report_path, encoding="utf-8") as f:
            content = f.read()

        self.assertIn("- Общее состояние: процесс завершён по состоянию.", content)
        self.assertIn("- Зарегистрировано фаз: 2 (пропущено: 1, с повторами: 1).", content)
        self.assertIn("- Тесты: нет данных о прогонах.", content)
        self.assertIn("- Проверка/UAT: в ожидании.", content)
        self.assertIn("Команда: `/alfred-dev:uat`", content)

    def test_completed_report_reflects_approved_uat(self):
        os.makedirs(os.path.join(self.tmpdir, ".claude"), exist_ok=True)
        session = {
            "command": "feature",
            "description": "Login with OAuth",
            "current_phase": "completed",
            "completed_phases": [
                {
                    "name": "quality",
                    "result": "approved",
                    "completed_at": "2026-03-14T10:15:00+00:00",
                },
            ],
            "artifacts": ["prd.md"],
            "created_at": "2026-03-14T10:00:00+00:00",
            "updated_at": "2026-03-14T10:15:00+00:00",
        }
        uat = {
            "target_id": "session:feature:2026-03-14T10:15:00+00:00",
            "status": "approved",
            "updated_at": "2026-03-14T10:20:00+00:00",
            "notes": "Smoke final OK",
        }
        with open(
            os.path.join(self.tmpdir, ".claude", "alfred-uat.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(uat, f)

        report_path = generate_report(session, project_dir=self.tmpdir)
        with open(report_path, encoding="utf-8") as f:
            content = f.read()

        self.assertIn("- Проверка/UAT: одобрена. UAT одобрена. Зарегистрирована 2026-03-14T10:20:00+00:00.", content)
        self.assertIn("- Фокус: Продолжить после закрытия процесса", content)
        self.assertIn("- Источник: закрытие сессии (`report`)", content)
        self.assertIn("Команда: `/alfred`", content)

    def test_completed_report_reflects_rejected_uat(self):
        os.makedirs(os.path.join(self.tmpdir, ".claude"), exist_ok=True)
        session = {
            "command": "fix",
            "description": "Fix checkout",
            "current_phase": "completed",
            "completed_phases": [
                {
                    "name": "quality",
                    "result": "approved",
                    "completed_at": "2026-03-14T10:25:00+00:00",
                },
            ],
            "artifacts": [],
            "created_at": "2026-03-14T10:00:00+00:00",
            "updated_at": "2026-03-14T10:25:00+00:00",
        }
        uat = {
            "target_id": "session:fix:2026-03-14T10:25:00+00:00",
            "status": "rejected",
            "updated_at": "2026-03-14T10:30:00+00:00",
            "notes": "The coupon edge case still fails",
        }
        with open(
            os.path.join(self.tmpdir, ".claude", "alfred-uat.json"), "w", encoding="utf-8"
        ) as f:
            json.dump(uat, f)

        report_path = generate_report(session, project_dir=self.tmpdir)
        with open(report_path, encoding="utf-8") as f:
            content = f.read()

        self.assertIn("- Проверка/UAT: отклонена. UAT отклонена. The coupon edge case still fails", content)
        self.assertIn("- Фокус: Продолжить после закрытия процесса", content)
        self.assertIn("Команда: `/alfred`", content)

    def test_interrupted_report_uses_structured_resume_guidance(self):
        session = {
            "command": "feature",
            "description": "New checkout",
            "current_phase": "architecture",
            "completed_phases": [],
            "artifacts": [],
            "created_at": "2026-03-14T10:00:00+00:00",
            "updated_at": "2026-03-14T10:05:00+00:00",
        }

        report_path = generate_report(session, project_dir=self.tmpdir, completed=False)
        with open(report_path, encoding="utf-8") as f:
            content = f.read()

        self.assertIn("- Фокус: Продолжить текущую сессию", content)
        self.assertIn("- Источник: активная сессия (`state`)", content)
        self.assertIn("Команда: `/alfred-dev:resume`", content)
        self.assertIn("Что делать сейчас: Продолжи сессию с места остановки", content)

    def test_completed_report_includes_matching_memory_decisions(self):
        from core.memory import MemoryDB

        os.makedirs(os.path.join(self.tmpdir, ".claude"), exist_ok=True)
        db = MemoryDB(os.path.join(self.tmpdir, ".claude", "alfred-memory.db"))
        other_iteration = db.start_iteration("feature", "Another initiative")
        db.log_decision(
            title="Do not mix this decision",
            chosen="Must not appear",
            rationale="Belongs to another session",
            iteration_id=other_iteration,
            phase="product",
        )
        db.complete_iteration(other_iteration)

        iteration_id = db.start_iteration("feature", "Login with OAuth")
        db.log_decision(
            title="Use the existing OAuth provider",
            chosen="Reuse the corporate provider",
            rationale="Reduces risk and speeds up release",
            iteration_id=iteration_id,
            phase="architecture",
        )
        db.log_decision(
            title="Close the old visual fallback",
            chosen="Remove the legacy login button",
            rationale="Avoids dead paths in the UI",
            iteration_id=iteration_id,
            phase="development",
        )
        db.complete_iteration(iteration_id)
        db.close()

        session = {
            "command": "feature",
            "description": "Login with OAuth",
            "current_phase": "completed",
            "completed_phases": [
                {
                    "name": "quality",
                    "result": "approved",
                    "completed_at": "2026-03-14T10:25:00+00:00",
                },
            ],
            "artifacts": ["prd.md"],
            "created_at": "2026-03-14T10:00:00+00:00",
            "updated_at": "2026-03-14T10:25:00+00:00",
        }

        report_path = generate_report(session, project_dir=self.tmpdir)
        with open(report_path, encoding="utf-8") as f:
            content = f.read()

        self.assertIn("- Решений в памяти, связанных с сессией: 2.", content)
        self.assertIn("## Ключевые решения", content)
        self.assertIn("Use the existing OAuth provider", content)
        self.assertIn("Reuse the corporate provider", content)
        self.assertIn("Close the old visual fallback", content)
        self.assertNotIn("Do not mix this decision", content)


if __name__ == "__main__":
    unittest.main()
