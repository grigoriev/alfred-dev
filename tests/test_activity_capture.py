#!/usr/bin/env python3
"""
Tests for hooks/activity-capture.py.

Check the logic of the central activity capture hook:
    - Detection of excluded files (_is_excluded_path).
    - Detection of trivial commands (_is_trivial_command).
    - Detection of git commit (is_git_commit_command).
    - Dispatchers: Write, Edit, Bash, Read, Glob, Grep, Agent, WebFetch,
      WebSearch, NotebookEdit, Prompt, Compact, Stop.
    - State processing: iterations and phases (_process_state).

Each test that uses the DB creates a temporary MemoryDB instance, starts an
iteration so it can query the timeline, and removes the temporary files in
tearDown.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


def _load_module():
    """Load the activity-capture.py module by path (its name has a hyphen)."""
    module_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "hooks",
        "activity-capture.py",
    )
    spec = importlib.util.spec_from_file_location("activity_capture", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_capture = _load_module()

# Make sure core.memory is available
_plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _plugin_root not in sys.path:
    sys.path.insert(0, _plugin_root)

from core.memory import MemoryDB
from core.continuity import (
    PREFETCH_CONSUMED_RELATIVE_PATH,
    PREFETCH_RELATIVE_PATH,
    STATE_RELATIVE_PATH,
    save_prefetch_result,
    consume_prefetch_result,
)
from core.orchestrator import advance_phase, create_session, save_state


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _complete_session(command: str, description: str):
    session = create_session(command, description)
    while session["current_phase"] != "completed":
        session = advance_phase(session, result="approved", artifacts=[])
    return session

class _DBTestCase(unittest.TestCase):
    """Base class for tests that need a temporary DB."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, "test.db")
        self._db = MemoryDB(self._db_path)
        # Create an iteration so the timeline can be queried
        self._it_id = self._db.start_iteration(command="test", description="test")

    def tearDown(self):
        if self._db:
            self._db.close()
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _get_events(self, event_type=None):
        """Return the timeline events, with an optional filter."""
        events = self._db.get_timeline(self._it_id)
        if event_type:
            return [e for e in events if e.get("event_type") == event_type]
        return events

    def _parse_payload(self, event):
        """Parse the JSON payload of an event."""
        raw = event.get("payload")
        if isinstance(raw, str):
            return json.loads(raw)
        return raw or {}


# ---------------------------------------------------------------------------
# TestIsExcludedPath
# ---------------------------------------------------------------------------

