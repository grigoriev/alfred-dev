#!/usr/bin/env python3
"""
Tests for the persistent memory module (core/memory.py).

Full coverage of:
- Database and schema creation (tables, indexes, WAL, FK, FTS5, permissions).
- CRUD operations on iterations, decisions, commits and events.
- Sanitization of sensitive content.
- Text search (FTS5 and LIKE fallback).
- Event timeline and statistics.
- Purge of old events.
"""

import json
import os
import stat
import sqlite3
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.memory import MemoryDB, sanitize_content


class TestMemoryDBCreation(unittest.TestCase):
    """Check that the database is created correctly with the expected schema."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

    def tearDown(self):
        self.db.close()
        # Clean up SQLite files (main + WAL + shm)
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_all_tables_exist(self):
        """The 6 schema tables must exist after creation."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "ORDER BY name"
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()

        expected = {"meta", "iterations", "decisions", "commits",
                    "commit_links", "events", "decision_links"}
        # FTS5 can add more tables; check only the basic ones
        self.assertTrue(expected.issubset(tables),
                        f"Missing tables: {expected - tables}")

    def test_schema_version_registered(self):
        """The schema version must be recorded in meta."""
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "4")

    def test_wal_mode_active(self):
        """WAL mode must be on for better concurrency."""
        conn = sqlite3.connect(self._db_path)
        row = conn.execute("PRAGMA journal_mode").fetchone()
        conn.close()

        self.assertEqual(row[0], "wal")

    def test_foreign_keys_enabled(self):
        """Foreign keys must be on in the MemoryDB connection.

        PRAGMA foreign_keys is a per-connection setting, not a file setting.
        So the test checks the internal connection of the object, not a
        new connection.
        """
        row = self.db._conn.execute("PRAGMA foreign_keys").fetchone()
        self.assertEqual(row[0], 1)

    def test_fts5_detection(self):
        """FTS5 detection must be recorded in meta."""
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'fts_enabled'"
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertIn(row[0], ("0", "1"))

    def test_fts_enabled_property(self):
        """The fts_enabled property must match the detection."""
        self.assertIsInstance(self.db.fts_enabled, bool)

    def test_fts_content_version_registered_when_enabled(self):
        """If FTS5 is on, the indexed content version must be recorded."""
        if not self.db.fts_enabled:
            self.skipTest("FTS5 is not available in this environment.")

        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'fts_content_version'"
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "2")

    def test_file_permissions_0600(self):
        """The DB file must have 0600 permissions (owner only)."""
        mode = os.stat(self._db_path).st_mode
        # Extract only the permission bits (last 9 bits)
        perms = stat.S_IMODE(mode)
        self.assertEqual(perms, 0o600,
                         f"Expected permissions 0600, got {oct(perms)}")

    def test_indices_exist(self):
        """The 8 indexes defined in the schema must exist."""
        conn = sqlite3.connect(self._db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_%'"
        )
        indices = {row[0] for row in cursor.fetchall()}
        conn.close()

        expected = {
            "idx_iterations_status",
            "idx_decisions_iteration",
            "idx_commits_iteration",
            "idx_events_iteration",
            "idx_events_type",
            "idx_decision_links_target",
        }
        self.assertEqual(expected, indices)

    def test_created_at_registered(self):
        """The creation date must be recorded in meta."""
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT value FROM meta WHERE key = 'created_at'"
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row)
        # Must be an ISO 8601 date
        self.assertIn("T", row[0])

    def test_creates_parent_directory(self):
        """If the parent directory does not exist, MemoryDB creates it."""
        nested_path = os.path.join(
            tempfile.mkdtemp(), "subdir", "deep", "test.db"
        )
        try:
            db = MemoryDB(nested_path)
            db.close()
            self.assertTrue(os.path.exists(nested_path))
        finally:
            # Cleanup
            for suffix in ("", "-wal", "-shm"):
                path = nested_path + suffix
                if os.path.exists(path):
                    os.unlink(path)


