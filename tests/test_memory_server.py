#!/usr/bin/env python3
"""
Tests for the MCP tools of the memory server.

Each test checks that the MCP server handlers return correct results
when they run operations on a temporary database. The tests cover both
the success path and the validation cases.
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.memory import MemoryDB
from mcp import memory_server as memory_server_module
from mcp.memory_server import MemoryMCPServer, _TOOLS, resolve_retention_days


class _BinaryInput:
    def __init__(self, data: bytes) -> None:
        self.buffer = io.BytesIO(data)


class _BinaryOutput:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()


class TestMCPTransport(unittest.TestCase):
    """Check modern MCP stdio framing and legacy compatibility."""

    def tearDown(self):
        memory_server_module._TRANSPORT_MODE = "jsonl"

    def test_read_message_accepts_json_lines(self):
        """Modern MCP stdio sends one JSON-RPC message per line."""
        old_stdin = sys.stdin
        try:
            sys.stdin = _BinaryInput(
                b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
            )
            message = memory_server_module._read_message()
        finally:
            sys.stdin = old_stdin

        self.assertEqual(message["method"], "ping")
        self.assertEqual(memory_server_module._TRANSPORT_MODE, "jsonl")

    def test_read_message_accepts_content_length_framing(self):
        """The legacy Content-Length framing is still accepted."""
        body = b'{"jsonrpc":"2.0","id":2,"method":"ping"}'
        payload = b"Content-Length: %d\r\n\r\n" % len(body) + body
        old_stdin = sys.stdin
        try:
            sys.stdin = _BinaryInput(payload)
            message = memory_server_module._read_message()
        finally:
            sys.stdin = old_stdin

        self.assertEqual(message["id"], 2)
        self.assertEqual(memory_server_module._TRANSPORT_MODE, "content-length")

    def test_write_message_uses_json_lines_by_default(self):
        """New responses use JSONL for current MCP clients."""
        old_stdout = sys.stdout
        sink = _BinaryOutput()
        try:
            sys.stdout = sink
            memory_server_module._TRANSPORT_MODE = "jsonl"
            memory_server_module._write_message(
                {"jsonrpc": "2.0", "id": 1, "result": {}}
            )
        finally:
            sys.stdout = old_stdout

        output = sink.buffer.getvalue()
        self.assertFalse(output.startswith(b"Content-Length:"))
        self.assertTrue(output.endswith(b"\n"))
        self.assertEqual(json.loads(output.decode("utf-8"))["id"], 1)

    def test_write_message_preserves_legacy_framing(self):
        """If the client used Content-Length, reply the same way."""
        old_stdout = sys.stdout
        sink = _BinaryOutput()
        try:
            sys.stdout = sink
            memory_server_module._TRANSPORT_MODE = "content-length"
            memory_server_module._write_message(
                {"jsonrpc": "2.0", "id": 2, "result": {}}
            )
        finally:
            sys.stdout = old_stdout

        output = sink.buffer.getvalue()
        self.assertTrue(output.startswith(b"Content-Length:"))
        self.assertIn(b"\r\n\r\n", output)


class TestMCPTools(unittest.TestCase):
    """Check that the MCP handlers return correct results."""

    def setUp(self):
        self._project_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self._project_dir, ".claude"), exist_ok=True)
        self._db_path = os.path.join(
            self._project_dir,
            ".claude",
            "alfred-memory.db",
        )
        self.server = MemoryMCPServer(db_path=self._db_path)
        self.server._project_dir = self._project_dir
        self.db = self.server._ensure_db()

    def tearDown(self):
        if self.server._db:
            self.server._db.close()
        shutil.rmtree(self._project_dir, ignore_errors=True)

    # --- Tests for new tools ----------------------------------------------

    def test_memory_update_decision_changes_status(self):
        """memory_update_decision changes the status of a decision."""
        dec_id = self.db.log_decision(
            title="Decision to update",
            chosen="Option A",
        )
        result = self.server._call_memory_update_decision(
            self.db, {"id": dec_id, "status": "superseded"},
        )

        self.assertNotIn("error", result)
        self.assertEqual(result["id"], dec_id)

        # Check that the status was really applied
        decisions = self.db.get_decisions()
        self.assertEqual(decisions[0]["status"], "superseded")

    def test_memory_update_decision_adds_tags(self):
        """memory_update_decision adds tags without duplicates."""
        dec_id = self.db.log_decision(
            title="Decision to tag",
            chosen="Option B",
            tags=["existing"],
        )
        result = self.server._call_memory_update_decision(
            self.db, {"id": dec_id, "tags": ["new", "existing"]},
        )

        self.assertNotIn("error", result)

        decisions = self.db.get_decisions()
        tags = json.loads(decisions[0]["tags"])
        # The "existing" tag must not be duplicated
        self.assertEqual(tags, ["existing", "new"])

    def test_memory_link_decisions_creates_link(self):
        """memory_link_decisions creates the link between decisions."""
        dec1 = self.db.log_decision(title="Source", chosen="A")
        dec2 = self.db.log_decision(title="Target", chosen="B")

        result = self.server._call_memory_link_decisions(
            self.db,
            {"source_id": dec1, "target_id": dec2, "link_type": "supersedes"},
        )

        self.assertNotIn("error", result)
        self.assertEqual(result["source_id"], dec1)
        self.assertEqual(result["target_id"], dec2)
        self.assertEqual(result["link_type"], "supersedes")

        # Check that the link exists in the DB
        links = self.db.get_decision_links(dec1)
        self.assertEqual(len(links), 1)

    def test_memory_health_returns_status(self):
        """memory_health returns a report with status and schema_version."""
        result = self.server._call_memory_health(self.db, {})

        self.assertIn("status", result)
        self.assertIn("schema_version", result)
        self.assertIn("fts_enabled", result)
        self.assertIn("size_bytes", result)
        # A new DB must be healthy
        self.assertEqual(result["status"], "healthy")

    def test_memory_export_returns_count(self):
        """memory_export exports the decisions and returns the count."""
        self.db.log_decision(title="Decision A", chosen="Option 1")
        self.db.log_decision(title="Decision B", chosen="Option 2")

        export_path = os.path.join(self._project_dir, "docs", "test_export.md")
        result = self.server._call_memory_export(
            self.db,
            {"format": "markdown", "path": export_path},
        )

        self.assertNotIn("error", result)
        self.assertEqual(result["exported"], 2)
        self.assertEqual(result["format"], "markdown")
        self.assertTrue(os.path.exists(export_path))

    def test_memory_export_rejects_path_outside_project(self):
        """memory_export must not write outside the current project."""
        self.db.log_decision(title="Decision A", chosen="Option 1")
        outside_dir = tempfile.mkdtemp()
        outside_path = os.path.join(outside_dir, "decisions.md")
        try:
            result = self.server._call_memory_export(
                self.db,
                {"format": "markdown", "path": outside_path},
            )

            self.assertIn("error", result)
            self.assertIn("внутри текущего проекта", result["error"])
            self.assertFalse(os.path.exists(outside_path))
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)

    def test_memory_import_rejects_path_outside_project(self):
        """memory_import must not read repositories or ADRs outside the project."""
        outside_dir = tempfile.mkdtemp()
        try:
            result = self.server._call_memory_import(
                self.db,
                {"source": "adr", "path": outside_dir},
            )

            self.assertIn("error", result)
            self.assertIn("внутри текущего проекта", result["error"])
        finally:
            shutil.rmtree(outside_dir, ignore_errors=True)

    def test_memory_log_event_indexes_payload_when_content_missing(self):
        """memory_log_event keeps the event searchable when only a payload arrives."""
        self.db.start_iteration("feature", "Demo")

        result = self.server._call_memory_log_event(
            self.db,
            {
                "event_type": "custom",
                "phase": "quality",
                "payload": {"note": "token refresh broken"},
            },
        )

        self.assertNotIn("error", result)
        found = self.db.search("token")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["source_type"], "event")

    def test_memory_log_event_rejects_non_object_payload(self):
        """memory_log_event accepts only JSON object payloads."""
        self.db.start_iteration("feature", "Demo")

        result = self.server._call_memory_log_event(
            self.db,
            {
                "event_type": "custom",
                "payload": ["no", "object"],
            },
        )

        self.assertIn("error", result)
        self.assertIn("payload", result["error"])

    def test_memory_log_event_schema_declares_bounds(self):
        """The MCP schema must expose limits for free-form events."""
        tool = next(tool for tool in _TOOLS if tool["name"] == "memory_log_event")
        props = tool["inputSchema"]["properties"]

        self.assertEqual(
            props["event_type"]["maxLength"],
            memory_server_module._EVENT_TYPE_MAX,
        )
        self.assertEqual(
            props["phase"]["maxLength"],
            memory_server_module._EVENT_PHASE_MAX,
        )
        self.assertEqual(
            props["summary"]["maxLength"],
            memory_server_module._EVENT_SUMMARY_MAX,
        )
        self.assertEqual(
            props["content"]["maxLength"],
            memory_server_module._EVENT_CONTENT_MAX,
        )
        self.assertIn("preview", props["payload"]["description"])

    def test_memory_log_event_truncates_large_mcp_content_and_payload(self):
        """The MCP boundary truncates very large events and keeps traceability."""
        iteration_id = self.db.start_iteration("feature", "Demo")

        result = self.server._call_memory_log_event(
            self.db,
            {
                "event_type": "custom",
                "phase": "quality",
                "summary": "large content",
                "content": "x" * (memory_server_module._EVENT_CONTENT_MAX + 1000),
                "payload": {
                    "blob": "y" * (memory_server_module._EVENT_PAYLOAD_MAX + 1000)
                },
            },
        )

        self.assertNotIn("error", result)
        self.assertTrue(result["content_truncated"])
        self.assertTrue(result["payload_truncated"])

        timeline = self.db.get_timeline(iteration_id)
        event = timeline[0]
        self.assertLess(len(event["content"]), memory_server_module._EVENT_CONTENT_MAX + 1000)
        self.assertIn("содержимое обрезано", event["content"])

        payload = json.loads(event["payload"])
        self.assertTrue(payload["_truncated"])
        self.assertIn("_alfred_mcp_truncation", payload)
        self.assertIn("payload", payload["_alfred_mcp_truncation"])
        self.assertLess(
            len(json.dumps(payload, ensure_ascii=False)),
            memory_server_module._EVENT_PAYLOAD_MAX + 1000,
        )

    def test_memory_get_iteration_returns_all_decisions_for_iteration(self):
        """memory_get_iteration must not truncate decisions to 50."""
        iteration_id = self.db.start_iteration("feature", "Long demo")
        for index in range(55):
            self.db.log_decision(
                title=f"Decision {index}",
                chosen="Option",
                iteration_id=iteration_id,
            )

        result = self.server._call_memory_get_iteration(self.db, {"id": iteration_id})

        self.assertNotIn("error", result)
        self.assertEqual(result["iteration"]["id"], iteration_id)
        self.assertEqual(result["total_decisions"], 55)
        self.assertEqual(len(result["decisions"]), 55)

    def test_memory_get_timeline_returns_full_iteration_history(self):
        """memory_get_timeline must not truncate long timelines to 100."""
        iteration_id = self.db.start_iteration("feature", "Long timeline")
        for index in range(105):
            self.db.log_event(
                event_type="custom",
                summary=f"event {index}",
                iteration_id=iteration_id,
            )

        result = self.server._call_memory_get_timeline(
            self.db,
            {"iteration_id": iteration_id},
        )

        self.assertNotIn("error", result)
        self.assertEqual(result["iteration_id"], iteration_id)
        self.assertEqual(result["total"], 105)
        self.assertEqual(len(result["events"]), 105)

    def test_initialize_uses_plugin_version(self):
        """initialize exposes the same version as plugin.json."""
        response = self.server._handle_initialize(1, {})
        with open(
            os.path.join(os.path.dirname(__file__), "..", ".claude-plugin", "plugin.json"),
            "r",
            encoding="utf-8",
        ) as fh:
            plugin = json.load(fh)

        self.assertEqual(
            response["result"]["serverInfo"]["version"],
            plugin["version"],
        )

    def test_tools_call_dispatches_bound_handler(self):
        """tools/call must run real handlers, not only list schemas."""
        response = self.server._handle_tools_call(
            2,
            {"name": "memory_stats", "arguments": {}},
        )

        self.assertNotIn("error", response)
        self.assertFalse(response["result"]["isError"])
        payload = json.loads(response["result"]["content"][0]["text"])
        self.assertIn("total_decisions", payload)
        self.assertIn("db_path", payload)

    # --- Tests for changed tools ------------------------------------------

    def test_memory_search_with_filters(self):
        """memory_search passes the tag and status filters correctly."""
        self.db.log_decision(
            title="Security policy",
            chosen="OAuth2",
            tags=["security"],
        )
        self.db.log_decision(
            title="Performance policy",
            chosen="Redis",
            tags=["performance"],
        )

        result = self.server._call_memory_search(
            self.db,
            {"query": "policy", "tags": ["security"]},
        )

        self.assertGreater(result["total"], 0)
        # Only the security decision must appear
        titles = [r.get("title", "") for r in result["results"]]
        self.assertTrue(any("Security" in t for t in titles))
        self.assertFalse(any("Performance" in t for t in titles))

    def test_memory_search_caps_excessive_limit(self):
        """memory_search must prevent very large MCP output from abusive limits."""
        for index in range(120):
            self.db.log_decision(
                title=f"Cache decision {index}",
                chosen="Redis",
            )

        result = self.server._call_memory_search(
            self.db,
            {"query": "cache", "limit": 9999},
        )

        self.assertTrue(result["limit_capped"])
        self.assertEqual(result["requested_limit"], 9999)
        self.assertEqual(result["applied_limit"], 100)
        self.assertLessEqual(result["total"], 100)

    def test_memory_get_decisions_caps_excessive_limit(self):
        """memory_get_decisions must paginate defensively by default."""
        for index in range(205):
            self.db.log_decision(
                title=f"Long decision {index}",
                chosen="SQLite",
            )

        result = self.server._call_memory_get_decisions(
            self.db,
            {"limit": 9999},
        )

        self.assertTrue(result["limit_capped"])
        self.assertEqual(result["requested_limit"], 9999)
        self.assertEqual(result["applied_limit"], 200)
        self.assertEqual(result["total"], 200)

    def test_memory_import_caps_excessive_git_limit(self):
        """memory_import from git must not accept unbounded limits."""
        calls = []

        def fake_import_git_history(repo_path, limit):
            calls.append((repo_path, limit))
            return limit

        self.db.import_git_history = fake_import_git_history

        repo_path = self._project_dir
        result = self.server._call_memory_import(
            self.db,
            {"source": "git", "path": repo_path, "limit": 999999},
        )

        self.assertEqual(calls, [(os.path.realpath(repo_path), 1000)])
        self.assertTrue(result["limit_capped"])
        self.assertEqual(result["requested_limit"], 999999)
        self.assertEqual(result["applied_limit"], 1000)
        self.assertEqual(result["imported"], 1000)

    def test_memory_tool_schemas_expose_limit_bounds(self):
        """The MCP schemas must declare maximums for paginated calls."""
        by_name = {tool["name"]: tool for tool in _TOOLS}

        search_limit = by_name["memory_search"]["inputSchema"]["properties"]["limit"]
        decisions_limit = by_name["memory_get_decisions"]["inputSchema"]["properties"]["limit"]
        import_limit = by_name["memory_import"]["inputSchema"]["properties"]["limit"]

        self.assertEqual(search_limit["maximum"], 100)
        self.assertEqual(decisions_limit["maximum"], 200)
        self.assertEqual(import_limit["maximum"], 1000)
        self.assertEqual(search_limit["minimum"], 1)
        self.assertEqual(decisions_limit["minimum"], 1)
        self.assertEqual(import_limit["minimum"], 1)

    def test_memory_log_decision_with_tags(self):
        """memory_log_decision records the tags correctly."""
        result = self.server._call_memory_log_decision(
            self.db,
            {
                "title": "Decision with tags",
                "chosen": "Option Z",
                "tags": ["api", "backend"],
            },
        )

        self.assertNotIn("error", result)
        dec_id = result["decision_id"]

        decisions = self.db.get_decisions()
        d = [dec for dec in decisions if dec["id"] == dec_id][0]
        tags = json.loads(d["tags"])
        self.assertEqual(tags, ["api", "backend"])

    def test_memory_log_commit_with_files(self):
        """memory_log_commit records the file list correctly."""
        result = self.server._call_memory_log_commit(
            self.db,
            {
                "sha": "test_files_sha_001",
                "message": "feat: new component",
                "files": ["src/app.py", "tests/test_app.py"],
            },
        )

        self.assertNotIn("error", result)
        commit_id = result["commit_id"]
        self.assertIsNotNone(commit_id)

        # Check with direct SQL that the files were saved
        import sqlite3
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT files FROM commits WHERE id = ?", (commit_id,)
        ).fetchone()
        conn.close()

        files = json.loads(row[0])
        self.assertEqual(files, ["src/app.py", "tests/test_app.py"])

    def test_memory_log_commit_accepts_author_and_committed_at(self):
        """memory_log_commit must store the author and the real date."""
        result = self.server._call_memory_log_commit(
            self.db,
            {
                "sha": "test_meta_sha_002",
                "message": "feat: import full metadata",
                "author": "Jane Developer",
                "committed_at": "2024-06-01T12:00:00+00:00",
            },
        )

        self.assertNotIn("error", result)
        commit_id = result["commit_id"]

        import sqlite3
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT author, committed_at FROM commits WHERE id = ?",
            (commit_id,),
        ).fetchone()
        conn.close()

        self.assertEqual(row[0], "Jane Developer")
        self.assertEqual(row[1], "2024-06-01T12:00:00+00:00")

    # --- Test for the total tool count -------------------------------------

    def test_tool_count_is_15(self):
        """The _TOOLS catalog must contain exactly 15 tools."""
        self.assertEqual(len(_TOOLS), 15)


class TestMCPMemoryConfig(unittest.TestCase):
    """Check that the server respects the project config."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._old_cwd = os.getcwd()
        os.chdir(self._tmpdir)
        os.makedirs(".claude", exist_ok=True)
        self._db_path = os.path.join(self._tmpdir, ".claude", "alfred-memory.db")

        with open(
            os.path.join(self._tmpdir, ".claude", "alfred-dev.local.md"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(
                "---\n"
                "memory:\n"
                "  enabled: true\n"
                "  capture_decisions: false\n"
                "  capture_commits: false\n"
                "  retention_days: 42\n"
                "---\n"
            )

        self.server = MemoryMCPServer(db_path=self._db_path)
        self.db = self.server._ensure_db()

    def tearDown(self):
        if self.server._db:
            self.server._db.close()
        os.chdir(self._old_cwd)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_log_decision_respects_capture_flag(self):
        """memory_log_decision is skipped if capture_decisions is false."""
        result = self.server._call_memory_log_decision(
            self.db,
            {"title": "Decision", "chosen": "Option"},
        )

        self.assertTrue(result["skipped"])
        self.assertEqual(self.db.get_decisions(), [])

    def test_log_commit_respects_capture_flag(self):
        """memory_log_commit is skipped if capture_commits is false."""
        result = self.server._call_memory_log_commit(
            self.db,
            {"sha": "abc123", "message": "feat: demo"},
        )

        self.assertTrue(result["skipped"])
        self.assertEqual(self.db.get_commits(), [])

    def test_retention_comes_from_project_config(self):
        """Without an env value, resolve_retention_days uses the project config."""
        os.environ.pop("ALFRED_MEMORY_RETENTION_DAYS", None)
        self.assertEqual(resolve_retention_days(self._tmpdir), 42)


if __name__ == "__main__":
    unittest.main()