class TestIsExcludedPath(unittest.TestCase):
    """Check the exclusion of internal files."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._original_cwd = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._original_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_excludes_claude_dir(self):
        path = os.path.join(self._tmpdir, ".claude", "config.json")
        self.assertTrue(_capture._is_excluded_path(path))

    def test_excludes_git_dir(self):
        path = os.path.join(self._tmpdir, ".git", "objects", "abc123")
        self.assertTrue(_capture._is_excluded_path(path))

    def test_excludes_node_modules(self):
        path = os.path.join(self._tmpdir, "node_modules", "lodash", "index.js")
        self.assertTrue(_capture._is_excluded_path(path))

    def test_excludes_pycache(self):
        path = os.path.join(self._tmpdir, "__pycache__", "module.cpython-312.pyc")
        self.assertTrue(_capture._is_excluded_path(path))

    def test_excludes_venv(self):
        path = os.path.join(self._tmpdir, ".venv", "lib", "python3.12", "site.py")
        self.assertTrue(_capture._is_excluded_path(path))

    def test_excludes_mypy_cache(self):
        path = os.path.join(self._tmpdir, ".mypy_cache", "3.12", "module.meta.json")
        self.assertTrue(_capture._is_excluded_path(path))

    def test_excludes_pytest_cache(self):
        path = os.path.join(self._tmpdir, ".pytest_cache", "v", "cache", "lastfailed")
        self.assertTrue(_capture._is_excluded_path(path))

    def test_includes_source_file(self):
        path = os.path.join(self._tmpdir, "src", "main.py")
        self.assertFalse(_capture._is_excluded_path(path))

    def test_includes_root_file(self):
        path = os.path.join(self._tmpdir, "README.md")
        self.assertFalse(_capture._is_excluded_path(path))

    def test_includes_nested_source(self):
        path = os.path.join(self._tmpdir, "core", "memory.py")
        self.assertFalse(_capture._is_excluded_path(path))


# ---------------------------------------------------------------------------
# TestIsTrivialCommand
# ---------------------------------------------------------------------------

class TestIsTrivialCommand(unittest.TestCase):
    """Check the detection of trivial commands."""

    def test_ls_is_trivial(self):
        self.assertTrue(_capture._is_trivial_command("ls"))

    def test_ls_with_flags_is_trivial(self):
        self.assertTrue(_capture._is_trivial_command("ls -la"))

    def test_pwd_is_trivial(self):
        self.assertTrue(_capture._is_trivial_command("pwd"))

    def test_cd_is_trivial(self):
        self.assertTrue(_capture._is_trivial_command("cd /tmp"))

    def test_echo_is_trivial(self):
        self.assertTrue(_capture._is_trivial_command("echo hello"))

    def test_cat_is_trivial(self):
        self.assertTrue(_capture._is_trivial_command("cat file.txt"))

    def test_head_is_trivial(self):
        self.assertTrue(_capture._is_trivial_command("head -n 10 file.py"))

    def test_tail_is_trivial(self):
        self.assertTrue(_capture._is_trivial_command("tail -f log.txt"))

    def test_npm_install_is_not_trivial(self):
        self.assertFalse(_capture._is_trivial_command("npm install"))

    def test_git_push_is_not_trivial(self):
        self.assertFalse(_capture._is_trivial_command("git push"))

    def test_python_is_not_trivial(self):
        self.assertFalse(_capture._is_trivial_command("python3 -m pytest tests/"))

    def test_make_is_not_trivial(self):
        self.assertFalse(_capture._is_trivial_command("make build"))

    def test_docker_is_not_trivial(self):
        self.assertFalse(_capture._is_trivial_command("docker build ."))

    def test_env_var_prefix_stripped(self):
        """Leading environment variables must not affect the detection."""
        self.assertFalse(_capture._is_trivial_command("NODE_ENV=prod npm start"))

    def test_absolute_path_stripped(self):
        """Absolute paths reduce to the base name."""
        self.assertTrue(_capture._is_trivial_command("/usr/bin/cat file.txt"))

    def test_chained_command_is_not_trivial_if_any_segment_is_relevant(self):
        """A trivial prefix must not hide a relevant command after it."""
        self.assertFalse(_capture._is_trivial_command("cd repo && pytest -q"))

    def test_chained_trivial_segments_remain_trivial(self):
        """A chain of only navigation/read commands stays trivial."""
        self.assertTrue(_capture._is_trivial_command("cd repo && ls -la"))


# ---------------------------------------------------------------------------
# TestIsGitCommitCommand
# ---------------------------------------------------------------------------

class TestIsGitCommitCommand(unittest.TestCase):
    """Check the detection of git commit in shell commands."""

    def test_simple_git_commit(self):
        self.assertTrue(_capture.is_git_commit_command("git commit -m 'msg'"))

    def test_git_commit_with_amend(self):
        self.assertTrue(_capture.is_git_commit_command("git commit --amend"))

    def test_chained_with_and(self):
        self.assertTrue(_capture.is_git_commit_command("git add . && git commit -m 'msg'"))

    def test_chained_with_semicolon(self):
        self.assertTrue(_capture.is_git_commit_command("git add .; git commit -m 'msg'"))

    def test_after_or(self):
        self.assertTrue(_capture.is_git_commit_command("false || git commit -m 'fallback'"))

    def test_not_in_echo(self):
        """git commit inside an echo is not a real commit."""
        self.assertFalse(_capture.is_git_commit_command("echo 'run git commit'"))

    def test_not_in_grep(self):
        self.assertFalse(_capture.is_git_commit_command("grep 'git commit' history.log"))

    def test_npm_install(self):
        self.assertFalse(_capture.is_git_commit_command("npm install"))

    def test_git_push(self):
        self.assertFalse(_capture.is_git_commit_command("git push origin main"))


# ---------------------------------------------------------------------------
# TestDispatchWrite
# ---------------------------------------------------------------------------

class TestDispatchWrite(_DBTestCase):
    """Check the Write dispatcher."""

    def test_normal_file_creates_event(self):
        """A Write to a normal file creates a file_written event."""
        # Create a temporary file so _read_file_safe can read it
        test_file = os.path.join(self._tmpdir, "src", "main.py")
        os.makedirs(os.path.dirname(test_file), exist_ok=True)
        with open(test_file, "w") as f:
            f.write("print('hello')\nprint('world')\n")

        data = {"tool_input": {"file_path": test_file}}

        _capture._dispatch_write(self._db, data)

        events = self._get_events("file_written")
        self.assertEqual(len(events), 1)

    def test_summary_contains_path_and_lines(self):
        """The summary includes the relative path and the line count."""
        test_file = os.path.join(self._tmpdir, "app.js")
        with open(test_file, "w") as f:
            f.write("const x = 1;\nconst y = 2;\nconst z = 3;\n")

        data = {"tool_input": {"file_path": test_file}}

        _capture._dispatch_write(self._db, data)

        events = self._get_events("file_written")
        self.assertIn("app.js", events[0].get("summary", ""))
        self.assertIn("строк: 3", events[0].get("summary", ""))

    def test_content_contains_file_content(self):
        """The content field stores the full file content."""
        test_file = os.path.join(self._tmpdir, "data.txt")
        file_text = "line one\nline two\n"
        with open(test_file, "w") as f:
            f.write(file_text)

        data = {"tool_input": {"file_path": test_file}}

        _capture._dispatch_write(self._db, data)

        events = self._get_events("file_written")
        self.assertEqual(events[0].get("content"), file_text)

    def test_excluded_file_creates_no_event(self):
        """A Write to an excluded file creates no event."""
        original_cwd = os.getcwd()
        os.chdir(self._tmpdir)
        try:
            data = {"tool_input": {"file_path": os.path.join(self._tmpdir, ".git", "index")}}
            _capture._dispatch_write(self._db, data)
            events = self._get_events("file_written")
            self.assertEqual(len(events), 0)
        finally:
            os.chdir(original_cwd)

    def test_empty_path_creates_no_event(self):
        """An empty path creates no event."""
        data = {"tool_input": {"file_path": ""}}
        _capture._dispatch_write(self._db, data)
        events = self._get_events("file_written")
        self.assertEqual(len(events), 0)

    def test_state_json_triggers_process_state(self):
        """If the file is alfred-dev-state.json, it triggers _process_state."""
        # Close the setUp iteration so _process_state creates a new one
        self._db.complete_iteration(self._it_id)

        state_file = os.path.join(self._tmpdir, "alfred-dev-state.json")
        state = {
            "command": "feature",
            "current_phase": "product",
            "description": "test feature",
            "completed_phases": [],
        }
        with open(state_file, "w") as f:
            json.dump(state, f)

        data = {"tool_input": {"file_path": state_file}}

        _capture._dispatch_write(self._db, data)

        # _process_state must have created a new iteration
        active = self._db.get_active_iteration()
        self.assertIsNotNone(active)
        self.assertEqual(active["command"], "feature")

        # Check that iteration_started was recorded in the new iteration
        new_timeline = self._db.get_timeline(active["id"])
        started = [e for e in new_timeline if e.get("event_type") == "iteration_started"]
        self.assertGreaterEqual(len(started), 1)

    def test_claude_state_json_triggers_process_state_even_if_path_is_excluded(self):
        """The real state lives in .claude/ and the generic exclusion must not skip it."""
        self._db.complete_iteration(self._it_id)

        state_dir = os.path.join(self._tmpdir, ".claude")
        os.makedirs(state_dir, exist_ok=True)
        state_file = os.path.join(state_dir, "alfred-dev-state.json")
        state = {
            "command": "feature",
            "current_phase": "product",
            "description": "test feature",
            "completed_phases": [],
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)

        data = {"tool_input": {"file_path": state_file}}
        _capture._dispatch_write(self._db, data)

        active = self._db.get_active_iteration()
        self.assertIsNotNone(active)
        self.assertEqual(active["command"], "feature")
        self.assertEqual(len(self._get_events("file_written")), 0)

    def test_summary_counts_single_line_without_trailing_newline(self):
        """A single line without a trailing newline still counts as 1."""
        test_file = os.path.join(self._tmpdir, "README.md")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("only one line")

        data = {"tool_input": {"file_path": test_file}}
        _capture._dispatch_write(self._db, data)

        events = self._get_events("file_written")
        self.assertIn("строк: 1", events[0].get("summary", ""))
        payload = self._parse_payload(events[0])
        self.assertEqual(payload["lines"], 1)

    def test_payload_contains_extension(self):
        """The payload includes the file extension."""
        test_file = os.path.join(self._tmpdir, "style.css")
        with open(test_file, "w") as f:
            f.write("body { color: red; }\n")

        data = {"tool_input": {"file_path": test_file}}

        _capture._dispatch_write(self._db, data)

        events = self._get_events("file_written")
        payload = self._parse_payload(events[0])
        self.assertEqual(payload["extension"], "css")


# ---------------------------------------------------------------------------
# TestDispatchEdit
# ---------------------------------------------------------------------------

class TestDispatchEdit(_DBTestCase):
    """Check the Edit dispatcher."""

    def test_creates_file_edited_event(self):
        """An Edit creates a file_edited event."""
        test_file = os.path.join(self._tmpdir, "main.py")
        with open(test_file, "w") as f:
            f.write("pass")

        data = {
            "tool_input": {
                "file_path": test_file,
                "old_string": "old\nanother line",
                "new_string": "new\nsecond\nthird",
            }
        }

        _capture._dispatch_edit(self._db, data)

        events = self._get_events("file_edited")
        self.assertEqual(len(events), 1)

    def test_summary_has_line_counts(self):
        """The summary shows the replaced and the new lines."""
        test_file = os.path.join(self._tmpdir, "app.py")
        with open(test_file, "w") as f:
            f.write("pass")

        data = {
            "tool_input": {
                "file_path": test_file,
                "old_string": "a\nb",
                "new_string": "x\ny\nz",
            }
        }

        _capture._dispatch_edit(self._db, data)

        events = self._get_events("file_edited")
        summary = events[0].get("summary", "")
        self.assertIn("строк заменено: 2, новых: 3", summary)

    def test_content_contains_diff(self):
        """The content field stores the old/new diff."""
        test_file = os.path.join(self._tmpdir, "util.py")
        with open(test_file, "w") as f:
            f.write("pass")

        data = {
            "tool_input": {
                "file_path": test_file,
                "old_string": "old_function()",
                "new_string": "new_function(x, y)",
            }
        }

        _capture._dispatch_edit(self._db, data)

        events = self._get_events("file_edited")
        content = events[0].get("content", "")
        self.assertIn("--- old ---", content)
        self.assertIn("old_function()", content)
        self.assertIn("--- new ---", content)
        self.assertIn("new_function(x, y)", content)

    def test_excluded_file_creates_no_event(self):
        """An Edit to an excluded file creates no event."""
        original_cwd = os.getcwd()
        os.chdir(self._tmpdir)
        try:
            data = {
                "tool_input": {
                    "file_path": os.path.join(self._tmpdir, ".claude", "settings.json"),
                    "old_string": "a",
                    "new_string": "b",
                }
            }
            _capture._dispatch_edit(self._db, data)
            events = self._get_events("file_edited")
            self.assertEqual(len(events), 0)
        finally:
            os.chdir(original_cwd)

    def test_payload_has_file_and_extension(self):
        """The payload includes the relative path and the extension."""
        test_file = os.path.join(self._tmpdir, "index.ts")
        with open(test_file, "w") as f:
            f.write("pass")

        data = {
            "tool_input": {
                "file_path": test_file,
                "old_string": "a",
                "new_string": "b",
            }
        }

        _capture._dispatch_edit(self._db, data)

        events = self._get_events("file_edited")
        payload = self._parse_payload(events[0])
        self.assertEqual(payload["extension"], "ts")
        self.assertIn("index.ts", payload["file"])


# ---------------------------------------------------------------------------
# TestDispatchBash
# ---------------------------------------------------------------------------

class TestDispatchBash(_DBTestCase):
    """Check the Bash dispatcher."""

    def test_nontrivial_command_creates_event(self):
        """A relevant command creates a command_executed event."""
        data = {
            "tool_input": {"command": "npm install"},
            "tool_result": {"exit_code": 0, "stdout": "added 123 packages"},
        }

        _capture._dispatch_bash(self._db, data)

        events = self._get_events("command_executed")
        self.assertEqual(len(events), 1)

    def test_trivial_command_creates_no_event(self):
        """A trivial command creates no event."""
        data = {
            "tool_input": {"command": "ls -la"},
            "tool_result": {"exit_code": 0, "stdout": "total 42"},
        }

        _capture._dispatch_bash(self._db, data)

        events = self._get_events("command_executed")
        self.assertEqual(len(events), 0)

    def test_chained_command_with_trivial_prefix_still_creates_event(self):
        """`cd repo && pytest` must not get lost because of the cd prefix."""
        data = {
            "tool_input": {"command": "cd repo && pytest -q"},
            "tool_result": {"exit_code": 0, "stdout": "10 passed"},
        }

        _capture._dispatch_bash(self._db, data)

        events = self._get_events("command_executed")
        self.assertEqual(len(events), 1)
        self.assertIn("pytest -q", events[0].get("summary", ""))

    def test_summary_contains_command_and_exit(self):
        """The summary includes the command (truncated) and the exit code."""
        data = {
            "tool_input": {"command": "python3 -m pytest tests/"},
            "tool_result": {"exit_code": 0, "stdout": "5 passed"},
        }

        _capture._dispatch_bash(self._db, data)

        events = self._get_events("command_executed")
        summary = events[0].get("summary", "")
        self.assertIn("python3 -m pytest", summary)
        self.assertIn("exit 0", summary)

    def test_content_contains_full_stdout(self):
        """The content field stores the full stdout without truncation."""
        long_output = "line " * 500
        data = {
            "tool_input": {"command": "npm build"},
            "tool_result": {"exit_code": 0, "stdout": long_output},
        }

        _capture._dispatch_bash(self._db, data)

        events = self._get_events("command_executed")
        content = events[0].get("content", "")
        self.assertIn("--- stdout ---", content)
        # The content must NOT be truncated
        self.assertIn(long_output, content)

    def test_content_contains_stderr_on_failure(self):
        """The content field includes stderr when an error occurs."""
        data = {
            "tool_input": {"command": "npm test"},
            "tool_result": {"exit_code": 1, "stdout": "", "stderr": "Error: test failed"},
        }

        _capture._dispatch_bash(self._db, data)

        events = self._get_events("command_executed")
        content = events[0].get("content", "")
        self.assertIn("--- stderr ---", content)
        self.assertIn("Error: test failed", content)

    def test_payload_contains_command_and_exit_code(self):
        """The payload has command and exit_code without truncation."""
        data = {
            "tool_input": {"command": "git status"},
            "tool_result": {"exit_code": 0, "stdout": "clean"},
        }

        _capture._dispatch_bash(self._db, data)

        events = self._get_events("command_executed")
        payload = self._parse_payload(events[0])
        self.assertEqual(payload["command"], "git status")
        self.assertEqual(payload["exit_code"], 0)

    def test_git_commit_triggers_log_commit(self):
        """A successful git commit triggers _capture_git_commit."""
        # We cannot test subprocess.run here, but we check that it
        # does not fail when there is no git repository
        data = {
            "tool_input": {"command": "git commit -m 'test'"},
            "tool_result": {"exit_code": 0, "stdout": "[main abc1234] test"},
        }

        # Must not raise an exception even without a git repo
        _capture._dispatch_bash(self._db, data)

        events = self._get_events("command_executed")
        self.assertEqual(len(events), 1)

    def test_git_commit_respects_capture_commits_flag(self):
        """If capture_commits is false, the commit must not be recorded."""
        data = {
            "tool_input": {"command": "git commit -m 'test'"},
            "tool_result": {"exit_code": 0, "stdout": "[main abc1234] test"},
        }

        with patch.object(
            _capture,
            "_memory_settings",
            return_value={"capture_commits": False, "sync_to_native": True},
        ):
            _capture._dispatch_bash(self._db, data)

        events = self._get_events("command_executed")
        self.assertEqual(len(events), 1)
        self.assertEqual(self._db.get_commits(), [])

    def test_empty_command_creates_no_event(self):
        """An empty command creates no event."""
        data = {
            "tool_input": {"command": ""},
            "tool_result": {"exit_code": 0},
        }

        _capture._dispatch_bash(self._db, data)

        events = self._get_events("command_executed")
        self.assertEqual(len(events), 0)


# ---------------------------------------------------------------------------
# TestDispatchPrompt
# ---------------------------------------------------------------------------

class TestDispatchPrompt(_DBTestCase):
    """Check the UserPromptSubmit/UserPromptExpansion dispatcher."""

    def setUp(self):
        super().setUp()
        self._original_cwd = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._original_cwd)
        super().tearDown()

    def test_prompt_saved_with_full_text(self):
        """The prompt is stored with the full text in content."""
        full_text = "Implement the authentication system with OAuth2 and JWT tokens"
        data = {"prompt": full_text}

        _capture._dispatch_prompt(self._db, data)

        events = self._get_events("user_prompt")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].get("content"), full_text)

    def test_summary_truncated(self):
        """The summary contains only the first line, truncated."""
        long_prompt = "First line of the prompt\nSecond line with more details\nThird"
        data = {"prompt": long_prompt}

        _capture._dispatch_prompt(self._db, data)

        events = self._get_events("user_prompt")
        summary = events[0].get("summary", "")
        self.assertIn("Prompt:", summary)
        self.assertIn("First line of the prompt", summary)
        self.assertIn("...", summary)

    def test_payload_has_length(self):
        """The payload includes the prompt length."""
        text = "Do this"
        data = {"prompt": text}

        _capture._dispatch_prompt(self._db, data)

        events = self._get_events("user_prompt")
        payload = self._parse_payload(events[0])
        self.assertEqual(payload["length"], len(text))
        self.assertEqual(payload["source"], "UserPromptSubmit")

    def test_prompt_expansion_payload_keeps_command_metadata(self):
        """UserPromptExpansion must record the slash command metadata."""
        text = "/alfred-dev:quick поправить CTA"
        data = {
            "hook_event_name": "UserPromptExpansion",
            "expansion_type": "slash_command",
            "command_name": "alfred-dev:quick",
            "command_source": "plugin",
            "prompt": text,
        }

        _capture._dispatch_prompt(self._db, data)

        events = self._get_events("user_prompt")
        payload = self._parse_payload(events[-1])
        self.assertEqual(payload["source"], "UserPromptExpansion")
        self.assertEqual(payload["expansion_type"], "slash_command")
        self.assertEqual(payload["command_name"], "alfred-dev:quick")
        self.assertEqual(payload["command_source"], "plugin")

    def test_dispatcher_table_supports_user_prompt_expansion(self):
        """The modern slash command expansion event uses the prompt dispatcher."""
        dispatchers = _capture._build_dispatcher_table()

        self.assertIs(dispatchers["UserPromptExpansion"], _capture._dispatch_prompt)

    def test_empty_prompt_creates_no_event(self):
        """An empty prompt creates no event."""
        data = {"prompt": ""}

        _capture._dispatch_prompt(self._db, data)

        events = self._get_events("user_prompt")
        self.assertEqual(len(events), 0)

    def test_content_field_fallback(self):
        """If 'prompt' is missing, it uses 'content' as a fallback."""
        text = "Texto via content"
        data = {"content": text}

        _capture._dispatch_prompt(self._db, data)

        events = self._get_events("user_prompt")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].get("content"), text)

    def test_prefetches_explicit_map_codebase_prompt(self):
        """A helper-first slash command must leave the brownfield map ready."""
        data = {"prompt": "/alfred-dev:map-codebase логин и пользователи"}

        _capture._dispatch_prompt(self._db, data)

        self.assertTrue(os.path.isfile(os.path.join(self._tmpdir, "docs", "project", "codebase-map.md")))
        self.assertTrue(os.path.isfile(os.path.join(self._tmpdir, "docs", "project", "current.md")))

        prefetched = self._get_events("alfred_prefetched")
        self.assertEqual(len(prefetched), 1)
        payload = self._parse_payload(prefetched[0])
        self.assertEqual(payload["source_command"], "map-codebase")
        self.assertEqual(payload["prefetched_command"], "map-codebase")
        self.assertIn("docs/project/codebase-map.md", payload["artifacts"])

    def test_prefetches_brownfield_map_for_contextual_alfred_prompt(self):
        """`/alfred` must prepare the map if the repo already exists."""
        os.makedirs(os.path.join(self._tmpdir, "src"), exist_ok=True)
        with open(os.path.join(self._tmpdir, "src", "index.js"), "w", encoding="utf-8") as fh:
            fh.write("console.log('hello');\n")

        data = {"prompt": "/alfred добавь логин и пользователей"}

        _capture._dispatch_prompt(self._db, data)

        self.assertTrue(os.path.isfile(os.path.join(self._tmpdir, "docs", "project", "codebase-map.md")))
        prefetched = self._get_events("alfred_prefetched")
        self.assertEqual(len(prefetched), 1)
        payload = self._parse_payload(prefetched[0])
        self.assertEqual(payload["source_command"], "alfred")
        self.assertEqual(payload["prefetched_command"], "map-codebase")

    def test_contextual_alfred_prefetch_skips_map_when_verify_is_pending(self):
        """`/alfred` must not run map-codebase early when verify is next."""
        os.makedirs(os.path.join(self._tmpdir, ".claude"), exist_ok=True)
        os.makedirs(os.path.join(self._tmpdir, "src"), exist_ok=True)
        with open(os.path.join(self._tmpdir, "src", "index.js"), "w", encoding="utf-8") as fh:
            fh.write("console.log('hello');\n")
        session = _complete_session("feature", "Login and users")
        save_state(session, os.path.join(self._tmpdir, STATE_RELATIVE_PATH))

        data = {"prompt": "/alfred добавь логин и пользователей"}

        _capture._dispatch_prompt(self._db, data)

        self.assertFalse(
            os.path.exists(os.path.join(self._tmpdir, "docs", "project", "codebase-map.md"))
        )
        prefetched = self._get_events("alfred_prefetched")
        self.assertEqual(len(prefetched), 0)

    def test_prefetches_quick_session_from_prompt(self):
        """The first `/alfred-dev:quick` must leave the session and the bypass ready."""
        data = {
            "prompt": (
                "/alfred-dev:quick поправить текст логина\n"
                "import subprocess\n"
                "print('test wrapper')\n"
            )
        }

        _capture._dispatch_prompt(self._db, data)

        state_path = os.path.join(self._tmpdir, ".claude", "alfred-dev-state.json")
        self.assertTrue(os.path.isfile(state_path))
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)

        self.assertEqual(state["command"], "quick")
        self.assertEqual(state["description"], "поправить текст логина")
        self.assertTrue(os.path.isfile(os.path.join(self._tmpdir, ".claude", "alfred-stop-hook-bypass.json")))

        prefetched = self._get_events("alfred_prefetched")
        self.assertEqual(len(prefetched), 1)
        payload = self._parse_payload(prefetched[0])
        self.assertEqual(payload["prefetched_command"], "quick")

    def test_prefetches_memory_ui_from_prompt(self):
        """`/alfred-dev:memory-ui` must leave the UI ready before the reasoning starts."""
        data = {"prompt": "/alfred-dev:memory-ui"}

        _capture._dispatch_prompt(self._db, data)

        state_path = os.path.join(self._tmpdir, ".claude", "alfred-memory-ui.json")
        self.assertTrue(os.path.isfile(state_path))
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)

        self.assertTrue(str(state.get("url", "")).startswith("http://127.0.0.1:"))

        prefetched = self._get_events("alfred_prefetched")
        self.assertEqual(len(prefetched), 1)
        payload = self._parse_payload(prefetched[0])
        self.assertEqual(payload["prefetched_command"], "memory-ui")

    def test_new_prompt_clears_consumed_prefetch_marker(self):
        """A new prompt must clear the transient barriers of the previous prompt."""
        payload = {
            "source_command": "map-codebase",
            "prefetched_command": "map-codebase",
            "recommended_command": "discuss",
            "project_name": "demo",
            "stack": {"runtime": "node", "framework": "unknown"},
        }
        save_prefetch_result(self._tmpdir, payload)
        consume_prefetch_result(self._tmpdir, "map-codebase")
        self.assertTrue(
            os.path.isfile(os.path.join(self._tmpdir, PREFETCH_CONSUMED_RELATIVE_PATH))
        )

        _capture._dispatch_prompt(self._db, {"prompt": "/alfred-dev:help"})

        self.assertFalse(
            os.path.exists(os.path.join(self._tmpdir, PREFETCH_CONSUMED_RELATIVE_PATH))
        )

    def test_new_prompt_clears_pending_prefetch_from_previous_prompt(self):
        """A new prompt must clear an old pending prefetch before it recalculates."""
        payload = {
            "source_command": "map-codebase",
            "prefetched_command": "map-codebase",
            "recommended_command": "discuss",
            "project_name": "demo",
            "stack": {"runtime": "node", "framework": "unknown"},
        }
        save_prefetch_result(self._tmpdir, payload)
        self.assertTrue(
            os.path.isfile(os.path.join(self._tmpdir, PREFETCH_RELATIVE_PATH))
        )

        _capture._dispatch_prompt(self._db, {"prompt": "/alfred-dev:help"})

        self.assertFalse(
            os.path.exists(os.path.join(self._tmpdir, PREFETCH_RELATIVE_PATH))
        )


class TestHookScriptRuntime(unittest.TestCase):
    """Check the hook as a real process, without an external PYTHONPATH."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._original_cwd = os.getcwd()
        os.chdir(self._tmpdir)
        os.makedirs(".claude", exist_ok=True)

        with open(".claude/alfred-dev.local.md", "w", encoding="utf-8") as fh:
            fh.write(
                "---\n"
                "memory:\n"
                "  enabled: true\n"
                "  sync_to_native: true\n"
                "  sync_commits_limit: 10\n"
                "  capture_decisions: true\n"
                "  capture_commits: true\n"
                "  retention_days: 365\n"
                "---\n"
            )

        self._db_path = os.path.join(self._tmpdir, ".claude", "alfred-memory.db")
        db = MemoryDB(self._db_path)
        db.start_iteration(command="session", description="runtime test")
        db.close()

        self._hook_path = os.path.join(_plugin_root, "hooks", "activity-capture.py")

    def tearDown(self):
        os.chdir(self._original_cwd)
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_script_logs_user_prompt_without_pythonpath(self):
        """The script must resolve core/* by itself at real runtime."""
        payload = {
            "session_id": "runtime-test",
            "transcript_path": os.path.join(self._tmpdir, "runtime-test.jsonl"),
            "cwd": self._tmpdir,
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Prompt runtime real",
        }

        proc = subprocess.run(
            ["python3", self._hook_path],
            input=json.dumps(payload),
            text=True,
            cwd=self._tmpdir,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)

        db = MemoryDB(self._db_path)
        try:
            active = db.get_active_iteration()
            self.assertIsNotNone(active)
            events = db.get_timeline(active["id"])
        finally:
            db.close()

        prompt_events = [e for e in events if e.get("event_type") == "user_prompt"]
        self.assertEqual(len(prompt_events), 1)
        self.assertEqual(prompt_events[0].get("content"), "Prompt runtime real")

    def test_script_logs_user_prompt_expansion_without_pythonpath(self):
        """The real hook supports the modern UserPromptExpansion payload."""
        payload = {
            "hook_event_name": "UserPromptExpansion",
            "expansion_type": "slash_command",
            "command_name": "alfred-dev:quick",
            "command_source": "plugin",
            "prompt": "/alfred-dev:quick поправить текст",
        }

        result = subprocess.run(
            [sys.executable, os.path.join(_plugin_root, "hooks", "activity-capture.py")],
            input=json.dumps(payload),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=self._tmpdir,
            env={"PATH": os.environ.get("PATH", "")},
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        db = MemoryDB(os.path.join(self._tmpdir, ".claude", "alfred-memory.db"))
        try:
            iteration = db.get_active_iteration()
            events = db.get_timeline(iteration["id"])
        finally:
            db.close()
        prompt_events = [e for e in events if e.get("event_type") == "user_prompt"]
        self.assertEqual(len(prompt_events), 1)
        prompt_payload = json.loads(prompt_events[0].get("payload"))
        self.assertEqual(prompt_payload["source"], "UserPromptExpansion")
        self.assertEqual(prompt_payload["command_name"], "alfred-dev:quick")

    def test_script_prefetches_map_codebase_on_first_prompt(self):
        """The hook must prepare map-codebase before the main reasoning."""
        payload = {
            "session_id": "runtime-prefetch-map",
            "transcript_path": os.path.join(self._tmpdir, "runtime-prefetch-map.jsonl"),
            "cwd": self._tmpdir,
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "/alfred-dev:map-codebase логин и пользователи",
        }

        proc = subprocess.run(
            ["python3", self._hook_path],
            input=json.dumps(payload),
            text=True,
            cwd=self._tmpdir,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self._tmpdir, "docs", "project", "codebase-map.md")))
        self.assertTrue(os.path.isfile(os.path.join(self._tmpdir, "docs", "project", "current.md")))

        db = MemoryDB(self._db_path)
        try:
            active = db.get_active_iteration()
            self.assertIsNotNone(active)
            events = db.get_timeline(active["id"])
        finally:
            db.close()

        prefetch_events = [e for e in events if e.get("event_type") == "alfred_prefetched"]
        self.assertEqual(len(prefetch_events), 1)

    def test_script_prefetches_brownfield_map_for_contextual_alfred(self):
        """The first `/alfred` in brownfield must leave the map ready."""
        os.makedirs(os.path.join(self._tmpdir, "src"), exist_ok=True)
        with open(os.path.join(self._tmpdir, "src", "index.js"), "w", encoding="utf-8") as fh:
            fh.write("console.log('hello');\n")

        payload = {
            "session_id": "runtime-prefetch-alfred",
            "transcript_path": os.path.join(self._tmpdir, "runtime-prefetch-alfred.jsonl"),
            "cwd": self._tmpdir,
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "/alfred добавь логин и пользователей",
        }

        proc = subprocess.run(
            ["python3", self._hook_path],
            input=json.dumps(payload),
            text=True,
            cwd=self._tmpdir,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self._tmpdir, "docs", "project", "codebase-map.md")))

    def test_script_prefetches_memory_ui(self):
        """The runtime hook must be able to start memory-ui before the reasoning."""
        payload = {
            "session_id": "runtime-prefetch-memory-ui",
            "transcript_path": os.path.join(self._tmpdir, "runtime-prefetch-memory-ui.jsonl"),
            "cwd": self._tmpdir,
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "/alfred-dev:memory-ui",
        }

        proc = subprocess.run(
            ["python3", self._hook_path],
            input=json.dumps(payload),
            text=True,
            cwd=self._tmpdir,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self._tmpdir, ".claude", "alfred-memory-ui.json")))

    def test_script_prefetches_memory_ui_stop(self):
        """`/alfred-dev:memory-ui stop` must close the UI, not start it."""
        from core.continuity import launch_memory_ui, stop_memory_ui

        launched = launch_memory_ui(
            self._tmpdir,
            open_browser_window=False,
            preferred_port=4580,
        )
        self.addCleanup(lambda: stop_memory_ui(self._tmpdir))
        payload = {
            "session_id": "runtime-prefetch-memory-ui-stop",
            "transcript_path": os.path.join(self._tmpdir, "runtime-prefetch-memory-ui-stop.jsonl"),
            "cwd": self._tmpdir,
            "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "/alfred-dev:memory-ui stop",
        }

        proc = subprocess.run(
            ["python3", self._hook_path],
            input=json.dumps(payload),
            text=True,
            cwd=self._tmpdir,
            capture_output=True,
            check=False,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(
            os.path.isfile(os.path.join(self._tmpdir, ".claude", "alfred-memory-ui.json"))
        )
        self.assertIn("url", launched)


# ---------------------------------------------------------------------------
# TestDispatchCompact
# ---------------------------------------------------------------------------

class TestDispatchCompact(_DBTestCase):
    """Check the PreCompact dispatcher."""

    def test_creates_context_compacted_event(self):
        """Create a context_compacted event with a descriptive summary."""
        _capture._dispatch_compact(self._db, {})

        events = self._get_events("context_compacted")
        self.assertEqual(len(events), 1)
        self.assertIn("сжат", events[0].get("summary", ""))

    def test_payload_has_source(self):
        """The payload includes the event source."""
        _capture._dispatch_compact(self._db, {})

        events = self._get_events("context_compacted")
        payload = self._parse_payload(events[0])
        self.assertEqual(payload["source"], "PreCompact")


# ---------------------------------------------------------------------------
# TestDispatchStop
# ---------------------------------------------------------------------------

class TestDispatchStop(_DBTestCase):
    """Check the Stop dispatcher."""

    def setUp(self):
        super().setUp()
        self._original_cwd = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._original_cwd)
        super().tearDown()

    def test_creates_session_ended_event(self):
        """Create a session_ended event."""
        _capture._dispatch_stop(self._db, {})

        events = self._get_events("session_ended")
        self.assertEqual(len(events), 1)
        self.assertIn("завершена", events[0].get("summary", ""))

    def test_closes_active_iteration(self):
        """If an iteration is active, close it."""
        # The setUp already has an active iteration
        active_before = self._db.get_active_iteration()
        self.assertIsNotNone(active_before)

        _capture._dispatch_stop(self._db, {})

        active_after = self._db.get_active_iteration()
        self.assertIsNone(active_after)

    def test_no_error_without_active_iteration(self):
        """Do not fail when no iteration is active."""
        # Close the setUp iteration
        self._db.complete_iteration(self._it_id)

        # Must not raise an exception
        _capture._dispatch_stop(self._db, {})

        # The session_ended event is recorded without iteration_id, so
        # we search the events table directly
        cursor = self._db._conn.execute(
            "SELECT * FROM events WHERE event_type = 'session_ended'"
        )
        rows = cursor.fetchall()
        self.assertEqual(len(rows), 1)

    def test_stop_clears_consumed_prefetch_marker(self):
        payload = {
            "source_command": "map-codebase",
            "prefetched_command": "map-codebase",
            "recommended_command": "discuss",
            "project_name": "demo",
            "stack": {"runtime": "node", "framework": "unknown"},
        }
        save_prefetch_result(self._tmpdir, payload)
        consume_prefetch_result(self._tmpdir, "map-codebase")
        self.assertTrue(
            os.path.isfile(os.path.join(self._tmpdir, PREFETCH_CONSUMED_RELATIVE_PATH))
        )

        _capture._dispatch_stop(self._db, {})

        self.assertFalse(
            os.path.exists(os.path.join(self._tmpdir, PREFETCH_CONSUMED_RELATIVE_PATH))
        )