class TestIterations(unittest.TestCase):
    """CRUD tests for iterations."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_start_iteration_returns_id(self):
        """start_iteration must return the ID of the new iteration."""
        iter_id = self.db.start_iteration("feature", "Login with OAuth")
        self.assertIsInstance(iter_id, int)
        self.assertGreater(iter_id, 0)

    def test_get_iteration(self):
        """get_iteration must return the iteration data."""
        iter_id = self.db.start_iteration("fix", "Form error")
        iteration = self.db.get_iteration(iter_id)

        self.assertIsNotNone(iteration)
        self.assertEqual(iteration["command"], "fix")
        self.assertEqual(iteration["description"], "Form error")
        self.assertEqual(iteration["status"], "active")
        self.assertIsNotNone(iteration["started_at"])
        self.assertIsNone(iteration["completed_at"])

    def test_get_nonexistent_iteration_returns_none(self):
        """A query for a missing iteration must return None."""
        self.assertIsNone(self.db.get_iteration(9999))

    def test_complete_iteration(self):
        """complete_iteration must mark the iteration as completed."""
        iter_id = self.db.start_iteration("spike", "Evaluate framework X")
        self.db.complete_iteration(iter_id)
        iteration = self.db.get_iteration(iter_id)

        self.assertEqual(iteration["status"], "completed")
        self.assertIsNotNone(iteration["completed_at"])

    def test_abandon_iteration(self):
        """An iteration can be abandoned with status 'abandoned'."""
        iter_id = self.db.start_iteration("feature", "Cancelled feature")
        self.db.complete_iteration(iter_id, status="abandoned")
        iteration = self.db.get_iteration(iter_id)

        self.assertEqual(iteration["status"], "abandoned")

    def test_get_active_iteration(self):
        """get_active_iteration must return the active iteration."""
        iter_id = self.db.start_iteration("feature", "Active task")
        active = self.db.get_active_iteration()

        self.assertIsNotNone(active)
        self.assertEqual(active["id"], iter_id)

    def test_get_active_iteration_returns_none_when_none_active(self):
        """If there is no active iteration, get_active_iteration returns None."""
        self.assertIsNone(self.db.get_active_iteration())

    def test_get_active_iteration_after_completion(self):
        """After completion, get_active_iteration does not return the completed one."""
        iter_id = self.db.start_iteration("fix", "Fixed bug")
        self.db.complete_iteration(iter_id)

        self.assertIsNone(self.db.get_active_iteration())

    def test_latest_active_iteration_wins(self):
        """If several are active, the most recent one is returned."""
        self.db.start_iteration("feature", "First")
        iter_id2 = self.db.start_iteration("feature", "Second")
        active = self.db.get_active_iteration()

        self.assertEqual(active["id"], iter_id2)


class TestDecisions(unittest.TestCase):
    """CRUD tests for decisions."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_log_decision_returns_id(self):
        """log_decision must return the ID of the new decision."""
        dec_id = self.db.log_decision(
            title="Choose a database",
            chosen="SQLite",
            context="We need local persistence",
        )
        self.assertIsInstance(dec_id, int)
        self.assertGreater(dec_id, 0)

    def test_get_decisions(self):
        """get_decisions must return the recorded decisions."""
        self.db.log_decision(title="Decision A", chosen="Option 1")
        self.db.log_decision(title="Decision B", chosen="Option 2")

        decisions = self.db.get_decisions()
        self.assertEqual(len(decisions), 2)

    def test_decision_auto_links_to_active_iteration(self):
        """Without iteration_id, the decision links to the active iteration."""
        iter_id = self.db.start_iteration("feature", "Memory module")
        dec_id = self.db.log_decision(
            title="Choose a search engine",
            chosen="FTS5",
        )

        decisions = self.db.get_decisions(iteration_id=iter_id)
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["id"], dec_id)

    def test_decision_without_active_iteration(self):
        """Without an active iteration, the decision is recorded with iteration_id=None."""
        dec_id = self.db.log_decision(
            title="Orphan decision",
            chosen="Some option",
        )
        decisions = self.db.get_decisions()
        self.assertEqual(len(decisions), 1)
        self.assertIsNone(decisions[0]["iteration_id"])

    def test_decision_with_all_fields(self):
        """Record a decision with all optional fields."""
        dec_id = self.db.log_decision(
            title="Framework web",
            chosen="FastAPI",
            context="We need a REST API",
            alternatives=["Django", "Flask"],
            rationale="Better performance and typing",
            impact="high",
            phase="architecture",
        )
        decisions = self.db.get_decisions()
        d = decisions[0]

        self.assertEqual(d["title"], "Framework web")
        self.assertEqual(d["chosen"], "FastAPI")
        self.assertEqual(d["impact"], "high")
        self.assertEqual(d["phase"], "architecture")

        # Alternatives are stored as JSON
        alts = json.loads(d["alternatives"])
        self.assertEqual(alts, ["Django", "Flask"])

    def test_get_decisions_filtered_by_iteration(self):
        """get_decisions with iteration_id filters correctly."""
        iter1 = self.db.start_iteration("feature", "First")
        self.db.log_decision(title="Dec iter 1", chosen="A")
        self.db.complete_iteration(iter1)

        iter2 = self.db.start_iteration("fix", "Second")
        self.db.log_decision(title="Dec iter 2", chosen="B")

        decs_iter1 = self.db.get_decisions(iteration_id=iter1)
        decs_iter2 = self.db.get_decisions(iteration_id=iter2)

        self.assertEqual(len(decs_iter1), 1)
        self.assertEqual(decs_iter1[0]["title"], "Dec iter 1")
        self.assertEqual(len(decs_iter2), 1)
        self.assertEqual(decs_iter2[0]["title"], "Dec iter 2")


