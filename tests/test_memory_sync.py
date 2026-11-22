#!/usr/bin/env python3
"""
Tests for the sync layer from SQLite to the native Claude Code memory.

Coverage:
- memory_dir resolution.
- Projection of active and archived decisions.
- Generation of the active iteration, commits and summary.
- Management of the delimited section in MEMORY.md.
- Cleanup of orphan files.
- Full end-to-end flow.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.memory import MemoryDB


class TestResolveMemoryDir(unittest.TestCase):
    """Check the resolution of the native memory directory."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        # Simulate the ~/.claude/projects/<hash>/memory/ structure
        self._projects_base = os.path.join(self._tmpdir, "projects")
        self._project_dir = os.path.join(self._tmpdir, "my-project")
        os.makedirs(self._project_dir)

        # Claude Code convention: path with / -> -
        mangled = self._project_dir.replace(os.sep, "-")
        if not mangled.startswith("-"):
            mangled = "-" + mangled
        self._memory_dir = os.path.join(self._projects_base, mangled, "memory")
        os.makedirs(self._memory_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_finds_existing_directory(self):
        """Find the memory directory when it exists."""
        from core.memory_sync import resolve_memory_dir

        result = resolve_memory_dir(self._project_dir, self._projects_base)
        self.assertIsNotNone(result)
        self.assertTrue(result.endswith("memory"))
        self.assertTrue(os.path.isdir(result))

    def test_creates_directory_if_missing(self):
        """Create the memory directory if it does not exist yet."""
        from core.memory_sync import resolve_memory_dir

        base = os.path.join(self._tmpdir, "new-base")
        result = resolve_memory_dir(
            os.path.join(self._tmpdir, "ghost"),
            base,
        )
        self.assertIsNotNone(result)
        self.assertTrue(os.path.isdir(result))
        self.assertTrue(result.endswith("memory"))

    def test_returns_none_if_cannot_create(self):
        """Return None if the directory cannot be created (permissions)."""
        from core.memory_sync import resolve_memory_dir
        from unittest.mock import patch

        with patch("os.makedirs", side_effect=OSError("permission denied")):
            result = resolve_memory_dir(
                os.path.join(self._tmpdir, "ghost"),
                os.path.join(self._tmpdir, "blocked"),
            )
        self.assertIsNone(result)


class SyncTestBase(unittest.TestCase):
    """Base class with a full environment: populated DB + MemorySync."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, ".claude", "alfred-memory.db")
        os.makedirs(os.path.dirname(self._db_path))
        self._memory_dir = os.path.join(self._tmpdir, "memory")
        os.makedirs(self._memory_dir)

        self.db = MemoryDB(self._db_path)
        from core.memory_sync import MemorySync
        self.sync = MemorySync(self.db, self._memory_dir)

        # Create test data
        self.iter_id = self.db.start_iteration(
            command="feature", description="Cache system"
        )
        self.d1_id = self.db.log_decision(
            title="Cache with Redis",
            chosen="Redis for sub-ms latency",
            context="We need a cache to reduce latency",
            alternatives=["Memcached", "In-memory cache"],
            rationale="Redis offers native TTL and optional persistence",
            impact="high",
            phase="arquitectura",
            tags=["cache", "infra"],
            iteration_id=self.iter_id,
        )
        self.d2_id = self.db.log_decision(
            title="Authentication with sessions",
            chosen="Server-side sessions",
            context="Compliance requirements",
            alternatives=["JWT"],
            rationale="Compliance requires immediate revocation",
            impact="critical",
            phase="arquitectura",
            tags=["auth", "security"],
            iteration_id=self.iter_id,
        )

    def tearDown(self):
        self.db.close()
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)


class TestSyncDecisions(SyncTestBase):
    """Check the projection of decisions to .md files."""

    def test_writes_active_decision_file(self):
        """sync_decision writes a file with correct frontmatter."""
        self.sync.sync_decision(self.d1_id)

        path = os.path.join(self._memory_dir, f"alfred-decision-{self.d1_id}.md")
        self.assertTrue(os.path.isfile(path))

        with open(path, "r") as f:
            content = f.read()

        self.assertIn("source: alfred-memory", content)
        self.assertIn(f"source_id: {self.d1_id}", content)
        self.assertIn("Cache with Redis", content)
        self.assertIn("Redis for sub-ms latency", content)
        self.assertIn("Memcached", content)
        self.assertIn("native TTL", content)

    def test_archived_decision_has_no_individual_file(self):
        """A superseded decision does not get an individual file."""
        self.db.update_decision_status(self.d1_id, "superseded")
        self.sync.sync_decision(self.d1_id)

        individual = os.path.join(
            self._memory_dir, f"alfred-decision-{self.d1_id}.md"
        )
        self.assertFalse(os.path.isfile(individual))

        # But it must be in the consolidated archive
        archived = os.path.join(self._memory_dir, "alfred-decisions-archived.md")
        self.assertTrue(os.path.isfile(archived))
        with open(archived, "r") as f:
            content = f.read()
        self.assertIn(f"D#{self.d1_id}", content)
        self.assertIn("superseded", content)

    def test_archived_decision_deletes_previous_file(self):
        """If a decision had a file and is archived, the file is deleted."""
        # First write the file as active
        self.sync.sync_decision(self.d1_id)
        path = os.path.join(self._memory_dir, f"alfred-decision-{self.d1_id}.md")
        self.assertTrue(os.path.isfile(path))

        # Archive and re-sync
        self.db.update_decision_status(self.d1_id, "superseded")
        self.sync.sync_decision(self.d1_id)
        self.assertFalse(os.path.isfile(path))

    def test_frontmatter_collapse_multiline_fields(self):
        """Frontmatter fields are normalized to one line."""
        decision_id = self.db.log_decision(
            title="Line 1\nLine 2",
            chosen='Option\nmultiline with "quotes"',
            rationale="r",
            iteration_id=self.iter_id,
        )

        self.sync.sync_decision(decision_id)

        path = os.path.join(self._memory_dir, f"alfred-decision-{decision_id}.md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn('name: "D#', content)
        self.assertIn('Line 1 Line 2"', content)
        self.assertIn('description: "Option multiline with \\"quotes\\"', content)


class TestSyncAll(SyncTestBase):
    """Check the full sync."""

    def test_writes_all_files(self):
        """sync_all writes the summary, iteration and decisions."""
        result = self.sync.sync_all()

        self.assertEqual(result["errors"], 0)
        self.assertGreater(result["synced"], 0)

        self.assertTrue(os.path.isfile(
            os.path.join(self._memory_dir, "alfred-summary.md")
        ))
        self.assertTrue(os.path.isfile(
            os.path.join(self._memory_dir, "alfred-iteration-active.md")
        ))
        self.assertTrue(os.path.isfile(
            os.path.join(self._memory_dir, f"alfred-decision-{self.d1_id}.md")
        ))
        self.assertTrue(os.path.isfile(
            os.path.join(self._memory_dir, f"alfred-decision-{self.d2_id}.md")
        ))

    def test_summary_contains_statistics(self):
        """The narrative summary includes counters and key decisions."""
        self.sync.sync_all()

        with open(os.path.join(self._memory_dir, "alfred-summary.md"), "r") as f:
            content = f.read()

        self.assertIn("Активных решений в проекте: 2", content)
        self.assertIn("Cache with Redis", content)
        self.assertIn("Authentication with sessions", content)
        self.assertIn("source: alfred-memory", content)

    def test_active_iteration_with_data(self):
        """The active iteration file contains the command and description."""
        self.sync.sync_all()

        with open(
            os.path.join(self._memory_dir, "alfred-iteration-active.md"), "r"
        ) as f:
            content = f.read()

        self.assertIn("feature", content)
        self.assertIn("Cache system", content)
        self.assertIn("source: alfred-memory", content)

    def test_active_iteration_keeps_late_phases_despite_general_limit(self):
        """Completed phases must appear even after a lot of earlier noise."""
        for index in range(120):
            self.db.log_event(
                event_type="command_executed",
                summary=f"cmd {index}",
                iteration_id=self.iter_id,
            )
        self.db.log_event(
            event_type="phase_completed",
            phase="arquitectura",
            payload={
                "fase": "arquitectura",
                "resultado": "aprobado",
                "completada_en": "2026-01-10T10:00:00+00:00",
            },
            iteration_id=self.iter_id,
        )
        self.db.log_event(
            event_type="phase_completed",
            phase="desarrollo",
            payload={
                "fase": "desarrollo",
                "resultado": "aprobado",
                "completada_en": "2026-01-11T10:00:00+00:00",
            },
            iteration_id=self.iter_id,
        )

        self.sync.sync_iteration()

        with open(
            os.path.join(self._memory_dir, "alfred-iteration-active.md"), "r"
        ) as f:
            content = f.read()

        self.assertIn("arquitectura", content)
        self.assertIn("desarrollo", content)
        self.assertIn("после desarrollo", content)

    def test_iteration_escapes_phases_with_pipes_and_newlines(self):
        """Free-form content must not break the phase table."""
        self.db.log_event(
            event_type="phase_completed",
            phase="arquitectura",
            payload={
                "fase": "arquitectura | backend\nprincipal",
                "resultado": "ok | aprobado",
                "completada_en": "2026-01-10T10:00:00+00:00",
            },
            iteration_id=self.iter_id,
        )

        self.sync.sync_iteration()

        with open(
            os.path.join(self._memory_dir, "alfred-iteration-active.md"), "r", encoding="utf-8"
        ) as f:
            content = f.read()

        self.assertIn(r"arquitectura \| backend principal", content)
        self.assertIn(r"ok \| aprobado", content)


class TestUpdateIndex(SyncTestBase):
    """Check the management of MEMORY.md with markers."""

    def test_adds_section_to_existing_memory_md(self):
        """Add the delimited section to a MEMORY.md with earlier content."""
        memory_md = os.path.join(self._memory_dir, "MEMORY.md")
        with open(memory_md, "w") as f:
            f.write("# My project\n\nManual content.\n")

        self.sync.sync_all()

        with open(memory_md, "r") as f:
            content = f.read()

        self.assertIn("Manual content.", content)
        self.assertIn("<!-- ALFRED-SYNC:START -->", content)
        self.assertIn("<!-- ALFRED-SYNC:END -->", content)
        self.assertIn("alfred-summary.md", content)

    def test_second_sync_does_not_duplicate_block(self):
        """Two syncs in a row do not duplicate the markers."""
        self.sync.sync_all()
        self.sync.sync_all()

        memory_md = os.path.join(self._memory_dir, "MEMORY.md")
        with open(memory_md, "r") as f:
            content = f.read()

        self.assertEqual(content.count("<!-- ALFRED-SYNC:START -->"), 1)
        self.assertEqual(content.count("<!-- ALFRED-SYNC:END -->"), 1)

    def test_creates_memory_md_if_missing(self):
        """If MEMORY.md does not exist, create it with the Alfred section."""
        memory_md = os.path.join(self._memory_dir, "MEMORY.md")
        self.assertFalse(os.path.isfile(memory_md))

        self.sync.sync_all()

        self.assertTrue(os.path.isfile(memory_md))
        with open(memory_md, "r") as f:
            content = f.read()
        self.assertIn("<!-- ALFRED-SYNC:START -->", content)

    def test_decision_index_uses_numeric_order(self):
        """Decisions in MEMORY.md must be sorted by real ID."""
        extra_ids = []
        for title in ("D3", "D4", "D5", "D6", "D7", "D8", "D9", "D10"):
            extra_ids.append(
                self.db.log_decision(
                    title=title,
                    chosen="ok",
                    iteration_id=self.iter_id,
                )
            )

        self.sync.sync_all()

        memory_md = os.path.join(self._memory_dir, "MEMORY.md")
        with open(memory_md, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertLess(
            content.index("alfred-decision-2.md"),
            content.index("alfred-decision-10.md"),
        )


class TestCleanupStale(SyncTestBase):
    """Check the cleanup of orphan files."""

    def test_deletes_decision_no_longer_active(self):
        """Files of archived decisions are deleted."""
        self.sync.sync_all()
        path = os.path.join(self._memory_dir, f"alfred-decision-{self.d1_id}.md")
        self.assertTrue(os.path.isfile(path))

        self.db.update_decision_status(self.d1_id, "superseded")
        deleted = self.sync.cleanup_stale()

        self.assertFalse(os.path.isfile(path))
        self.assertEqual(len(deleted), 1)

    def test_does_not_touch_manual_files(self):
        """Files without source: alfred-memory are not deleted."""
        manual = os.path.join(self._memory_dir, "alfred-notes.md")
        with open(manual, "w") as f:
            f.write("My personal notes.\n")

        deleted = self.sync.cleanup_stale()
        self.assertTrue(os.path.isfile(manual))
        self.assertNotIn(manual, deleted)

    def test_deletes_iteration_without_active(self):
        """The iteration file is deleted if there is no active iteration."""
        self.sync.sync_all()
        iter_path = os.path.join(self._memory_dir, "alfred-iteration-active.md")
        self.assertTrue(os.path.isfile(iter_path))

        self.db.complete_iteration(self.iter_id)
        deleted = self.sync.cleanup_stale()

        self.assertFalse(os.path.isfile(iter_path))


class TestCommitsSync(SyncTestBase):
    """Check the projection of commits."""

    def test_writes_commits_file(self):
        """sync_commits writes a table with recent commits."""
        self.db.log_commit(
            sha="abc1234567890",
            message="feat: initial setup",
            author="dev",
            files_changed=3,
        )
        self.sync.sync_commits()

        path = os.path.join(self._memory_dir, "alfred-commits-recent.md")
        self.assertTrue(os.path.isfile(path))

        with open(path, "r") as f:
            content = f.read()

        self.assertIn("abc1234", content)
        self.assertIn("feat: initial setup", content)
        self.assertIn("source: alfred-memory", content)
        self.assertIn(f"I#{self.iter_id}", content)

    def test_no_commits_writes_no_file(self):
        """If there are no commits, no file is written."""
        self.sync.sync_commits()

        path = os.path.join(self._memory_dir, "alfred-commits-recent.md")
        self.assertFalse(os.path.isfile(path))

    def test_commits_sync_marks_imported_history(self):
        """Commits without an iteration must be marked as history."""
        self.db.log_commit(
            sha="historical_sync_sha",
            message="chore: imported history",
            author="repo-bot",
            files=["legacy.txt"],
            files_changed=1,
            auto_link_iteration=False,
        )

        self.sync.sync_commits()

        path = os.path.join(self._memory_dir, "alfred-commits-recent.md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("история", content)
        self.assertIn("включая активный процесс и импортированную историю", content)

    def test_summary_separates_iteration_commits_from_history(self):
        """The summary must not mix imported commits with flow commits."""
        self.db.log_commit(
            sha="linked_sync_sha",
            message="feat: linked work",
            author="dev",
        )
        self.db.log_commit(
            sha="historical_summary_sha",
            message="chore: imported history",
            author="repo-bot",
            auto_link_iteration=False,
        )

        self.sync.sync_summary()

        path = os.path.join(self._memory_dir, "alfred-summary.md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn("Commits, связанных с итерациями: 1 (итераций: 1).", content)
        self.assertIn("Импортированных commits в истории для справки: 1.", content)

    def test_commits_table_escapes_pipes_and_newlines(self):
        """The Markdown table must stay valid with free-form text."""
        self.db.log_commit(
            sha="pipecommit123456",
            message="feat: cache | auth\nline two",
            author="dev | ops\nteam",
            files_changed=2,
        )

        self.sync.sync_commits()

        path = os.path.join(self._memory_dir, "alfred-commits-recent.md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(r"feat: cache \| auth line two", content)
        self.assertIn(r"dev \| ops team", content)

    def test_summary_normalizes_multiline_decision_choice(self):
        """Inner line breaks must not break bullets in the narrative summary."""
        self.db.log_decision(
            title="Multiline decision",
            chosen="First line\nSecond line with detail",
            iteration_id=self.iter_id,
        )

        self.sync.sync_summary()

        path = os.path.join(self._memory_dir, "alfred-summary.md")
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertIn(
            "- **D#3 -- Multiline decision:** First line Second line with detail",
            content,
        )


class TestEdgeCases(unittest.TestCase):
    """Tests for edge cases that the classes above do not cover."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, ".claude", "alfred-memory.db")
        os.makedirs(os.path.dirname(self._db_path))
        self._memory_dir = os.path.join(self._tmpdir, "memory")
        os.makedirs(self._memory_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_sync_all_empty_db(self):
        """sync_all with an empty DB writes no decision files."""
        db = MemoryDB(self._db_path)
        from core.memory_sync import MemorySync
        sync = MemorySync(db, self._memory_dir)

        result = sync.sync_all()
        self.assertEqual(result["errors"], 0)

        # The summary must exist but with 0 decisions
        summary = os.path.join(self._memory_dir, "alfred-summary.md")
        self.assertTrue(os.path.isfile(summary))
        with open(summary, "r") as f:
            content = f.read()
        self.assertIn("Активных решений в проекте: 0", content)

        # There must be no individual decision files
        for entry in os.listdir(self._memory_dir):
            if entry.startswith("alfred-decision-") and entry != "alfred-decisions-archived.md":
                self.fail(f"Unexpected decision file: {entry}")

        db.close()

    def test_start_marker_without_end(self):
        """If MEMORY.md has START without END, clean it and recreate it."""
        db = MemoryDB(self._db_path)
        from core.memory_sync import MemorySync
        sync = MemorySync(db, self._memory_dir)

        memory_md = os.path.join(self._memory_dir, "MEMORY.md")
        with open(memory_md, "w") as f:
            f.write("# Notes\n\n<!-- ALFRED-SYNC:START -->\nBroken content\n")

        sync.sync_all()

        with open(memory_md, "r") as f:
            content = f.read()

        # There must be exactly one pair of valid markers
        self.assertEqual(content.count("<!-- ALFRED-SYNC:START -->"), 1)
        self.assertEqual(content.count("<!-- ALFRED-SYNC:END -->"), 1)
        # The original content must be kept
        self.assertIn("# Notes", content)

        db.close()

    def test_markers_in_reverse_order(self):
        """If the markers are reversed, clean them and recreate them."""
        db = MemoryDB(self._db_path)
        from core.memory_sync import MemorySync
        sync = MemorySync(db, self._memory_dir)

        memory_md = os.path.join(self._memory_dir, "MEMORY.md")
        with open(memory_md, "w") as f:
            f.write(
                "# Notes\n\n"
                "<!-- ALFRED-SYNC:END -->\nGarbage\n"
                "<!-- ALFRED-SYNC:START -->\n"
            )

        sync.sync_all()

        with open(memory_md, "r") as f:
            content = f.read()

        self.assertEqual(content.count("<!-- ALFRED-SYNC:START -->"), 1)
        self.assertEqual(content.count("<!-- ALFRED-SYNC:END -->"), 1)
        # Check that START comes before END
        self.assertLess(
            content.index("<!-- ALFRED-SYNC:START -->"),
            content.index("<!-- ALFRED-SYNC:END -->"),
        )

        db.close()

    def test_decision_with_none_fields(self):
        """Decisions with optional fields set to None do not break the projection."""
        db = MemoryDB(self._db_path)
        from core.memory_sync import MemorySync
        sync = MemorySync(db, self._memory_dir)

        db.start_iteration(command="test", description=None)
        d_id = db.log_decision(
            title="Minimal",
            chosen="Single option",
            # context, alternatives, rationale, impact, phase, tags: all None
        )

        sync.sync_decision(d_id)

        path = os.path.join(self._memory_dir, f"alfred-decision-{d_id}.md")
        self.assertTrue(os.path.isfile(path))
        with open(path, "r") as f:
            content = f.read()
        self.assertIn("Minimal", content)
        self.assertIn("Single option", content)
        self.assertIn("source: alfred-memory", content)

        db.close()

    def test_sync_decision_works_beyond_1000_records(self):
        """sync_decision must fetch a decision outside the first batch."""
        db = MemoryDB(self._db_path)
        from core.memory_sync import MemorySync
        sync = MemorySync(db, self._memory_dir)

        db.start_iteration(command="test", description="volume")
        last_id = None
        for index in range(1005):
            last_id = db.log_decision(
                title=f"Decision {index}",
                chosen=f"Option {index}",
            )

        sync.sync_decision(last_id)

        path = os.path.join(self._memory_dir, f"alfred-decision-{last_id}.md")
        self.assertTrue(os.path.isfile(path))
        with open(path, "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("Decision 1004", content)

        db.close()


class TestE2E(unittest.TestCase):
    """End-to-end test of the full flow."""

    def test_full_flow(self):
        """Create data, sync, archive, re-sync."""
        tmpdir = tempfile.mkdtemp()
        try:
            db_path = os.path.join(tmpdir, ".claude", "alfred-memory.db")
            os.makedirs(os.path.dirname(db_path))
            memory_dir = os.path.join(tmpdir, "memory")
            os.makedirs(memory_dir)

            # Existing MEMORY.md
            memory_md = os.path.join(memory_dir, "MEMORY.md")
            with open(memory_md, "w") as f:
                f.write("# Test project\n\nManual user notes.\n")

            db = MemoryDB(db_path)
            from core.memory_sync import MemorySync
            sync = MemorySync(db, memory_dir)

            # 1. Create an iteration with decisions and a commit
            db.start_iteration(command="feature", description="E2E test")
            d1 = db.log_decision(
                title="Framework web",
                chosen="FastAPI",
                alternatives=["Flask", "Django"],
                rationale="Performance and native typing",
                impact="high",
                phase="arquitectura",
                tags=["backend"],
            )
            d2 = db.log_decision(
                title="Database",
                chosen="PostgreSQL",
                impact="critical",
                phase="arquitectura",
            )
            db.log_commit(
                sha="abc1234567890",
                message="feat: initial setup",
                author="dev",
            )

            # 2. Full sync
            result = sync.sync_all()
            self.assertEqual(result["errors"], 0)

            # 3. Check files
            self.assertTrue(os.path.isfile(
                os.path.join(memory_dir, f"alfred-decision-{d1}.md")
            ))
            self.assertTrue(os.path.isfile(
                os.path.join(memory_dir, f"alfred-decision-{d2}.md")
            ))
            self.assertTrue(os.path.isfile(
                os.path.join(memory_dir, "alfred-summary.md")
            ))
            self.assertTrue(os.path.isfile(
                os.path.join(memory_dir, "alfred-iteration-active.md")
            ))
            self.assertTrue(os.path.isfile(
                os.path.join(memory_dir, "alfred-commits-recent.md")
            ))

            # 4. MEMORY.md keeps manual content
            with open(memory_md, "r") as f:
                index = f.read()
            self.assertIn("Manual user notes.", index)
            self.assertIn("<!-- ALFRED-SYNC:START -->", index)
            self.assertIn("alfred-summary.md", index)

            # 5. Summary with correct data
            with open(os.path.join(memory_dir, "alfred-summary.md"), "r") as f:
                summary = f.read()
            self.assertIn("Активных решений в проекте: 2", summary)
            self.assertIn("Framework web", summary)

            # 6. Archive and re-sync
            db.update_decision_status(d1, "superseded")
            sync.sync_decision(d1)
            sync.sync_summary()
            sync.update_index()

            self.assertFalse(os.path.isfile(
                os.path.join(memory_dir, f"alfred-decision-{d1}.md")
            ))
            archived = os.path.join(memory_dir, "alfred-decisions-archived.md")
            self.assertTrue(os.path.isfile(archived))
            with open(archived, "r") as f:
                arch = f.read()
            self.assertIn("Framework web", arch)
            self.assertIn("superseded", arch)

            # 7. Updated summary
            with open(os.path.join(memory_dir, "alfred-summary.md"), "r") as f:
                summary2 = f.read()
            self.assertIn("Активных решений в проекте: 1", summary2)

            db.close()
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