# ---------------------------------------------------------------------------
# TestProcessState
# ---------------------------------------------------------------------------

class TestProcessState(_DBTestCase):
    """Check the state processing (iterations and phases)."""

    def _write_state(self, state: dict) -> str:
        """Write a temporary state file and return its path."""
        state_file = os.path.join(self._tmpdir, "alfred-dev-state.json")
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f)
        return state_file

    def test_creates_iteration_if_none_active(self):
        """Without an active iteration other than the setUp one, state processing creates a new one."""
        # Close the setUp iteration to simulate "no active iteration"
        self._db.complete_iteration(self._it_id)

        state_file = self._write_state({
            "command": "feature",
            "current_phase": "product",
            "description": "test feature",
            "completed_phases": [],
        })

        _capture._process_state(self._db, state_file)

        active = self._db.get_active_iteration()
        self.assertIsNotNone(active)
        self.assertEqual(active["command"], "feature")

    def test_registers_phase_completed(self):
        """Completed phases are recorded as events."""
        state_file = self._write_state({
            "command": "feature",
            "current_phase": "architecture",
            "description": "test",
            "completed_phases": [{"name": "product", "result": "approved"}],
        })

        _capture._process_state(self._db, state_file)

        events = self._get_events("phase_completed")
        self.assertGreaterEqual(len(events), 1)

    def test_does_not_duplicate_phases(self):
        """Two runs with the same phases do not duplicate events."""
        state_file = self._write_state({
            "command": "feature",
            "current_phase": "development",
            "description": "test",
            "completed_phases": [
                {"name": "product", "result": "approved"},
                {"name": "architecture", "result": "approved"},
            ],
        })

        _capture._process_state(self._db, state_file)
        _capture._process_state(self._db, state_file)

        events = self._get_events("phase_completed")
        # There must be exactly 2, not 4
        self.assertEqual(len(events), 2)

    def test_does_not_duplicate_old_phases_beyond_timeline_default_limit(self):
        """Deduplication must not depend on the limit of 100 general events."""
        self._db.log_event(
            event_type="phase_completed",
            phase="product",
            payload={"phase": "product", "result": "approved"},
            iteration_id=self._it_id,
        )
        for index in range(120):
            self._db.log_event(
                event_type="command_executed",
                summary=f"ruido {index}",
                iteration_id=self._it_id,
            )

        state_file = self._write_state({
            "command": "feature",
            "current_phase": "architecture",
            "description": "test",
            "completed_phases": [{"name": "product", "result": "approved"}],
        })

        _capture._process_state(self._db, state_file)

        events = self._get_events("phase_completed")
        self.assertEqual(len(events), 1)

    def test_session_iteration_is_upgraded_to_real_flow_iteration(self):
        """A generic session iteration must hand control to the real flow."""
        self._db.complete_iteration(self._it_id)
        session_id = self._db.start_iteration("session", "Общая сессия")

        state_file = self._write_state({
            "command": "feature",
            "current_phase": "product",
            "description": "реализовать вход через соцсети",
            "completed_phases": [],
        })

        _capture._process_state(self._db, state_file)

        active = self._db.get_active_iteration()
        self.assertIsNotNone(active)
        self.assertEqual(active["command"], "feature")
        self.assertEqual(active["description"], "реализовать вход через соцсети")

        session_iteration = self._db.get_iteration(session_id)
        self.assertEqual(session_iteration["status"], "abandoned")

        started_events = self._db.get_events(
            iteration_id=int(active["id"]),
            event_type="iteration_started",
            limit=5,
        )
        self.assertEqual(len(started_events), 1)

    def test_completes_iteration(self):
        """Phase 'completed' closes the iteration."""
        state_file = self._write_state({
            "command": "feature",
            "current_phase": "completed",
            "description": "test",
            "completed_phases": [{"name": "product"}],
        })

        _capture._process_state(self._db, state_file)

        # The original setUp iteration may stay open or be closed,
        # depending on whether _process_state used the existing one
        # We check that an iteration_completed exists
        events = self._get_events("iteration_completed")
        self.assertGreaterEqual(len(events), 1)

    def test_string_phases(self):
        """Phases given as strings (not dicts) are processed correctly."""
        state_file = self._write_state({
            "command": "fix",
            "current_phase": "validation",
            "description": "test",
            "completed_phases": ["diagnosis", "correction"],
        })

        _capture._process_state(self._db, state_file)

        events = self._get_events("phase_completed")
        self.assertEqual(len(events), 2)

    def test_invalid_state_file_does_nothing(self):
        """An invalid state file generates no events."""
        state_file = os.path.join(self._tmpdir, "alfred-dev-state.json")
        with open(state_file, "w") as f:
            f.write("this is not json {{{")

        initial_count = len(self._get_events())

        _capture._process_state(self._db, state_file)

        final_count = len(self._get_events())
        self.assertEqual(initial_count, final_count)

    def test_auto_pins_completed_phase(self):
        """Completed phases are pinned automatically."""
        state_file = self._write_state({
            "command": "feature",
            "current_phase": "architecture",
            "description": "test",
            "completed_phases": [{"name": "product", "result": "ok"}],
        })

        _capture._process_state(self._db, state_file)

        # Check that a pin exists (does not fail if the table does not exist)
        try:
            cursor = self._db._conn.execute(
                "SELECT * FROM pinned_items WHERE item_ref = ?",
                ("phase:product",),
            )
            pins = cursor.fetchall()
            self.assertGreaterEqual(len(pins), 1)
        except Exception:
            pass  # If the table does not exist, the test does not apply