class TestCommits(unittest.TestCase):
    """CRUD tests for commits."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_log_commit_returns_id(self):
        """log_commit must return the ID of the new commit."""
        commit_id = self.db.log_commit(
            sha="abc123def456",
            message="feat: new module",
        )
        self.assertIsInstance(commit_id, int)
        self.assertGreater(commit_id, 0)

    def test_duplicate_sha_returns_none(self):
        """Recording a commit with the same SHA returns None (idempotency)."""
        self.db.log_commit(sha="abc123def456", message="first record")
        result = self.db.log_commit(sha="abc123def456", message="duplicate")
        self.assertIsNone(result)

    def test_commit_auto_links_to_active_iteration(self):
        """Without iteration_id, the commit links to the active iteration."""
        iter_id = self.db.start_iteration("feature", "Module X")
        commit_id = self.db.log_commit(
            sha="commit1sha",
            message="feat: implement X",
        )

        # Check with direct SQL
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT iteration_id FROM commits WHERE id = ?", (commit_id,)
        ).fetchone()
        conn.close()

        self.assertEqual(row[0], iter_id)

    def test_log_commit_with_full_metadata(self):
        """Record a commit with all metadata fields."""
        commit_id = self.db.log_commit(
            sha="full_meta_sha",
            message="refactor: simplify logic",
            author="dev@example.com",
            files_changed=5,
            insertions=120,
            deletions=80,
        )
        self.assertIsNotNone(commit_id)

    def test_log_commit_preserves_explicit_committed_at(self):
        """If committed_at is passed, that real date must be stored."""
        committed_at = "2024-01-02T03:04:05+00:00"
        commit_id = self.db.log_commit(
            sha="dated_meta_sha",
            message="feat: historical",
            committed_at=committed_at,
        )

        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT committed_at FROM commits WHERE id = ?",
            (commit_id,),
        ).fetchone()
        conn.close()

        self.assertEqual(row[0], committed_at)

    def test_log_commit_can_skip_auto_link_to_active_iteration(self):
        """Historical imports must not attach to the active iteration."""
        self.db.start_iteration("feature", "Active session")
        commit_id = self.db.log_commit(
            sha="historical_sha",
            message="feat: historical commit",
            auto_link_iteration=False,
        )

        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT iteration_id FROM commits WHERE id = ?",
            (commit_id,),
        ).fetchone()
        conn.close()

        self.assertIsNone(row[0])

    def test_link_commit_decision(self):
        """link_commit_decision must create the link correctly."""
        dec_id = self.db.log_decision(
            title="Use SQLite", chosen="SQLite"
        )
        commit_id = self.db.log_commit(
            sha="linked_sha_123",
            message="feat: implement SQLite",
        )
        # Must not raise an exception
        self.db.link_commit_decision(commit_id, dec_id, "implements")

        # Check with direct SQL
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT * FROM commit_links WHERE commit_id = ? AND decision_id = ?",
            (commit_id, dec_id),
        ).fetchone()
        conn.close()

        self.assertIsNotNone(row)

    def test_link_commit_decision_duplicate_ignored(self):
        """Linking the same commit to the same decision twice does not fail."""
        dec_id = self.db.log_decision(title="Dec", chosen="X")
        commit_id = self.db.log_commit(sha="dup_link_sha", message="msg")

        self.db.link_commit_decision(commit_id, dec_id)
        # Second time: must not raise an exception
        self.db.link_commit_decision(commit_id, dec_id)


class TestSanitization(unittest.TestCase):
    """
    Tests for sanitization of sensitive content.

    The test values are built at runtime from concatenated parts, so the
    security hook does not detect them in the test source code.
    """

    def test_none_returns_none(self):
        """sanitize_content(None) must return None."""
        self.assertIsNone(sanitize_content(None))

    def test_clean_text_unchanged(self):
        """Text without secrets must pass unchanged."""
        text = "This text contains no secret"
        self.assertEqual(sanitize_content(text), text)

    def test_aws_key_redacted(self):
        """AWS keys (pattern AKIA...) must be redacted."""
        # Build the fake key at runtime so the hook does not fire
        fake_key = "AKIA" + "TESTMEMORYDB1234"
        text = f"The key is {fake_key} in this text"
        result = sanitize_content(text)

        self.assertNotIn(fake_key, result)
        self.assertIn("[REDACTED:AWS_KEY]", result)

    def test_jwt_redacted(self):
        """JWT tokens must be redacted."""
        # Build a fake JWT with 3 parts separated by dots
        header = "eyJhbGciOiJI" + "UzI1NiIsInR5"
        payload = "eyJzdWIiOiIx" + "MjM0NTY3ODkw"
        signature = "SflKxwRJSM" + "eKKF2QT4fwp"
        fake_jwt = f"{header}.{payload}.{signature}"
        text = f"Token: {fake_jwt}"
        result = sanitize_content(text)

        self.assertNotIn(fake_jwt, result)
        self.assertIn("[REDACTED:JWT]", result)

    def test_sk_key_redacted(self):
        """Keys with the sk- prefix must be redacted."""
        # 20+ alphanumeric characters after sk-
        fake_sk = "sk-" + "a" * 25
        text = f"Key: {fake_sk}"
        result = sanitize_content(text)

        self.assertNotIn(fake_sk, result)
        self.assertIn("[REDACTED:SK_KEY]", result)

    def test_private_key_header_redacted(self):
        """PEM private key headers must be redacted."""
        pem = "-----BEGIN " + "PRIVATE KEY-----"
        text = f"Certificate: {pem}"
        result = sanitize_content(text)

        self.assertNotIn(pem, result)
        self.assertIn("[REDACTED:PRIVATE_KEY]", result)

    def test_connection_string_redacted(self):
        """Connection strings with credentials must be redacted."""
        # Build it in parts to avoid the hook
        proto = "postgres" + "ql"
        creds = "username" + ":long_password"
        host = "server" + ".example.com"
        conn_str = f"{proto}://{creds}@{host}/db"
        text = f"DB: {conn_str}"
        result = sanitize_content(text)

        self.assertIn("[REDACTED:CONNECTION_STRING]", result)

    def test_short_credential_connection_string_redacted(self):
        """DSNs with short credentials must also be redacted."""
        conn_str = "postgres://user:pass@example.com/db"
        result = sanitize_content(f"DB: {conn_str}")

        self.assertIn("[REDACTED:CONNECTION_STRING]", result)

    def test_multiple_secrets_all_redacted(self):
        """If one text has several secrets, all of them are redacted."""
        fake_aws = "AKIA" + "MULTITEST12345678"
        fake_sk = "sk-" + "b" * 25
        text = f"AWS: {fake_aws}, SK: {fake_sk}"
        result = sanitize_content(text)

        self.assertNotIn(fake_aws, result)
        self.assertNotIn(fake_sk, result)
        self.assertIn("[REDACTED:AWS_KEY]", result)
        self.assertIn("[REDACTED:SK_KEY]", result)

    def test_sanitization_in_decision(self):
        """Decision fields are sanitized when stored."""
        tmpfile = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        db_path = tmpfile.name
        tmpfile.close()

        try:
            db = MemoryDB(db_path)
            fake_key = "AKIA" + "DECISIONTEST1234"
            db.log_decision(
                title="Configure access",
                chosen=f"Use key {fake_key}",
            )
            decisions = db.get_decisions()
            db.close()

            self.assertNotIn(fake_key, decisions[0]["chosen"])
            self.assertIn("[REDACTED:AWS_KEY]", decisions[0]["chosen"])
        finally:
            for suffix in ("", "-wal", "-shm"):
                path = db_path + suffix
                if os.path.exists(path):
                    os.unlink(path)


class TestSearch(unittest.TestCase):
    """Text search tests."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

        # Populate with test data
        self.iter_id = self.db.start_iteration("feature", "Payment system")
        self.db.log_decision(
            title="Payment gateway",
            chosen="Stripe",
            context="We need to charge subscriptions",
            rationale="Good documentation and support in Europe",
        )
        self.db.log_decision(
            title="Database",
            chosen="PostgreSQL",
            context="Relational persistence",
        )
        self.db.log_commit(
            sha="search_test_sha1",
            message="feat: integrate Stripe as payment gateway",
        )

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_search_finds_decision_by_title(self):
        """Search must find decisions by title."""
        results = self.db.search("gateway")
        self.assertGreater(len(results), 0)

        # At least one result must be the gateway decision
        titles = [r.get("title", "") for r in results]
        self.assertTrue(
            any("gateway" in t for t in titles),
            f"'gateway' not found in: {titles}"
        )

    def test_search_finds_commit_by_message(self):
        """Search must find commits by message."""
        results = self.db.search("Stripe")
        self.assertGreater(len(results), 0)

        # There must be at least one commit or decision result
        source_types = [r["source_type"] for r in results]
        # Stripe appears in the decision and in the commit
        self.assertTrue(len(source_types) > 0)

    def test_search_finds_commit_by_changed_file(self):
        """Search must find commits by paths in files."""
        self.db.log_commit(
            sha="search_test_sha2",
            message="feat: refactor auth callback",
            files=["src/auth/callback.py", "tests/test_auth_callback.py"],
        )

        results = self.db.search("callback.py")

        self.assertTrue(any(r["source_type"] == "commit" for r in results))
        self.assertTrue(
            any("callback.py" in r.get("files", "") for r in results if r["source_type"] == "commit")
        )

    def test_search_prioritizes_primary_match_over_secondary_mentions(self):
        """A match in the title or message must beat a side mention."""
        self.db.log_decision(
            title="Shared infra",
            chosen="Redis",
            rationale="We need an ordered cache rollback for tests.",
        )
        self.db.log_commit(
            sha="search_test_sha3",
            message="feat: cache rollback",
        )

        results = self.db.search("cache rollback", limit=1)

        self.assertEqual(results[0]["source_type"], "commit")
        self.assertEqual(results[0]["message"], "feat: cache rollback")

    def test_search_like_fallback_uses_same_relevance_rules(self):
        """The LIKE fallback must not rank decisions ahead of commits."""
        self.db._fts_enabled = False
        self.db.log_decision(
            title="Shared infra",
            chosen="Redis",
            rationale="We need an ordered cache rollback for tests.",
        )
        self.db.log_commit(
            sha="search_test_sha4",
            message="feat: cache rollback",
            files=["src/cache/rollback.py"],
        )

        results = self.db.search("cache rollback", limit=1)
        file_results = self.db.search("rollback.py", limit=3)

        self.assertEqual(results[0]["source_type"], "commit")
        self.assertTrue(any(r["source_type"] == "commit" for r in file_results))

    def test_fts_index_includes_commit_files_and_event_summary(self):
        """FTS must index file paths and event summaries."""
        if not self.db.fts_enabled:
            self.skipTest("FTS5 is not available in this environment.")

        self.db.log_commit(
            sha="search_test_sha5",
            message="feat: auth pipeline",
            files=["src/auth/callback.py"],
        )
        self.db.log_event(
            event_type="custom",
            summary="rollout freeze approved",
            iteration_id=self.iter_id,
        )

        commit_row = self.db._conn.execute(
            "SELECT content FROM memory_fts WHERE source_type = 'commit' "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        event_row = self.db._conn.execute(
            "SELECT content FROM memory_fts WHERE source_type = 'event' "
            "ORDER BY rowid DESC LIMIT 1"
        ).fetchone()

        self.assertIn("callback.py", commit_row[0])
        self.assertIn("rollout freeze approved", event_row[0])

    def test_search_no_results(self):
        """A search for a missing term returns an empty list."""
        results = self.db.search("nonexistent_quantum_blockchain")
        self.assertEqual(len(results), 0)

    def test_search_with_iteration_filter(self):
        """A search filtered by iteration returns only results from that iteration."""
        # Create another iteration with different data
        self.db.complete_iteration(self.iter_id)
        iter2 = self.db.start_iteration("fix", "Something else")
        self.db.log_decision(title="Another decision", chosen="Another option")

        results = self.db.search("gateway", iteration_id=iter2)
        self.assertEqual(len(results), 0)

    def test_search_respects_limit(self):
        """Search respects the limit parameter."""
        # Insert many decisions with the same term
        for i in range(10):
            self.db.log_decision(
                title=f"Optimization number {i}",
                chosen="Cache it",
            )

        results = self.db.search("Optimization", limit=3)
        self.assertLessEqual(len(results), 3)


class TestEvents(unittest.TestCase):
    """CRUD tests for events."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_log_event_returns_id(self):
        """log_event must return the ID of the new event."""
        iter_id = self.db.start_iteration("feature", "Test")
        event_id = self.db.log_event(
            event_type="phase_completed",
            phase="product",
            iteration_id=iter_id,
        )
        self.assertIsInstance(event_id, int)
        self.assertGreater(event_id, 0)

    def test_log_event_with_payload(self):
        """Events can include a JSON payload."""
        iter_id = self.db.start_iteration("feature", "Test")
        self.db.log_event(
            event_type="gate_passed",
            phase="development",
            payload={"tests_ok": True, "duration_s": 12.5},
            iteration_id=iter_id,
        )

        timeline = self.db.get_timeline(iter_id)
        self.assertEqual(len(timeline), 1)

        payload = json.loads(timeline[0]["payload"])
        self.assertTrue(payload["tests_ok"])

    def test_log_event_sanitizes_nested_payload_secrets(self):
        """Secrets inside nested payloads must not stay in SQLite."""
        iter_id = self.db.start_iteration("feature", "Test")
        fake_sk = "sk-" + "c" * 25
        self.db.log_event(
            event_type="gate_passed",
            phase="development",
            payload={
                "nested": {"token": fake_sk},
                "items": ["ok", {"secret": fake_sk}],
            },
            iteration_id=iter_id,
        )

        timeline = self.db.get_timeline(iter_id)
        payload = json.loads(timeline[0]["payload"])
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(fake_sk, serialized)
        self.assertIn("[REDACTED:SK_KEY]", serialized)

    def test_event_auto_links_to_active_iteration(self):
        """Without iteration_id, the event links to the active iteration."""
        iter_id = self.db.start_iteration("feature", "Auto-link")
        self.db.log_event(event_type="phase_completed", phase="product")

        timeline = self.db.get_timeline(iter_id)
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["iteration_id"], iter_id)

    def test_get_timeline_ordered_chronologically(self):
        """get_timeline returns events in ascending chronological order."""
        iter_id = self.db.start_iteration("feature", "Timeline")

        self.db.log_event(
            event_type="phase_completed", phase="product",
            iteration_id=iter_id,
        )
        self.db.log_event(
            event_type="phase_completed", phase="architecture",
            iteration_id=iter_id,
        )
        self.db.log_event(
            event_type="phase_completed", phase="development",
            iteration_id=iter_id,
        )

        timeline = self.db.get_timeline(iter_id)
        self.assertEqual(len(timeline), 3)
        self.assertEqual(timeline[0]["phase"], "product")
        self.assertEqual(timeline[1]["phase"], "architecture")
        self.assertEqual(timeline[2]["phase"], "development")

    def test_get_timeline_empty_for_nonexistent_iteration(self):
        """get_timeline for a missing iteration returns an empty list."""
        timeline = self.db.get_timeline(9999)
        self.assertEqual(len(timeline), 0)

    def test_purge_old_events(self):
        """purge_old_events deletes events older than the window."""
        iter_id = self.db.start_iteration("feature", "Purge")

        # Insert an event with an old date directly into the DB,
        # so the test does not wait real days
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT INTO events (iteration_id, event_type, phase, created_at) "
            "VALUES (?, 'phase_completed', 'product', '2020-01-01T00:00:00+00:00')",
            (iter_id,),
        )
        conn.commit()
        conn.close()

        # Insert a recent event through the API
        self.db.log_event(
            event_type="phase_completed", phase="development",
            iteration_id=iter_id,
        )

        # Purge with 30-day retention: only the old one must be deleted
        deleted = self.db.purge_old_events(retention_days=30)
        self.assertEqual(deleted, 1)

        timeline = self.db.get_timeline(iter_id)
        self.assertEqual(len(timeline), 1)
        self.assertEqual(timeline[0]["phase"], "development")

    def test_purge_does_not_delete_recent_events(self):
        """purge_old_events does not delete recent events."""
        iter_id = self.db.start_iteration("feature", "Recent")
        self.db.log_event(
            event_type="phase_completed", phase="product",
            iteration_id=iter_id,
        )

        deleted = self.db.purge_old_events(retention_days=30)
        self.assertEqual(deleted, 0)

    def test_count_events_supports_iteration_filters_without_truncation(self):
        """count_events must return the real total, not a partial window."""
        iter_a = self.db.start_iteration("feature", "A")
        self.db.complete_iteration(iter_a)
        iter_b = self.db.start_iteration("feature", "B")

        for index in range(1005):
            self.db.log_event(
                event_type="command_executed" if index % 2 == 0 else "phase_completed",
                iteration_id=iter_a if index < 1000 else iter_b,
            )

        self.assertEqual(self.db.count_events(), 1005)
        self.assertEqual(self.db.count_events(iteration_id=iter_a), 1000)
        self.assertEqual(self.db.count_events(iteration_id=iter_b), 5)
        self.assertEqual(self.db.count_events(event_type="command_executed"), 503)


class TestStats(unittest.TestCase):
    """Tests for general statistics."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_stats_empty_db(self):
        """In an empty DB, the counters must be 0."""
        stats = self.db.get_stats()

        self.assertEqual(stats["total_iterations"], 0)
        self.assertEqual(stats["total_decisions"], 0)
        self.assertEqual(stats["total_commits"], 0)
        self.assertEqual(stats["total_events"], 0)

    def test_stats_with_data(self):
        """The counters must reflect the inserted data."""
        self.db.start_iteration("feature", "Test stats")
        self.db.log_decision(title="Dec 1", chosen="A")
        self.db.log_decision(title="Dec 2", chosen="B")
        self.db.log_commit(sha="stats_sha_1", message="commit 1")
        self.db.log_event(event_type="phase_completed", phase="product")

        stats = self.db.get_stats()

        self.assertEqual(stats["total_iterations"], 1)
        self.assertEqual(stats["total_decisions"], 2)
        self.assertEqual(stats["total_commits"], 1)
        self.assertEqual(stats["total_events"], 1)

    def test_stats_includes_metadata(self):
        """The statistics include metadata from the meta table."""
        stats = self.db.get_stats()

        self.assertIn("schema_version", stats)
        self.assertEqual(stats["schema_version"], "4")
        self.assertIn("fts_enabled", stats)
        self.assertIn("created_at", stats)

    def test_stats_fts_coherent_with_property(self):
        """The fts_enabled field in stats matches the property."""
        stats = self.db.get_stats()
        expected = "1" if self.db.fts_enabled else "0"
        self.assertEqual(stats["fts_enabled"], expected)


class TestReopen(unittest.TestCase):
    """Tests for reopening the database (persistence across sessions)."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_data_persists_after_close_and_reopen(self):
        """Data must persist after the DB is closed and reopened."""
        db = MemoryDB(self._db_path)
        iter_id = db.start_iteration("feature", "Persistence")
        db.log_decision(title="Persistent decision", chosen="SQLite")
        db.close()

        # Reopen
        db2 = MemoryDB(self._db_path)
        iteration = db2.get_iteration(iter_id)
        decisions = db2.get_decisions()
        db2.close()

        self.assertIsNotNone(iteration)
        self.assertEqual(iteration["command"], "feature")
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["title"], "Persistent decision")

    def test_schema_not_duplicated_on_reopen(self):
        """Reopening the DB must not duplicate the schema version."""
        db = MemoryDB(self._db_path)
        db.close()

        db2 = MemoryDB(self._db_path)
        stats = db2.get_stats()
        db2.close()

        self.assertEqual(stats["schema_version"], "4")


# ---------------------------------------------------------------------------
# SQL of schema v1 (no tags, status, files or decision_links).
# The migration tests use it to create a DB that simulates the earlier
# version and to check that _run_migrations converts it correctly.
# ---------------------------------------------------------------------------

_V1_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS iterations (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    command          TEXT    NOT NULL,
    description      TEXT,
    status           TEXT    NOT NULL DEFAULT 'active',
    started_at       TEXT    NOT NULL,
    completed_at     TEXT,
    phases_completed TEXT,
    artifacts        TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration_id  INTEGER REFERENCES iterations(id),
    title         TEXT    NOT NULL,
    context       TEXT,
    chosen        TEXT    NOT NULL,
    alternatives  TEXT,
    rationale     TEXT,
    impact        TEXT,
    phase         TEXT,
    decided_at    TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS commits (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    sha           TEXT    UNIQUE NOT NULL,
    message       TEXT,
    author        TEXT,
    files_changed INTEGER,
    insertions    INTEGER,
    deletions     INTEGER,
    committed_at  TEXT    NOT NULL,
    iteration_id  INTEGER REFERENCES iterations(id)
);
CREATE TABLE IF NOT EXISTS commit_links (
    commit_id   INTEGER REFERENCES commits(id),
    decision_id INTEGER REFERENCES decisions(id),
    link_type   TEXT,
    PRIMARY KEY (commit_id, decision_id)
);
CREATE TABLE IF NOT EXISTS events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    iteration_id  INTEGER REFERENCES iterations(id),
    event_type    TEXT    NOT NULL,
    phase         TEXT,
    payload       TEXT,
    created_at    TEXT    NOT NULL
);
"""


def _create_v1_db(db_path: str) -> None:
    """Create a database with schema v1 for migration tests.

    Run the SQL of the original schema (without the columns and tables
    added in v2) and insert version 1 into the meta table.

    Args:
        db_path: path to the SQLite file to create.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(_V1_SCHEMA_SQL)
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', '1')"
    )
    conn.commit()
    conn.close()


class TestSchemaMigration(unittest.TestCase):
    """Check that the schema migration works correctly.

    Each test that needs a v1 DB creates it by hand with the original
    schema (6 tables, without the tags/status/files columns and without
    the decision_links table). Then it opens the DB with MemoryDB to force
    the migration.
    """

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()

    def tearDown(self):
        # Clean up SQLite files (main + WAL + shm + backup)
        for suffix in ("", "-wal", "-shm", ".bak"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_new_db_gets_latest_schema_version(self):
        """A new DB must be created directly with the latest version."""
        db = MemoryDB(self._db_path)
        stats = db.get_stats()
        db.close()

        self.assertEqual(stats["schema_version"], "4")

    def test_v1_db_migrates_to_v3(self):
        """A DB with schema v1 must migrate to v4 automatically when opened."""
        _create_v1_db(self._db_path)

        db = MemoryDB(self._db_path)
        stats = db.get_stats()
        db.close()

        self.assertEqual(stats["schema_version"], "4")

    def test_migration_creates_backup(self):
        """A migration must create a backup copy (.bak) of the file."""
        _create_v1_db(self._db_path)

        db = MemoryDB(self._db_path)
        db.close()

        bak_path = self._db_path + ".bak"
        self.assertTrue(
            os.path.exists(bak_path),
            f"Backup file not found at {bak_path}"
        )

    def test_migration_adds_tags_column(self):
        """After migration from v1, the decisions table must have the tags column."""
        _create_v1_db(self._db_path)

        db = MemoryDB(self._db_path)

        # Check that a record with the tags column can be inserted
        db._conn.execute(
            "INSERT INTO decisions "
            "(title, chosen, tags, status, decided_at) "
            "VALUES ('Test', 'A', '[\"tag1\"]', 'active', '2026-01-01T00:00:00+00:00')"
        )
        db._conn.commit()

        row = db._conn.execute(
            "SELECT tags FROM decisions WHERE title = 'Test'"
        ).fetchone()
        db.close()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], '["tag1"]')

    def test_migration_creates_decision_links_table(self):
        """After migration from v1, the decision_links table must exist."""
        _create_v1_db(self._db_path)

        db = MemoryDB(self._db_path)

        row = db._conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='decision_links'"
        ).fetchone()
        db.close()

        self.assertIsNotNone(
            row,
            "The decision_links table was not found in sqlite_master"
        )


class TestDecisionTagsAndStatus(unittest.TestCase):
    """Tests for tags and status on decisions.

    They check that tags are stored as JSON, that the status can be
    updated with valid values and that the defaults are correct.
    """

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_log_decision_with_tags(self):
        """The given tags are stored as JSON in the tags column."""
        dec_id = self.db.log_decision(
            title="Decision with tags",
            chosen="Option A",
            tags=["architecture", "performance"],
        )
        decisions = self.db.get_decisions()
        d = decisions[0]

        tags = json.loads(d["tags"])
        self.assertEqual(tags, ["architecture", "performance"])

    def test_log_decision_without_tags_defaults_empty(self):
        """Without tags, the tags column contains an empty JSON list."""
        dec_id = self.db.log_decision(
            title="Decision without tags",
            chosen="Option B",
        )
        decisions = self.db.get_decisions()
        d = decisions[0]

        tags = json.loads(d["tags"])
        self.assertEqual(tags, [])

    def test_add_decision_tags(self):
        """add_decision_tags adds tags without duplicating existing ones."""
        dec_id = self.db.log_decision(
            title="Decision to tag",
            chosen="Option C",
            tags=["frontend"],
        )
        self.db.add_decision_tags(dec_id, ["backend", "frontend", "api"])

        decisions = self.db.get_decisions()
        tags = json.loads(decisions[0]["tags"])

        # frontend must not be duplicated; the order keeps the insertion order
        self.assertEqual(tags, ["frontend", "backend", "api"])

    def test_update_decision_status(self):
        """update_decision_status changes the status correctly."""
        dec_id = self.db.log_decision(
            title="Decision to replace",
            chosen="Old option",
        )
        self.db.update_decision_status(dec_id, "superseded")

        decisions = self.db.get_decisions()
        self.assertEqual(decisions[0]["status"], "superseded")

    def test_update_decision_status_invalid(self):
        """An invalid status must raise ValueError."""
        dec_id = self.db.log_decision(
            title="Decision with invalid status",
            chosen="Something",
        )
        with self.assertRaises(ValueError):
            self.db.update_decision_status(dec_id, "invalid")

    def test_decision_default_status_active(self):
        """The default status of a new decision is 'active'."""
        dec_id = self.db.log_decision(
            title="New decision",
            chosen="Anything",
        )
        decisions = self.db.get_decisions()
        self.assertEqual(decisions[0]["status"], "active")


class TestDecisionLinks(unittest.TestCase):
    """Tests for links between decisions.

    They check that directed links between decisions can be created,
    that idempotency works and that lookup works in both directions.
    """

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_link_decisions(self):
        """link_decisions creates the link and get_decision_links returns it."""
        dec1 = self.db.log_decision(title="Source decision", chosen="A")
        dec2 = self.db.log_decision(title="Target decision", chosen="B")

        self.db.link_decisions(dec1, dec2, "supersedes")
        links = self.db.get_decision_links(dec1)

        self.assertEqual(len(links), 1)
        self.assertEqual(links[0]["source_id"], dec1)
        self.assertEqual(links[0]["target_id"], dec2)
        self.assertEqual(links[0]["link_type"], "supersedes")
        self.assertIn("created_at", links[0])

    def test_link_decisions_duplicate_ignored(self):
        """Creating the same link twice does not raise an exception."""
        dec1 = self.db.log_decision(title="Dec A", chosen="X")
        dec2 = self.db.log_decision(title="Dec B", chosen="Y")

        self.db.link_decisions(dec1, dec2, "relates")
        # Second time: must not fail
        self.db.link_decisions(dec1, dec2, "relates")

        links = self.db.get_decision_links(dec1)
        self.assertEqual(len(links), 1)

    def test_get_decision_links_bidirectional(self):
        """get_decision_links returns results when looked up from the target."""
        dec1 = self.db.log_decision(title="Source", chosen="A")
        dec2 = self.db.log_decision(title="Target", chosen="B")

        self.db.link_decisions(dec1, dec2, "depends_on")

        # A lookup from the target (dec2) also returns the link
        links_from_target = self.db.get_decision_links(dec2)
        self.assertEqual(len(links_from_target), 1)
        self.assertEqual(links_from_target[0]["source_id"], dec1)
        self.assertEqual(links_from_target[0]["target_id"], dec2)

    def test_get_decision_links_empty(self):
        """Without links, get_decision_links returns an empty list."""
        dec = self.db.log_decision(title="Lonely", chosen="Z")
        links = self.db.get_decision_links(dec)
        self.assertEqual(links, [])


class TestSearchFilters(unittest.TestCase):
    """Tests for the advanced search filters (since, until, tags, status).

    They check that search() and get_decisions() apply the date, tag
    and status filters correctly to the returned results.
    """

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_search_with_since_filter(self):
        """since excludes results dated before the threshold."""
        # Create two decisions with the same term so both appear
        dec_old = self.db.log_decision(
            title="Optimization old",
            chosen="Cache LRU",
        )
        dec_new = self.db.log_decision(
            title="Optimization recent",
            chosen="Distributed cache",
        )

        # Force the date of the first decision to 2025-01-01 with direct SQL
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "UPDATE decisions SET decided_at = ? WHERE id = ?",
            ("2025-01-01T00:00:00+00:00", dec_old),
        )
        conn.commit()
        conn.close()

        results = self.db.search("Optimization", since="2026-01-01")
        titles = [r.get("title", "") for r in results]

        self.assertNotIn("Optimization old", titles)
        self.assertTrue(
            any("Optimization recent" in t for t in titles),
            f"The recent decision must appear, results: {titles}",
        )

    def test_search_with_until_filter(self):
        """until excludes results dated after the threshold."""
        dec_old = self.db.log_decision(
            title="Migration old",
            chosen="PostgreSQL 14",
        )
        dec_new = self.db.log_decision(
            title="Migration recent",
            chosen="PostgreSQL 16",
        )

        # Force the date of the first decision to 2025-01-01
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "UPDATE decisions SET decided_at = ? WHERE id = ?",
            ("2025-01-01T00:00:00+00:00", dec_old),
        )
        conn.commit()
        conn.close()

        results = self.db.search("Migration", until="2025-06-01")
        titles = [r.get("title", "") for r in results]

        self.assertNotIn("Migration recent", titles)
        self.assertTrue(
            any("Migration old" in t for t in titles),
            f"The old decision must appear, results: {titles}",
        )

    def test_search_with_tags_filter(self):
        """tags filters decisions that contain at least one tag."""
        self.db.log_decision(
            title="Authentication policy",
            chosen="OAuth2",
            tags=["security", "auth"],
        )
        self.db.log_decision(
            title="Cache policy",
            chosen="Redis",
            tags=["performance"],
        )

        results = self.db.search("policy", tags=["security"])
        titles = [r.get("title", "") for r in results]

        self.assertTrue(
            any("Authentication" in t for t in titles),
            f"The security decision must appear: {titles}",
        )
        self.assertNotIn("Cache policy", titles)

    def test_search_with_status_filter(self):
        """status filters decisions by their status."""
        dec_active = self.db.log_decision(
            title="Deployment strategy active",
            chosen="Kubernetes",
        )
        dec_superseded = self.db.log_decision(
            title="Deployment strategy old",
            chosen="Docker Swarm",
        )
        self.db.update_decision_status(dec_superseded, "superseded")

        results = self.db.search("Deployment strategy", status="active")
        titles = [r.get("title", "") for r in results]

        self.assertTrue(
            any("active" in t for t in titles),
            f"The active decision must appear: {titles}",
        )
        self.assertNotIn("Deployment strategy old", titles)

    def test_get_decisions_with_tags_filter(self):
        """get_decisions filters by tags in SQL."""
        self.db.log_decision(
            title="Data access pattern",
            chosen="Repository pattern",
            tags=["architecture", "backend"],
        )
        self.db.log_decision(
            title="UI design",
            chosen="Material Design",
            tags=["frontend", "ux"],
        )

        results = self.db.get_decisions(tags=["architecture"])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Data access pattern")

    def test_get_decisions_with_status_filter(self):
        """get_decisions filters by status in SQL."""
        dec1 = self.db.log_decision(
            title="Current decision",
            chosen="A",
        )
        dec2 = self.db.log_decision(
            title="Replaced decision",
            chosen="B",
        )
        self.db.update_decision_status(dec2, "superseded")

        actives = self.db.get_decisions(status="active")
        self.assertEqual(len(actives), 1)
        self.assertEqual(actives[0]["title"], "Current decision")

        superseded = self.db.get_decisions(status="superseded")
        self.assertEqual(len(superseded), 1)
        self.assertEqual(superseded[0]["title"], "Replaced decision")


class TestCommitFiles(unittest.TestCase):
    """Tests for the files field on commits.

    They check that the list of changed files is serialized correctly
    as JSON in the ``files`` column of the commits table.
    """

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_log_commit_with_files(self):
        """files is stored as JSON when a list is given."""
        commit_id = self.db.log_commit(
            sha="files_test_sha_1",
            message="feat: new component",
            files=["src/components/Button.tsx", "src/styles/button.css"],
        )
        self.assertIsNotNone(commit_id)

        # Check with direct SQL
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT files FROM commits WHERE id = ?", (commit_id,)
        ).fetchone()
        conn.close()

        files = json.loads(row[0])
        self.assertEqual(
            files,
            ["src/components/Button.tsx", "src/styles/button.css"],
        )

    def test_log_commit_without_files_defaults_empty(self):
        """Without files, the column contains an empty JSON list."""
        commit_id = self.db.log_commit(
            sha="files_test_sha_2",
            message="chore: cleanup",
        )
        self.assertIsNotNone(commit_id)

        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT files FROM commits WHERE id = ?", (commit_id,)
        ).fetchone()
        conn.close()

        files = json.loads(row[0])
        self.assertEqual(files, [])

    def test_log_commit_files_list_stored(self):
        """Paths are stored exactly in the files field."""
        expected_files = [
            "core/memory.py",
            "tests/test_memory.py",
            "docs/changelog.md",
        ]
        commit_id = self.db.log_commit(
            sha="files_test_sha_3",
            message="refactor: reorganize modules",
            files=expected_files,
        )
        self.assertIsNotNone(commit_id)

        # Check directly against SQLite, without the API
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT files FROM commits WHERE sha = 'files_test_sha_3'"
        ).fetchone()
        conn.close()

        stored_files = json.loads(row[0])
        self.assertEqual(stored_files, expected_files)


class TestHealthCheck(unittest.TestCase):
    """Tests for database integrity validation.

    They check that check_health() correctly detects the schema state,
    the file permissions and the database size.
    """

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_healthy_db(self):
        """A new DB must report status 'healthy' with no issues."""
        health = self.db.check_health()
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(len(health["issues"]), 0)

    def test_schema_version_check(self):
        """The schema version must be '4'."""
        health = self.db.check_health()
        self.assertEqual(health["schema_version"], "4")

    def test_permissions_check(self):
        """The file permissions must be correct."""
        health = self.db.check_health()
        self.assertTrue(health["permissions_ok"])

    def test_db_size_reported(self):
        """The DB size must exist and be an integer greater than 0."""
        health = self.db.check_health()
        self.assertIn("size_bytes", health)
        self.assertIsInstance(health["size_bytes"], int)
        self.assertGreater(health["size_bytes"], 0)

    def test_health_includes_wal_size(self):
        """size_bytes must include the WAL when there is recent data."""
        self.db.start_iteration("feature", "size")
        self.db.log_event(event_type="custom", content="A" * 100000)

        health = self.db.check_health()
        main_size = os.path.getsize(self._db_path)

        self.assertGreater(health["size_bytes"], main_size)

    def test_reopen_repairs_legacy_fts_content(self):
        """On reopen, an old DB must rebuild FTS with the new format."""
        if not self.db.fts_enabled:
            self.skipTest("FTS5 is not available in this environment.")

        iteration_id = self.db.start_iteration("feature", "fts legacy")
        commit_id = self.db.log_commit(
            sha="legacy_fts_sha",
            message="feat: auth pipeline",
            files=["src/auth/callback.py"],
            iteration_id=iteration_id,
        )
        event_id = self.db.log_event(
            event_type="custom",
            summary="rollout freeze approved",
            iteration_id=iteration_id,
        )

        self.db._conn.execute(
            "UPDATE meta SET value = '1' WHERE key = 'fts_content_version'"
        )
        self.db._conn.execute("DELETE FROM memory_fts")
        self.db._conn.execute(
            "INSERT INTO memory_fts (source_type, source_id, content) VALUES (?, ?, ?)",
            ("commit", str(commit_id), "feat: auth pipeline"),
        )
        self.db._conn.commit()
        self.db.close()

        self.db = MemoryDB(self._db_path)

        commit_row = self.db._conn.execute(
            "SELECT content FROM memory_fts WHERE source_type = 'commit' AND source_id = ?",
            (str(commit_id),),
        ).fetchone()
        event_row = self.db._conn.execute(
            "SELECT content FROM memory_fts WHERE source_type = 'event' AND source_id = ?",
            (str(event_id),),
        ).fetchone()
        meta_row = self.db._conn.execute(
            "SELECT value FROM meta WHERE key = 'fts_content_version'"
        ).fetchone()

        self.assertIn("callback.py", commit_row[0])
        self.assertIn("rollout freeze approved", event_row[0])
        self.assertEqual(meta_row[0], "2")
        self.assertEqual(self.db.check_health()["status"], "healthy")


class TestExportImport(unittest.TestCase):
    """Tests for data export and import.

    They check that export_decisions_markdown writes correct files and
    that import_git_history is idempotent for commits that are already
    recorded.
    """

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)
        self._export_dir = tempfile.mkdtemp()

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)
        import shutil
        shutil.rmtree(self._export_dir, ignore_errors=True)

    def _init_repo(self, name: str) -> str:
        import subprocess

        repo_dir = os.path.join(self._export_dir, name)
        os.makedirs(repo_dir)
        subprocess.run(
            ["git", "init"], cwd=repo_dir,
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=repo_dir, capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=repo_dir, capture_output=True, check=True,
        )
        return repo_dir

    def test_export_markdown_creates_file(self):
        """export_decisions_markdown must create the file with the title."""
        self.db.log_decision(
            title="Use SQLite as the memory engine",
            chosen="SQLite",
            context="We need light local persistence",
        )
        export_path = os.path.join(self._export_dir, "decisions.md")
        count = self.db.export_decisions_markdown(export_path)

        self.assertEqual(count, 1)
        self.assertTrue(os.path.exists(export_path))

        with open(export_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("Use SQLite as the memory engine", content)

    def test_export_markdown_includes_metadata(self):
        """The export must include tags and status in the Markdown."""
        self.db.log_decision(
            title="Data access pattern",
            chosen="Repository pattern",
            tags=["architecture", "backend"],
        )
        export_path = os.path.join(self._export_dir, "meta.md")
        self.db.export_decisions_markdown(export_path)

        with open(export_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("architecture", content)
        self.assertIn("backend", content)
        self.assertIn("active", content)

    def test_import_git_history_idempotent(self):
        """Importing the same history twice does not duplicate commits."""
        import subprocess

        repo_dir = self._init_repo("test_repo")
        test_file = os.path.join(repo_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("test")
        subprocess.run(
            ["git", "add", "."], cwd=repo_dir,
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "feat: test commit"],
            cwd=repo_dir, capture_output=True, check=True,
        )

        first_count = self.db.import_git_history(repo_dir)
        self.assertEqual(first_count, 1)

        second_count = self.db.import_git_history(repo_dir)
        self.assertEqual(second_count, 0)

    def test_import_git_history_handles_pipe_in_subject(self):
        """Must not break if the commit subject contains |."""
        import subprocess

        repo_dir = self._init_repo("pipe_repo")
        with open(os.path.join(repo_dir, "test.txt"), "w", encoding="utf-8") as handle:
            handle.write("test")
        subprocess.run(
            ["git", "add", "."], cwd=repo_dir,
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "feat | weird separator"],
            cwd=repo_dir, capture_output=True, check=True,
        )

        imported = self.db.import_git_history(repo_dir)
        self.assertEqual(imported, 1)

        results = self.db.search("weird separator", limit=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_type"], "commit")
        self.assertEqual(results[0]["message"], "feat | weird separator")
        self.assertEqual(results[0]["author"], "Test")

    def test_import_git_history_preserves_commit_date(self):
        """Imported history must keep committed_at from the repo."""
        import subprocess

        repo_dir = self._init_repo("dated_repo")
        with open(os.path.join(repo_dir, "dated.txt"), "w", encoding="utf-8") as handle:
            handle.write("dated")
        subprocess.run(
            ["git", "add", "."], cwd=repo_dir,
            capture_output=True, check=True,
        )
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = "2024-05-06T07:08:09+00:00"
        env["GIT_COMMITTER_DATE"] = "2024-05-06T07:08:09+00:00"
        subprocess.run(
            ["git", "commit", "-m", "feat: dated import"],
            cwd=repo_dir, env=env, capture_output=True, check=True,
        )

        imported = self.db.import_git_history(repo_dir)
        self.assertEqual(imported, 1)

        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT committed_at FROM commits WHERE message = ?",
            ("feat: dated import",),
        ).fetchone()
        conn.close()

        expected = datetime.fromisoformat("2024-05-06T07:08:09+00:00")
        actual = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
        self.assertEqual(actual, expected)

    def test_import_git_history_does_not_link_history_to_active_iteration(self):
        """Importing history must not pollute the current active iteration."""
        import subprocess

        repo_dir = self._init_repo("iteration_repo")
        with open(os.path.join(repo_dir, "iter.txt"), "w", encoding="utf-8") as handle:
            handle.write("iter")
        subprocess.run(
            ["git", "add", "."], cwd=repo_dir,
            capture_output=True, check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "feat: imported history"],
            cwd=repo_dir, capture_output=True, check=True,
        )

        active_iteration = self.db.start_iteration("feature", "Current work")
        imported = self.db.import_git_history(repo_dir)

        self.assertEqual(imported, 1)
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT iteration_id FROM commits WHERE message = ?",
            ("feat: imported history",),
        ).fetchone()
        conn.close()

        self.assertNotEqual(row[0], active_iteration)
        self.assertIsNone(row[0])


class TestEventSearchAndPurge(unittest.TestCase):
    """Check event FTS and cleanup on purge."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            suffix=".db", delete=False
        )
        self._db_path = self._tmpfile.name
        self._tmpfile.close()
        self.db = MemoryDB(self._db_path)
        self.iter_id = self.db.start_iteration("feature", "fts events")

    def tearDown(self):
        self.db.close()
        for suffix in ("", "-wal", "-shm"):
            path = self._db_path + suffix
            if os.path.exists(path):
                os.unlink(path)

    def test_search_returns_event_content(self):
        """Search must return events that match by text."""
        self.db.log_event(
            event_type="custom",
            content="token refresh strategy approved",
            iteration_id=self.iter_id,
        )

        results = self.db.search("token refresh", limit=10)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["source_type"], "event")
        self.assertEqual(results[0]["content"], "token refresh strategy approved")

    def test_purge_old_events_removes_fts_entries(self):
        """Purging events must also clean up their FTS rows."""
        event_id = self.db.log_event(
            event_type="custom",
            content="legacy rollout note",
            iteration_id=self.iter_id,
        )
        old_date = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        self.db._conn.execute(
            "UPDATE events SET created_at = ? WHERE id = ?",
            (old_date, event_id),
        )
        self.db._conn.commit()

        deleted = self.db.purge_old_events(retention_days=30)

        self.assertEqual(deleted, 1)
        self.assertEqual(self.db.search("legacy rollout", limit=10), [])
        self.assertEqual(self.db.check_health()["status"], "healthy")


if __name__ == "__main__":
    unittest.main()