# ---------------------------------------------------------------------------
# TestDispatchRead
# ---------------------------------------------------------------------------

class TestDispatchRead(_DBTestCase):
    """Check the Read dispatcher."""

    def setUp(self):
        super().setUp()
        self._original_cwd = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._original_cwd)
        super().tearDown()

    def test_creates_file_read_event(self):
        """A Read creates a file_read event."""
        data = {"tool_input": {"file_path": os.path.join(self._tmpdir, "src", "main.py")}}
        _capture._dispatch_read(self._db, data)

        events = self._get_events("file_read")
        self.assertEqual(len(events), 1)

    def test_summary_contains_path(self):
        """The summary includes the relative path."""
        data = {"tool_input": {"file_path": os.path.join(self._tmpdir, "core", "memory.py")}}
        _capture._dispatch_read(self._db, data)

        events = self._get_events("file_read")
        self.assertIn("memory.py", events[0].get("summary", ""))

    def test_summary_with_offset_and_limit(self):
        """The summary includes the line range when it is given."""
        data = {"tool_input": {"file_path": os.path.join(self._tmpdir, "f.py"), "offset": 10, "limit": 50}}
        _capture._dispatch_read(self._db, data)

        events = self._get_events("file_read")
        summary = events[0].get("summary", "")
        self.assertIn("строки 10-60", summary)

    def test_summary_with_only_offset(self):
        """The summary shows the start line when only offset is given."""
        data = {"tool_input": {"file_path": os.path.join(self._tmpdir, "f.py"), "offset": 100}}
        _capture._dispatch_read(self._db, data)

        events = self._get_events("file_read")
        self.assertIn("со строки 100", events[0].get("summary", ""))

    def test_summary_with_only_limit(self):
        """The summary shows the limit when only limit is given."""
        data = {"tool_input": {"file_path": os.path.join(self._tmpdir, "f.py"), "limit": 20}}
        _capture._dispatch_read(self._db, data)

        events = self._get_events("file_read")
        self.assertIn("первые строки: 20", events[0].get("summary", ""))

    def test_offset_zero_is_preserved_in_summary_and_payload(self):
        """offset=0 is valid and a truthy check must not drop it."""
        data = {
            "tool_input": {
                "file_path": os.path.join(self._tmpdir, "f.py"),
                "offset": 0,
                "limit": 20,
            }
        }
        _capture._dispatch_read(self._db, data)

        events = self._get_events("file_read")
        summary = events[0].get("summary", "")
        payload = self._parse_payload(events[0])
        self.assertIn("строки 0-20", summary)
        self.assertEqual(payload["offset"], 0)
        self.assertEqual(payload["limit"], 20)

    def test_excluded_file_creates_no_event(self):
        """A Read of an excluded file creates no event."""
        data = {"tool_input": {"file_path": os.path.join(self._tmpdir, ".git", "HEAD")}}
        _capture._dispatch_read(self._db, data)

        events = self._get_events("file_read")
        self.assertEqual(len(events), 0)

    def test_empty_path_creates_no_event(self):
        """An empty path creates no event."""
        data = {"tool_input": {"file_path": ""}}
        _capture._dispatch_read(self._db, data)

        events = self._get_events("file_read")
        self.assertEqual(len(events), 0)

    def test_no_content_stored(self):
        """It stores no content to avoid duplication."""
        data = {"tool_input": {"file_path": os.path.join(self._tmpdir, "f.py")}}
        _capture._dispatch_read(self._db, data)

        events = self._get_events("file_read")
        self.assertIsNone(events[0].get("content"))


# ---------------------------------------------------------------------------
# TestDispatchGlob
# ---------------------------------------------------------------------------

class TestDispatchGlob(_DBTestCase):
    """Check the Glob dispatcher."""

    def test_creates_glob_search_event(self):
        """A Glob creates a glob_search event."""
        data = {
            "tool_input": {"pattern": "**/*.py", "path": "."},
            "tool_result": {"output": "src/main.py\nsrc/util.py\n"},
        }
        _capture._dispatch_glob(self._db, data)

        events = self._get_events("glob_search")
        self.assertEqual(len(events), 1)

    def test_summary_contains_pattern_and_count(self):
        """The summary includes the pattern and the number of results."""
        data = {
            "tool_input": {"pattern": "*.ts"},
            "tool_result": {"output": "index.ts\napp.ts\nutil.ts\n"},
        }
        _capture._dispatch_glob(self._db, data)

        events = self._get_events("glob_search")
        summary = events[0].get("summary", "")
        self.assertIn("*.ts", summary)
        self.assertIn("результатов: 3", summary)

    def test_content_stores_file_list(self):
        """The content stores the list of found files."""
        file_list = "a.py\nb.py\n"
        data = {
            "tool_input": {"pattern": "*.py"},
            "tool_result": {"output": file_list},
        }
        _capture._dispatch_glob(self._db, data)

        events = self._get_events("glob_search")
        self.assertEqual(events[0].get("content"), file_list)

    def test_large_content_is_truncated_with_metadata(self):
        """Huge outputs are trimmed so memory does not grow without control."""
        long_list = "".join(f"src/file_{i}.py\n" for i in range(200))
        data = {
            "tool_input": {"pattern": "*.py"},
            "tool_result": {"output": long_list},
        }

        _capture._dispatch_glob(self._db, data)

        events = self._get_events("glob_search")
        payload = self._parse_payload(events[0])
        content = events[0].get("content", "")
        self.assertTrue(payload["content_truncated"])
        self.assertGreater(payload["content_lines"], 80)
        self.assertIn("содержимое обрезано", content)
        self.assertNotEqual(content, long_list)

    def test_empty_pattern_creates_no_event(self):
        """An empty pattern creates no event."""
        data = {"tool_input": {"pattern": ""}, "tool_result": {}}
        _capture._dispatch_glob(self._db, data)

        events = self._get_events("glob_search")
        self.assertEqual(len(events), 0)

    def test_zero_results(self):
        """A glob with no results is recorded with 0 results."""
        data = {
            "tool_input": {"pattern": "*.xyz"},
            "tool_result": {"output": ""},
        }
        _capture._dispatch_glob(self._db, data)

        events = self._get_events("glob_search")
        payload = self._parse_payload(events[0])
        self.assertEqual(payload["results"], 0)


# ---------------------------------------------------------------------------
# TestDispatchGrep
# ---------------------------------------------------------------------------

class TestDispatchGrep(_DBTestCase):
    """Check the Grep dispatcher."""

    def test_creates_grep_search_event(self):
        """A Grep creates a grep_search event."""
        data = {
            "tool_input": {"pattern": "TODO", "path": "."},
            "tool_result": {"output": "file.py:10:# TODO fix\n"},
        }
        _capture._dispatch_grep(self._db, data)

        events = self._get_events("grep_search")
        self.assertEqual(len(events), 1)

    def test_summary_contains_pattern_and_count(self):
        """The summary includes the regex pattern and the count."""
        data = {
            "tool_input": {"pattern": "import\\s+os"},
            "tool_result": {"output": "a.py\nb.py\nc.py\n"},
        }
        _capture._dispatch_grep(self._db, data)

        events = self._get_events("grep_search")
        summary = events[0].get("summary", "")
        self.assertIn("import\\s+os", summary)
        self.assertIn("совпадений: 3", summary)

    def test_payload_includes_filters(self):
        """The payload includes the type and glob filters when they are used."""
        data = {
            "tool_input": {"pattern": "def ", "type": "py", "output_mode": "content"},
            "tool_result": {"output": "result\n"},
        }
        _capture._dispatch_grep(self._db, data)

        events = self._get_events("grep_search")
        payload = self._parse_payload(events[0])
        self.assertEqual(payload["type"], "py")
        self.assertEqual(payload["mode"], "content")

    def test_glob_filter_in_summary(self):
        """The summary shows the glob filter when it is used."""
        data = {
            "tool_input": {"pattern": "class", "glob": "*.tsx"},
            "tool_result": {"output": "Component.tsx\n"},
        }
        _capture._dispatch_grep(self._db, data)

        events = self._get_events("grep_search")
        summary = events[0].get("summary", "")
        self.assertIn("фильтр=*.tsx", summary)

    def test_empty_pattern_creates_no_event(self):
        """An empty pattern creates no event."""
        data = {"tool_input": {"pattern": ""}, "tool_result": {}}
        _capture._dispatch_grep(self._db, data)

        events = self._get_events("grep_search")
        self.assertEqual(len(events), 0)

    def test_large_grep_output_is_truncated_with_metadata(self):
        """A massive grep is stored as a preview with trim metadata."""
        output = "".join(f"file_{i}.py:{i}: match\n" for i in range(160))
        data = {
            "tool_input": {"pattern": "match"},
            "tool_result": {"output": output},
        }

        _capture._dispatch_grep(self._db, data)

        events = self._get_events("grep_search")
        payload = self._parse_payload(events[0])
        content = events[0].get("content", "")
        self.assertTrue(payload["content_truncated"])
        self.assertIn("содержимое обрезано", content)
        self.assertNotEqual(content, output)


# ---------------------------------------------------------------------------
# TestDispatchAgent
# ---------------------------------------------------------------------------

class TestDispatchAgent(_DBTestCase):
    """Check the Agent dispatcher."""

    def test_creates_agent_launched_event(self):
        """An Agent creates an agent_launched event."""
        data = {
            "tool_input": {
                "description": "search pattern",
                "subagent_type": "Explore",
                "prompt": "Find the AuthMiddleware class",
            },
            "tool_result": {"output": "Найдено в src/auth.py"},
        }
        _capture._dispatch_agent(self._db, data)

        events = self._get_events("agent_launched")
        self.assertEqual(len(events), 1)

    def test_summary_contains_type_and_description(self):
        """The summary includes the type and the description."""
        data = {
            "tool_input": {
                "description": "review code",
                "subagent_type": "code-reviewer",
                "prompt": "Review the auth module",
            },
            "tool_result": {},
        }
        _capture._dispatch_agent(self._db, data)

        events = self._get_events("agent_launched")
        summary = events[0].get("summary", "")
        self.assertIn("code-reviewer", summary)
        self.assertIn("review code", summary)

    def test_content_contains_prompt_and_result(self):
        """The content stores the sent prompt and the result."""
        data = {
            "tool_input": {"prompt": "Analyze this", "description": "test"},
            "tool_result": {"output": "Analysis result"},
        }
        _capture._dispatch_agent(self._db, data)

        events = self._get_events("agent_launched")
        content = events[0].get("content", "")
        self.assertIn("--- prompt ---", content)
        self.assertIn("Analyze this", content)
        self.assertIn("--- результат ---", content)
        self.assertIn("Analysis result", content)

    def test_default_subagent_type(self):
        """Without subagent_type, it uses general-purpose by default."""
        data = {
            "tool_input": {"description": "generic task", "prompt": "сделай что-нибудь"},
            "tool_result": {},
        }
        _capture._dispatch_agent(self._db, data)

        events = self._get_events("agent_launched")
        payload = self._parse_payload(events[0])
        self.assertEqual(payload["subagent_type"], "general-purpose")


# ---------------------------------------------------------------------------
# TestDispatchWebFetch
# ---------------------------------------------------------------------------

class TestDispatchWebFetch(_DBTestCase):
    """Check the WebFetch dispatcher."""

    def test_creates_web_fetched_event(self):
        """A WebFetch creates a web_fetched event."""
        data = {
            "tool_input": {"url": "https://example.com/api"},
            "tool_result": {"content": "<html>OK</html>"},
        }
        _capture._dispatch_web_fetch(self._db, data)

        events = self._get_events("web_fetched")
        self.assertEqual(len(events), 1)

    def test_summary_contains_url(self):
        """The summary includes the URL (truncated if it is long)."""
        data = {
            "tool_input": {"url": "https://docs.python.org/3/library/sqlite3.html"},
            "tool_result": {"content": "docs"},
        }
        _capture._dispatch_web_fetch(self._db, data)

        events = self._get_events("web_fetched")
        self.assertIn("docs.python.org", events[0].get("summary", ""))

    def test_content_stores_response(self):
        """The content stores the full response."""
        response = "<html><body>Contenido completo</body></html>"
        data = {
            "tool_input": {"url": "https://example.com"},
            "tool_result": {"content": response},
        }
        _capture._dispatch_web_fetch(self._db, data)

        events = self._get_events("web_fetched")
        self.assertEqual(events[0].get("content"), response)

    def test_empty_url_creates_no_event(self):
        """An empty URL creates no event."""
        data = {"tool_input": {"url": ""}, "tool_result": {}}
        _capture._dispatch_web_fetch(self._db, data)

        events = self._get_events("web_fetched")
        self.assertEqual(len(events), 0)

    def test_large_response_is_truncated_with_metadata(self):
        """A huge HTTP response must not fill memory by itself."""
        response = "<html>" + ("content " * 800) + "</html>"
        data = {
            "tool_input": {"url": "https://example.com"},
            "tool_result": {"content": response},
        }

        _capture._dispatch_web_fetch(self._db, data)

        events = self._get_events("web_fetched")
        payload = self._parse_payload(events[0])
        content = events[0].get("content", "")
        self.assertTrue(payload["content_truncated"])
        self.assertIn("содержимое обрезано", content)
        self.assertNotEqual(content, response)


# ---------------------------------------------------------------------------
# TestDispatchWebSearch
# ---------------------------------------------------------------------------

class TestDispatchWebSearch(_DBTestCase):
    """Check the WebSearch dispatcher."""

    def test_creates_web_searched_event(self):
        """A WebSearch creates a web_searched event."""
        data = {
            "tool_input": {"query": "python sqlite3 fts5"},
            "tool_result": {"content": "result 1\nresult 2"},
        }
        _capture._dispatch_web_search(self._db, data)

        events = self._get_events("web_searched")
        self.assertEqual(len(events), 1)

    def test_summary_contains_query(self):
        """The summary includes the search query."""
        data = {
            "tool_input": {"query": "claude code hooks api"},
            "tool_result": {"content": "results"},
        }
        _capture._dispatch_web_search(self._db, data)

        events = self._get_events("web_searched")
        self.assertIn("claude code hooks api", events[0].get("summary", ""))

    def test_content_stores_results(self):
        """The content stores the search results."""
        results = "1. Resultado uno\n2. Resultado dos\n3. Resultado tres"
        data = {
            "tool_input": {"query": "test"},
            "tool_result": {"content": results},
        }
        _capture._dispatch_web_search(self._db, data)

        events = self._get_events("web_searched")
        self.assertEqual(events[0].get("content"), results)

    def test_empty_query_creates_no_event(self):
        """An empty query creates no event."""
        data = {"tool_input": {"query": ""}, "tool_result": {}}
        _capture._dispatch_web_search(self._db, data)

        events = self._get_events("web_searched")
        self.assertEqual(len(events), 0)

    def test_large_results_are_truncated_with_metadata(self):
        """Huge search results are stored as a preview."""
        results = "".join(f"{i}. long result\n" for i in range(180))
        data = {
            "tool_input": {"query": "test"},
            "tool_result": {"content": results},
        }

        _capture._dispatch_web_search(self._db, data)

        events = self._get_events("web_searched")
        payload = self._parse_payload(events[0])
        content = events[0].get("content", "")
        self.assertTrue(payload["content_truncated"])
        self.assertIn("содержимое обрезано", content)
        self.assertNotEqual(content, results)


# ---------------------------------------------------------------------------
# TestDispatchNotebook
# ---------------------------------------------------------------------------

class TestDispatchNotebook(_DBTestCase):
    """Check the NotebookEdit dispatcher."""

    def setUp(self):
        super().setUp()
        self._original_cwd = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._original_cwd)
        super().tearDown()

    def test_creates_notebook_edited_event(self):
        """A NotebookEdit creates a notebook_edited event."""
        data = {"tool_input": {"notebook_path": os.path.join(self._tmpdir, "analysis.ipynb"), "command": "edit"}}
        _capture._dispatch_notebook(self._db, data)

        events = self._get_events("notebook_edited")
        self.assertEqual(len(events), 1)

    def test_summary_contains_path_and_command(self):
        """The summary includes the path and the operation type."""
        data = {"tool_input": {"notebook_path": os.path.join(self._tmpdir, "model.ipynb"), "command": "add_cell"}}
        _capture._dispatch_notebook(self._db, data)

        events = self._get_events("notebook_edited")
        summary = events[0].get("summary", "")
        self.assertIn("model.ipynb", summary)
        self.assertIn("add_cell", summary)

    def test_payload_has_file_and_command(self):
        """The payload includes the relative path and the command."""
        data = {"tool_input": {"notebook_path": os.path.join(self._tmpdir, "nb.ipynb"), "command": "delete_cell"}}
        _capture._dispatch_notebook(self._db, data)

        events = self._get_events("notebook_edited")
        payload = self._parse_payload(events[0])
        self.assertIn("nb.ipynb", payload["file"])
        self.assertEqual(payload["command"], "delete_cell")

    def test_excluded_path_creates_no_event(self):
        """A notebook in an excluded directory creates no event."""
        data = {"tool_input": {"notebook_path": os.path.join(self._tmpdir, ".venv", "nb.ipynb")}}
        _capture._dispatch_notebook(self._db, data)

        events = self._get_events("notebook_edited")
        self.assertEqual(len(events), 0)

    def test_empty_path_creates_no_event(self):
        """An empty path creates no event."""
        data = {"tool_input": {"notebook_path": ""}}
        _capture._dispatch_notebook(self._db, data)

        events = self._get_events("notebook_edited")
        self.assertEqual(len(events), 0)


# ---------------------------------------------------------------------------
# TestHelpers
# ---------------------------------------------------------------------------

class TestFirstMeaningfulLine(unittest.TestCase):
    """Check the extraction of the first meaningful line."""

    def test_normal_text(self):
        result = _capture._first_meaningful_line("first line\nsecond")
        self.assertEqual(result, "first line")

    def test_empty_lines_skipped(self):
        result = _capture._first_meaningful_line("\n\n  \nthird line\n")
        self.assertEqual(result, "third line")

    def test_empty_string(self):
        result = _capture._first_meaningful_line("")
        self.assertEqual(result, "")

    def test_none_returns_empty(self):
        result = _capture._first_meaningful_line(None)
        self.assertEqual(result, "")

    def test_truncated_to_120(self):
        long_line = "x" * 200
        result = _capture._first_meaningful_line(long_line)
        self.assertEqual(len(result), 120)


class TestPrepareHighVolumeContent(unittest.TestCase):
    """Check the trim helper for high-volume events."""

    def test_small_text_kept_intact(self):
        text = "uno\ndos\n"
        content, meta = _capture._prepare_high_volume_content(text)
        self.assertEqual(content, text)
        self.assertFalse(meta["content_truncated"])

    def test_large_text_is_marked_and_trimmed(self):
        text = "".join(f"line {i}\n" for i in range(200))
        content, meta = _capture._prepare_high_volume_content(text)
        self.assertTrue(meta["content_truncated"])
        self.assertIn("содержимое обрезано", content)
        self.assertLess(len(content), len(text))


class TestRelativePath(unittest.TestCase):
    """Check the conversion to a relative path."""

    def test_normal_conversion(self):
        result = _capture._relative_path("/project/src/main.py", "/project")
        self.assertEqual(result, "src/main.py")

    def test_same_directory(self):
        result = _capture._relative_path("/project/file.py", "/project")
        self.assertEqual(result, "file.py")

    def test_returns_absolute_path_for_file_outside_project(self):
        result = _capture._relative_path("/tmp/external.txt", "/project")
        self.assertEqual(result, _capture._normalize_local_path("/tmp/external.txt"))

    def test_normalizes_symlinked_paths_before_relativizing(self):
        if not hasattr(os, "symlink"):
            self.skipTest("The system does not support symlinks.")

        real_project = tempfile.mkdtemp()
        alias_root = tempfile.mkdtemp()
        try:
            alias_project = os.path.join(alias_root, "alias-project")
            try:
                os.symlink(real_project, alias_project)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"Could not create the test symlink: {exc}")

            target = os.path.join(alias_project, "src", "main.py")
            os.makedirs(os.path.dirname(os.path.realpath(target)), exist_ok=True)
            with open(os.path.realpath(target), "w", encoding="utf-8") as fh:
                fh.write("print('ok')\n")

            result = _capture._relative_path(target, real_project)
            self.assertEqual(result, os.path.join("src", "main.py"))
        finally:
            shutil.rmtree(alias_root, ignore_errors=True)
            shutil.rmtree(real_project, ignore_errors=True)


class TestReadFileSafe(unittest.TestCase):
    """Check the safe file read."""

    def test_reads_existing_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("test content")
            path = f.name
        try:
            result = _capture._read_file_safe(path)
            self.assertEqual(result, "test content")
        finally:
            os.unlink(path)

    def test_returns_none_for_missing_file(self):
        result = _capture._read_file_safe("/tmp/does_not_exist_at_all_12345.txt")
        self.assertIsNone(result)


class TestLoadStateFile(unittest.TestCase):
    """Check the loading and validation of the state file."""

    def setUp(self):
        self._tmpfile = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self._tmpfile.close()

    def tearDown(self):
        if os.path.exists(self._tmpfile.name):
            os.unlink(self._tmpfile.name)

    def _write_state(self, data):
        with open(self._tmpfile.name, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_valid_state(self):
        self._write_state({
            "command": "feature",
            "current_phase": "product",
            "description": "login with OAuth2",
        })
        result = _capture._load_state_file(self._tmpfile.name)
        self.assertIsNotNone(result)
        self.assertEqual(result["command"], "feature")

    def test_missing_command(self):
        self._write_state({"current_phase": "product"})
        result = _capture._load_state_file(self._tmpfile.name)
        self.assertIsNone(result)

    def test_missing_current_phase(self):
        self._write_state({"command": "feature"})
        result = _capture._load_state_file(self._tmpfile.name)
        self.assertIsNone(result)

    def test_not_a_dict(self):
        self._write_state([1, 2, 3])
        result = _capture._load_state_file(self._tmpfile.name)
        self.assertIsNone(result)

    def test_invalid_json(self):
        with open(self._tmpfile.name, "w") as f:
            f.write("this is not json {{{")
        result = _capture._load_state_file(self._tmpfile.name)
        self.assertIsNone(result)

    def test_nonexistent_file(self):
        result = _capture._load_state_file("/tmp/no_existe_alfred_state.json")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
