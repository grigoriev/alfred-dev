#!/usr/bin/env python3
"""
Central activity capture hook for Alfred Dev.

Replaces ``memory-capture.py`` and ``commit-capture.py``. It is a single
entry point that records ALL relevant activity in the persistent memory
database. Each event is stored with three levels of detail:

- **summary**: human-readable text (in Russian) for the dashboard.
- **payload**: structured JSON for programmatic filtering.
- **content**: full, untruncated text for on-demand lookup.

Write policy: persist only what a human would want to read again.
    At runtime the hook records Alfred slash prompts, `git commit` commits
    of the session and writes to state/handoff/UAT/`docs/project/`. It does
    not copy Read/Glob/Grep, old Git history or every code edit.

Fail-open policy: the hook NEVER blocks the workflow. Any error goes to
stderr with the ``[activity-capture]`` prefix and the hook exits with
code 0.
"""

import json
import os
import re
import shlex
import subprocess
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Directories and patterns excluded from generic capture.
# These are internal files. Their activity adds noise and no useful
# context to the project history.
_EXCLUDED_PREFIXES = (
    ".claude/",
    ".git/",
    "node_modules/",
    "__pycache__/",
    ".venv/",
    "venv/",
    ".mypy_cache/",
    ".pytest_cache/",
)

# Pattern that detects 'git commit' as a real command, not as an argument
# of another command (grep, echo, etc.). It matches git commit only at the
# start of the line or after shell operators (&&, ||, ;).
_GIT_COMMIT_RE = re.compile(r"(?:^|&&|\|\||;)\s*git\s+commit\b")

# Trivial commands that add no useful context to the history.
# These are read, navigation or diagnostic commands that do not change
# the project state.
_TRIVIAL_COMMANDS = frozenset({
    "ls", "pwd", "cd", "echo", "cat", "head", "tail", "less", "more",
    "wc", "whoami", "date", "which", "where", "type", "file", "true",
    "false", "clear", "history", "env", "printenv", "set", "export",
    "alias", "unalias", "source", ".", "test", "[",
})

# Alfred commands that can be prepared deterministically before the
# model tries to resolve the prompt by itself.
_ALFRED_PREFETCH_COMMANDS = frozenset({
    "alfred",
    "audit",
    "map-codebase",
    "discuss",
    "feature",
    "fix",
    "quick",
    "cto",
    "ship",
    "spike",
    "memory-ui",
})

# Prefix for warning messages on stderr.
_LOG_PREFIX = "[activity-capture]"

_HIGH_VOLUME_CONTENT_MAX_LINES = 80
_HIGH_VOLUME_CONTENT_MAX_CHARS = 4000


def _ensure_plugin_root_on_path() -> str:
    """Make sure the plugin root is available for imports.

    Claude Code runs hooks as standalone scripts, and they do not always get
    ``PYTHONPATH`` with the plugin root. Without this fix, imports such as
    ``core.memory`` or ``core.memory_config`` can fail even when the plugin
    is installed correctly.

    Returns:
        Absolute path to the plugin root.
    """
    plugin_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if plugin_root not in sys.path:
        sys.path.insert(0, plugin_root)
    return plugin_root


# ---------------------------------------------------------------------------
# Dispatcher table
# ---------------------------------------------------------------------------

def _build_dispatcher_table():
    """Build the event -> dispatch function map.

    This is a function to avoid forward references to functions that are
    not yet declared when the module is defined.

    Returns:
        Dictionary with event keys and dispatcher function values.
    """
    return {
        "Write": _dispatch_write,
        "Edit": _dispatch_edit,
        "Bash": _dispatch_bash,
        "Read": _dispatch_read,
        "Glob": _dispatch_glob,
        "Grep": _dispatch_grep,
        "Agent": _dispatch_agent,
        "WebFetch": _dispatch_web_fetch,
        "WebSearch": _dispatch_web_search,
        "NotebookEdit": _dispatch_notebook,
        "UserPromptSubmit": _dispatch_prompt,
        "UserPromptExpansion": _dispatch_prompt,
        "PreCompact": _dispatch_compact,
        "Stop": _dispatch_stop,
    }


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _is_memory_enabled() -> bool:
    """Check if persistent memory is enabled in the configuration.

    Looks for ``alfred-dev.local.md`` in the ``.claude`` directory of the
    current project and checks that it has the ``memory:`` section with
    ``enabled: true``.

    Returns:
        True if memory is enabled, otherwise False.
    """
    _ensure_plugin_root_on_path()
    try:
        from core.memory_config import is_memory_enabled
    except ImportError:
        return False

    return is_memory_enabled(os.getcwd())


def _memory_settings():
    """Load the effective memory configuration of the project."""
    _ensure_plugin_root_on_path()
    try:
        from core.memory_config import load_memory_config
    except ImportError:
        return {
            "enabled": False,
            "sync_to_native": True,
            "sync_commits_limit": 10,
            "capture_decisions": True,
            "capture_commits": True,
            "retention_days": 365,
        }
    return load_memory_config(os.getcwd())


def _is_excluded_path(file_path: str) -> bool:
    """Determine if a file must be excluded from generic capture.

    Excludes internal files of the plugin, of version control and of tool
    caches. The comparison uses the path relative to the project directory.

    Args:
        file_path: absolute or relative file path.

    Returns:
        True if the file must be excluded.
    """
    project_dir = _normalize_local_path(os.getcwd())
    normalized_path = _normalize_local_path(file_path)
    try:
        rel_path = os.path.relpath(normalized_path, project_dir)
    except ValueError:
        rel_path = normalized_path

    rel_path = rel_path.replace(os.sep, "/")

    for prefix in _EXCLUDED_PREFIXES:
        if rel_path.startswith(prefix) or f"/{prefix}" in rel_path:
            return True
    return False


def _normalize_local_path(file_path: str) -> str:
    """Normalize a local path for stable comparisons."""
    return os.path.normcase(os.path.realpath(os.path.abspath(file_path)))


def _shell_segments(command: str) -> list[list[str]]:
    """Split a shell command into segments separated by &&, || or ;."""
    cleaned = command.strip()
    if not cleaned:
        return []

    try:
        lexer = shlex.shlex(cleaned, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = cleaned.split()

    segments = []
    current = []
    for token in tokens:
        if token in {"&&", "||", ";"}:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)

    if current:
        segments.append(current)
    return segments


def _segment_command_name(tokens: list[str]) -> str:
    """Extract the main executable of a shell segment."""
    for token in tokens:
        if re.match(r"^\w+=\S*$", token):
            continue
        return os.path.basename(token)
    return ""


_NOISE_TOOLS = frozenset({
    "Read",
    "Glob",
    "Grep",
    "WebFetch",
    "WebSearch",
    "NotebookEdit",
    "Agent",
})
_MEMORY_WRITE_PREFIXES = ("docs/project/", "docs/adr/")
_MEMORY_WRITE_FILES = frozenset({
    ".claude/alfred-dev-state.json",
    ".claude/alfred-handoff.json",
    ".claude/alfred-uat.json",
})


def _should_record_event(dispatch_key: str, data: dict) -> bool:
    """Filter noise: memory is not a log of every tool call."""
    if dispatch_key in {"UserPromptSubmit", "UserPromptExpansion", "PreCompact", "Stop"}:
        return True
    if dispatch_key in _NOISE_TOOLS:
        return False
    if dispatch_key == "Bash":
        command = ""
        tool_input = data.get("tool_input")
        if isinstance(tool_input, dict):
            command = str(tool_input.get("command") or "")
        return is_git_commit_command(command)
    if dispatch_key in {"Write", "Edit"}:
        file_path = ""
        tool_input = data.get("tool_input")
        if isinstance(tool_input, dict):
            file_path = str(tool_input.get("file_path") or "")
        relative = _relative_path(file_path, os.getcwd()).replace("\\", "/")
        if relative.startswith(_MEMORY_WRITE_PREFIXES):
            return True
        return relative in _MEMORY_WRITE_FILES
    return False


def _is_trivial_command(command: str) -> bool:
    """Determine if a command is trivial and not worth recording.

    Extracts the first token of each command segment (ignoring environment
    variables) and compares it with the list of trivial commands.

    Args:
        command: full shell command.

    Returns:
        True if the command is trivial.
    """
    segments = _shell_segments(command)
    if not segments:
        return False

    command_names = [_segment_command_name(segment) for segment in segments]
    if not all(command_names):
        return False

    return all(command_name in _TRIVIAL_COMMANDS for command_name in command_names)


def is_git_commit_command(command: str) -> bool:
    """Determine if a command contains a real git commit.

    Public so that tests can use it easily.

    Args:
        command: shell command to analyze.

    Returns:
        True if it contains a real git commit.
    """
    return bool(_GIT_COMMIT_RE.search(command))


def _open_db():
    """Open the memory database of the current project.

    Looks for the DB in ``.claude/alfred-memory.db`` relative to the working
    directory. Returns None if it does not exist or cannot be opened.

    Returns:
        MemoryDB instance, or None if it could not be opened.
    """
    _ensure_plugin_root_on_path()

    try:
        from core.memory import MemoryDB
    except ImportError as e:
        print(
            f"{_LOG_PREFIX} Предупреждение: не удалось импортировать core.memory: {e}",
            file=sys.stderr,
        )
        return None

    db_path = os.path.join(os.getcwd(), ".claude", "alfred-memory.db")
    if not os.path.isfile(db_path):
        return None

    try:
        return MemoryDB(db_path)
    except Exception as e:
        print(
            f"{_LOG_PREFIX} Предупреждение: не удалось открыть БД памяти: {e}",
            file=sys.stderr,
        )
        return None


def _relative_path(file_path: str, project_dir: str) -> str:
    """Convert an absolute path to a path relative to the project.

    Args:
        file_path: absolute file path.
        project_dir: project root directory.

    Returns:
        Relative path. If the conversion fails, the normalized original path.
    """
    normalized_file = _normalize_local_path(file_path)
    normalized_project = _normalize_local_path(project_dir)
    try:
        rel_path = os.path.relpath(normalized_file, normalized_project)
    except ValueError:
        return normalized_file
    if rel_path == ".." or rel_path.startswith(f"..{os.sep}"):
        return normalized_file
    return rel_path


def _read_file_safe(file_path: str) -> Optional[str]:
    """Read the content of a file safely.

    Args:
        file_path: absolute file path.

    Returns:
        File content as text, or None if the read fails.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _first_meaningful_line(text: str) -> str:
    """Extract the first non-empty line of a text.

    Args:
        text: input text.

    Returns:
        First non-empty line, truncated to 120 characters. Empty string
        if no line has content.
    """
    if not text:
        return ""
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped:
            return stripped[:120]
    return ""


def _prepare_high_volume_content(text: str) -> tuple[Optional[str], dict]:
    """Trim large outputs and return capture metadata.

    Some exploration events (`Glob`, `Grep`, `WebFetch`, `WebSearch`) can
    produce thousands of lines or very large HTML blobs. Storing them in full
    adds little signal and a lot of noise. In these cases we store a preview
    with metadata so that memory knows the content was trimmed.
    """
    if not text:
        return None, {}

    lines = text.splitlines()
    total_lines = len(lines)
    total_chars = len(text)
    preview = text
    truncated = False

    if total_lines > _HIGH_VOLUME_CONTENT_MAX_LINES:
        preview = "\n".join(lines[:_HIGH_VOLUME_CONTENT_MAX_LINES])
        if text.endswith("\n"):
            preview += "\n"
        truncated = True

    if len(preview) > _HIGH_VOLUME_CONTENT_MAX_CHARS:
        preview = preview[:_HIGH_VOLUME_CONTENT_MAX_CHARS].rstrip()
        truncated = True

    metadata = {
        "content_lines": total_lines,
        "content_chars": total_chars,
    }

    if not truncated:
        metadata["content_truncated"] = False
        return preview, metadata

    preview_lines = len(preview.splitlines())
    omitted_lines = max(total_lines - preview_lines, 0)
    omitted_chars = max(total_chars - len(preview), 0)
    marker = (
        "\n"
        f"--- содержимое обрезано: пропущено строк: {omitted_lines}, "
        f"символов: {omitted_chars} ---"
    )
    preview = f"{preview.rstrip()}{marker}"

    metadata["content_truncated"] = True
    metadata["omitted_lines"] = omitted_lines
    metadata["omitted_chars"] = omitted_chars
    return preview, metadata


def _try_sync(db, action: str, **kwargs) -> None:
    """Run an incremental sync to native .md files.

    Projects recent changes to the Claude Code native memory files. If it
    fails for any reason, it continues and only prints a warning
    (fail-open policy).

    Args:
        db: MemoryDB instance.
        action: sync type (decision, iteration, commits).
        **kwargs: additional arguments for the sync method.
    """
    try:
        settings = _memory_settings()
        if not settings.get("sync_to_native", True):
            return

        from core.memory_sync import MemorySync, resolve_memory_dir

        memory_dir = resolve_memory_dir(os.getcwd())
        if memory_dir is None:
            return

        commits_limit = settings.get("sync_commits_limit", 10)
        if not isinstance(commits_limit, int) or commits_limit < 1:
            commits_limit = 10

        sync = MemorySync(db, memory_dir, commits_limit=commits_limit)

        if action == "decision":
            decision_id = kwargs.get("decision_id")
            if decision_id is not None:
                sync.sync_decision(decision_id)
        elif action == "iteration":
            sync.sync_iteration()
        elif action == "commits":
            sync.sync_commits()
        else:
            return  # Unknown action: do not sync

        sync.sync_summary()
        sync.update_index()
    except Exception as e:
        print(
            f"{_LOG_PREFIX} Предупреждение: инкрементальная синхронизация не удалась: {e}",
            file=sys.stderr,
        )


def _load_state_file(file_path: str) -> Optional[dict]:
    """Read and parse the session state file.

    Validates that the JSON has the minimum required structure: it must be
    a dictionary with the ``command`` and ``current_phase`` keys.

    Args:
        file_path: absolute path to the alfred-dev-state.json file.

    Returns:
        Dictionary with the state, or None if it cannot be read or parsed.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, json.JSONDecodeError, FileNotFoundError):
        return None

    if not isinstance(state, dict):
        return None
    if "command" not in state or "current_phase" not in state:
        return None

    return state


def _parse_alfred_prefetch_prompt(prompt_text: str) -> Optional[dict]:
    """Extract the Alfred slash command if it supports helper-first preparation."""
    normalized = (prompt_text or "").strip()
    first_line = normalized.splitlines()[0].strip()
    alias_match = re.match(
        r"^/alfred(?:\s+(?P<rest>.*))?$",
        first_line,
        flags=re.IGNORECASE,
    )
    if alias_match:
        raw_request = " ".join((alias_match.group("rest") or "").split()).strip()
        return {
            "source_command": "alfred",
            "raw_request": raw_request,
        }

    if not normalized.startswith("/alfred-dev:"):
        return None

    match = re.match(
        r"^/alfred-dev:(?P<command>[a-z0-9-]+)\b(?P<rest>.*)$",
        first_line,
        flags=re.IGNORECASE,
    )
    if not match:
        return None

    command = match.group("command").lower()
    if command not in _ALFRED_PREFETCH_COMMANDS:
        return None

    raw_request = " ".join(match.group("rest").split()).strip()
    return {
        "source_command": command,
        "raw_request": raw_request,
    }


def _prefetch_alfred_continuity(prompt_text: str) -> Optional[dict]:
    """Prepare continuity artifacts before the first reasoning step."""
    parsed = _parse_alfred_prefetch_prompt(prompt_text)
    if parsed is None:
        return None

    _ensure_plugin_root_on_path()
    try:
        from core.continuity import (
            is_memory_ui_stop_request,
            launch_memory_ui,
            needs_codebase_map,
            prepare_cto_review,
            save_prefetch_result,
            start_flow_session,
            start_quick_session,
            suggest_verify_action,
            write_codebase_map_files,
            write_discovery_files,
        )
    except ImportError as exc:
        print(
            f"{_LOG_PREFIX} Предупреждение: не удалось импортировать core.continuity: {exc}",
            file=sys.stderr,
        )
        return None

    project_dir = os.getcwd()
    source_command = parsed["source_command"]
    raw_request = parsed["raw_request"]

    target_command = source_command
    action = None

    if source_command == "alfred":
        if suggest_verify_action(project_dir) is not None:
            return None
        if not needs_codebase_map(project_dir):
            return None
        target_command = "map-codebase"
        action = write_codebase_map_files
    elif source_command == "map-codebase":
        action = write_codebase_map_files
    elif source_command == "discuss":
        action = write_discovery_files
    elif source_command == "quick":
        action = start_quick_session
    elif source_command == "cto":
        action = prepare_cto_review
    elif source_command in {"feature", "fix", "spike", "ship", "audit"}:
        action = lambda project_dir, raw_request: start_flow_session(
            project_dir,
            command=source_command,
            raw_request=raw_request,
        )
    elif source_command == "memory-ui":
        if is_memory_ui_stop_request(raw_request):
            from core.continuity import stop_memory_ui

            action = lambda project_dir, raw_request: stop_memory_ui(project_dir)
        else:
            action = lambda project_dir, raw_request: launch_memory_ui(
                project_dir,
                open_browser_window=False,
            )

    if action is None:
        return None

    try:
        result = action(project_dir, raw_request)
    except RuntimeError as exc:
        print(
            f"{_LOG_PREFIX} Предупреждение: prefetch /{source_command if source_command == 'alfred' else 'alfred-dev:' + source_command} пропущен: {exc}",
            file=sys.stderr,
        )
        return None
    except Exception as exc:
        print(
            f"{_LOG_PREFIX} Предупреждение: сбой prefetch /{source_command if source_command == 'alfred' else 'alfred-dev:' + source_command}: {exc}",
            file=sys.stderr,
        )
        return None

    payload = result.copy() if isinstance(result, dict) else {}
    payload["source_command"] = source_command
    payload["prefetched_command"] = target_command
    save_prefetch_result(project_dir, payload)
    return payload


def _log_prefetch_event(db, project_dir: str, payload: dict) -> None:
    """Record in memory that Alfred prepared a helper-first command."""
    command = payload.get("prefetched_command", "unknown")
    source_command = payload.get("source_command", command)
    artifacts = []

    for key, value in payload.items():
        if not key.endswith("_path"):
            continue
        if not isinstance(value, str) or not value:
            continue
        artifacts.append(_relative_path(value, project_dir))

    source_label = "/alfred" if source_command == "alfred" else f"/alfred-dev:{source_command}"
    summary = f"Prefetch Alfred: {source_label}"
    if source_command != command:
        summary += f" подготовил /alfred-dev:{command}"
    else:
        summary += " подготовлен до основного процесса"

    event_payload = {
        "source_command": source_command,
        "prefetched_command": command,
        "artifacts": artifacts,
    }
    next_command = payload.get("recommended_command") or payload.get("next_command")
    if isinstance(next_command, str) and next_command.strip():
        event_payload["next_command"] = next_command.strip()

    db.log_event(
        event_type="alfred_prefetched",
        summary=summary,
        payload=event_payload,
    )


# ---------------------------------------------------------------------------
# State logic (iterations and phases)
# ---------------------------------------------------------------------------

def _process_state(db, file_path: str) -> None:
    """Process the state file and record iteration/phase events.

    The comparison logic has three parts:

    1. If the DB has no active iteration, start a new one.
    2. For each completed phase in the new state that is not yet recorded
       as an event in the DB, record one ``phase_completed`` event.
    3. If the current phase is "completed", close the active iteration.

    Also, completed phases are marked automatically (auto-pin) so that
    they survive between sessions.

    Args:
        db: open MemoryDB instance.
        file_path: path to the alfred-dev-state.json file.
    """
    new_state = _load_state_file(file_path)
    if new_state is None:
        return

    command = new_state.get("command", "unknown")
    description = new_state.get("description", "")
    current_phase = new_state.get("current_phase", "")
    completed_phases = new_state.get("completed_phases", [])

    # --- Check for an active iteration ---
    active = db.get_active_iteration()

    if active is None:
        iteration_id = db.start_iteration(
            command=command,
            description=description,
        )
        db.log_event(
            event_type="iteration_started",
            payload={"command": command, "description": description},
            iteration_id=iteration_id,
        )
        _try_sync(db, "iteration")
        active = db.get_active_iteration()
    else:
        active_command = str(active.get("command") or "")
        active_description = str(active.get("description") or "")
        if active_command == "session" and command and command != "session":
            db.complete_iteration(int(active["id"]), status="abandoned")
            iteration_id = db.start_iteration(
                command=command,
                description=description or active_description,
            )
            db.log_event(
                event_type="iteration_started",
                payload={"command": command, "description": description},
                iteration_id=iteration_id,
            )
            _try_sync(db, "iteration")
            active = db.get_active_iteration()

    if active is None:
        return

    iteration_id = active["id"]

    # --- Detect newly completed phases ---
    phase_event_count = db.count_events(
        iteration_id=iteration_id,
        event_type="phase_completed",
    )
    existing_events = db.get_events(
        iteration_id=iteration_id,
        event_type="phase_completed",
        ascending=True,
        limit=max(phase_event_count, 1),
    )
    existing_phases = set()
    for event in existing_events:
        payload_raw = event.get("payload")
        if payload_raw:
            try:
                payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
                phase_name = payload.get("phase", "") or event.get("phase", "")
                if phase_name:
                    existing_phases.add(phase_name)
            except (json.JSONDecodeError, AttributeError):
                pass

    for phase in completed_phases:
        phase_name = phase.get("name", "") if isinstance(phase, dict) else str(phase)
        if not phase_name:
            continue
        if phase_name in existing_phases:
            continue

        payload = {"phase": phase_name}
        if isinstance(phase, dict):
            if "result" in phase:
                payload["result"] = phase["result"]
            if "completed_at" in phase:
                payload["completed_at"] = phase["completed_at"]
            if "artifacts" in phase:
                payload["artifacts"] = phase["artifacts"]

        db.log_event(
            event_type="phase_completed",
            phase=phase_name,
            payload=payload,
            iteration_id=iteration_id,
        )

    # --- Detect a completed iteration ---
    if current_phase == "completed":
        db.complete_iteration(iteration_id)
        db.log_event(
            event_type="iteration_completed",
            payload={
                "command": command,
                "total_phases": len(completed_phases),
            },
            iteration_id=iteration_id,
        )
        _try_sync(db, "iteration")



# ---------------------------------------------------------------------------
# Git commit capture
# ---------------------------------------------------------------------------

def _capture_git_commit(db) -> None:
    """Extract metadata of the last commit and record it with log_commit().

    Adds structured commit data (SHA, message, author, files) to the
    generic event for the commits view of the dashboard.

    Args:
        db: open MemoryDB instance.
    """
    if not _memory_settings().get("capture_commits", True):
        return

    try:
        result = subprocess.run(
            ["git", "log", "-1",
             "--format=%H%x1f%s%x1f%an%x1f%aI",
             "--name-only"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return
    except Exception:
        return

    lines = result.stdout.strip().split("\n")
    if not lines or "\x1f" not in lines[0]:
        return

    parts = lines[0].split("\x1f", 3)
    sha = parts[0]
    message = parts[1] if len(parts) > 1 else ""
    author = parts[2] if len(parts) > 2 else ""
    committed_at = parts[3] if len(parts) > 3 else ""
    files = [line.strip() for line in lines[1:] if line.strip()]

    db.log_commit(
        sha=sha, message=message, author=author,
        files=files, files_changed=len(files),
        committed_at=committed_at,
    )
    _try_sync(db, "commits")


# ---------------------------------------------------------------------------
# Dispatchers
# ---------------------------------------------------------------------------

def _dispatch_write(db, data: dict) -> None:
    """Capture a full file write.

    Records the full file content, its extension, line count and relative
    path. If the file is ``alfred-dev-state.json``, it also runs the
    iteration/phase tracking logic.

    Args:
        db: open MemoryDB instance.
        data: PostToolUse hook data.
    """
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")

    if not file_path:
        return

    is_state_file = os.path.basename(file_path) == "alfred-dev-state.json"
    if is_state_file:
        _process_state(db, file_path)

    if _is_excluded_path(file_path):
        return

    project_dir = os.getcwd()
    rel_path = _relative_path(file_path, project_dir)
    _, ext = os.path.splitext(file_path)
    ext_clean = ext.lstrip(".") if ext else ""

    file_content = _read_file_safe(file_path)
    line_count = len(file_content.splitlines()) if file_content else 0
    try:
        from core.secrets import is_secret_storage_path
    except Exception:
        is_secret_storage_path = lambda _path: False  # noqa: E731
    stored_content = None if is_secret_storage_path(file_path) else file_content

    summary = f"Записан {rel_path} (строк: {line_count}, {ext_clean or 'без расширения'})"

    db.log_event(
        event_type="file_written",
        summary=summary,
        payload={"file": rel_path, "extension": ext_clean, "lines": line_count},
        content=stored_content,
    )


def _dispatch_edit(db, data: dict) -> None:
    """Capture a partial file edit.

    Records the diff (old_string -> new_string) with the count of replaced
    and new lines.

    Args:
        db: open MemoryDB instance.
        data: PostToolUse hook data.
    """
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")

    if not file_path or _is_excluded_path(file_path):
        return

    rel_path = _relative_path(file_path, os.getcwd())
    _, ext = os.path.splitext(file_path)
    ext_clean = ext.lstrip(".") if ext else ""

    old_string = tool_input.get("old_string", "")
    new_string = tool_input.get("new_string", "")
    old_lines = old_string.count("\n") + 1 if old_string else 0
    new_lines = new_string.count("\n") + 1 if new_string else 0

    summary = f"Изменён {rel_path}: строк заменено: {old_lines}, новых: {new_lines}"
    content = f"--- old ---\n{old_string}\n--- new ---\n{new_string}"

    db.log_event(
        event_type="file_edited",
        summary=summary,
        payload={"file": rel_path, "extension": ext_clean, "old_lines": old_lines, "new_lines": new_lines},
        content=content,
    )


def _dispatch_bash(db, data: dict) -> None:
    """Capture a Bash command run.

    Records the full command, exit code, stdout and stderr without
    truncation. If the command is a successful ``git commit``, it also
    runs the extended commit metadata capture.

    Args:
        db: open MemoryDB instance.
        data: PostToolUse hook data.
    """
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_response") or data.get("tool_result") or {}
    if not isinstance(tool_result, dict):
        tool_result = {"output": str(tool_result)}

    command = tool_input.get("command", "")
    if not command or _is_trivial_command(command):
        return

    exit_code = tool_result.get("exit_code")
    stdout = tool_result.get("stdout", "") or tool_result.get("output", "")
    stderr = tool_result.get("stderr", "")

    cmd_short = command[:80] + "..." if len(command) > 80 else command
    exit_str = f"exit {exit_code}" if exit_code is not None else "нет exit code"
    first_line = _first_meaningful_line(stdout)
    summary_parts = [f"Выполнено: {cmd_short} -- {exit_str}"]
    if first_line:
        summary_parts.append(first_line)
    summary = ", ".join(summary_parts)

    content_parts = []
    if stdout:
        content_parts.append(f"--- stdout ---\n{stdout}")
    if stderr:
        content_parts.append(f"--- stderr ---\n{stderr}")
    content = "\n".join(content_parts) if content_parts else None

    db.log_event(
        event_type="command_executed",
        summary=summary,
        payload={"command": command, "exit_code": exit_code},
        content=content,
    )

    # Extended git commit capture
    if _GIT_COMMIT_RE.search(command) and exit_code == 0:
        _capture_git_commit(db)


def _dispatch_read(db, data: dict) -> None:
    """Capture a file read.

    Records the path of the read file and the requested line range.
    It does not store the content (it already exists in the file) to
    avoid needless duplication.

    Args:
        db: open MemoryDB instance.
        data: PostToolUse hook data.
    """
    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "")

    if not file_path or _is_excluded_path(file_path):
        return

    rel_path = _relative_path(file_path, os.getcwd())
    offset = tool_input.get("offset")
    limit = tool_input.get("limit")

    range_str = ""
    if offset is not None and limit is not None:
        range_str = f" (строки {offset}-{offset + limit})"
    elif offset is not None:
        range_str = f" (со строки {offset})"
    elif limit is not None:
        range_str = f" (первые строки: {limit})"

    summary = f"Прочитан {rel_path}{range_str}"

    payload = {"file": rel_path}
    if offset is not None:
        payload["offset"] = offset
    if limit is not None:
        payload["limit"] = limit

    db.log_event(
        event_type="file_read",
        summary=summary,
        payload=payload,
    )


def _dispatch_glob(db, data: dict) -> None:
    """Capture a file search by glob pattern.

    Records the pattern and the number of results.

    Args:
        db: open MemoryDB instance.
        data: PostToolUse hook data.
    """
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})

    pattern = tool_input.get("pattern", "")
    if not pattern:
        return

    search_path = tool_input.get("path", ".")

    # Count results: tool_result can be a string with paths or a dict
    result_text = ""
    if isinstance(tool_result, str):
        result_text = tool_result
    elif isinstance(tool_result, dict):
        result_text = tool_result.get("output", "") or tool_result.get("stdout", "")

    match_count = len([l for l in result_text.strip().split("\n") if l.strip()]) if result_text.strip() else 0

    summary = f"Glob: {pattern} в {search_path} (результатов: {match_count})"

    content, content_meta = _prepare_high_volume_content(result_text)
    payload = {"pattern": pattern, "path": search_path, "results": match_count}
    payload.update(content_meta)

    db.log_event(
        event_type="glob_search",
        summary=summary,
        payload=payload,
        content=content,
    )


def _dispatch_grep(db, data: dict) -> None:
    """Capture a content search in files.

    Records the regex pattern, the directory and the number of matches.

    Args:
        db: open MemoryDB instance.
        data: PostToolUse hook data.
    """
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})

    pattern = tool_input.get("pattern", "")
    if not pattern:
        return

    search_path = tool_input.get("path", ".")
    output_mode = tool_input.get("output_mode", "files_with_matches")
    file_type = tool_input.get("type", "")
    glob_filter = tool_input.get("glob", "")

    result_text = ""
    if isinstance(tool_result, str):
        result_text = tool_result
    elif isinstance(tool_result, dict):
        result_text = tool_result.get("output", "") or tool_result.get("stdout", "")

    match_count = len([l for l in result_text.strip().split("\n") if l.strip()]) if result_text.strip() else 0

    filter_str = ""
    if file_type:
        filter_str = f" тип={file_type}"
    elif glob_filter:
        filter_str = f" фильтр={glob_filter}"

    summary = f"Grep: '{pattern}' в {search_path}{filter_str} (совпадений: {match_count})"

    content, content_meta = _prepare_high_volume_content(result_text)
    payload = {"pattern": pattern, "path": search_path, "mode": output_mode, "results": match_count}
    if file_type:
        payload["type"] = file_type
    if glob_filter:
        payload["glob"] = glob_filter
    payload.update(content_meta)

    db.log_event(
        event_type="grep_search",
        summary=summary,
        payload=payload,
        content=content,
    )


def _dispatch_agent(db, data: dict) -> None:
    """Capture a subagent launch.

    Records the subagent type, the task description and the prompt.
    The full result is stored in content.

    Args:
        db: open MemoryDB instance.
        data: PostToolUse hook data.
    """
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})

    description = tool_input.get("description", "")
    subagent_type = tool_input.get("subagent_type", "general-purpose")
    prompt = tool_input.get("prompt", "")

    summary = f"Субагент ({subagent_type}): {description}" if description else f"Субагент ({subagent_type}) запущен"

    result_text = ""
    if isinstance(tool_result, str):
        result_text = tool_result
    elif isinstance(tool_result, dict):
        result_text = tool_result.get("output", "") or tool_result.get("stdout", "")

    content_parts = []
    if prompt:
        content_parts.append(f"--- prompt ---\n{prompt}")
    if result_text:
        content_parts.append(f"--- результат ---\n{result_text}")

    db.log_event(
        event_type="agent_launched",
        summary=summary,
        payload={"subagent_type": subagent_type, "description": description},
        content="\n".join(content_parts) if content_parts else None,
    )


def _dispatch_web_fetch(db, data: dict) -> None:
    """Capture an HTTP request to an external URL.

    Args:
        db: open MemoryDB instance.
        data: PostToolUse hook data.
    """
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})

    url = tool_input.get("url", "")
    if not url:
        return

    result_text = ""
    if isinstance(tool_result, str):
        result_text = tool_result
    elif isinstance(tool_result, dict):
        result_text = tool_result.get("output", "") or tool_result.get("content", "")

    summary = f"Web fetch: {url[:100]}"

    content, content_meta = _prepare_high_volume_content(result_text)
    payload = {"url": url}
    payload.update(content_meta)

    db.log_event(
        event_type="web_fetched",
        summary=summary,
        payload=payload,
        content=content,
    )


def _dispatch_web_search(db, data: dict) -> None:
    """Capture a web search.

    Args:
        db: open MemoryDB instance.
        data: PostToolUse hook data.
    """
    tool_input = data.get("tool_input", {})
    tool_result = data.get("tool_result", {})

    query = tool_input.get("query", "")
    if not query:
        return

    result_text = ""
    if isinstance(tool_result, str):
        result_text = tool_result
    elif isinstance(tool_result, dict):
        result_text = tool_result.get("output", "") or tool_result.get("content", "")

    summary = f"Web search: {query[:100]}"

    content, content_meta = _prepare_high_volume_content(result_text)
    payload = {"query": query}
    payload.update(content_meta)

    db.log_event(
        event_type="web_searched",
        summary=summary,
        payload=payload,
        content=content,
    )


def _dispatch_notebook(db, data: dict) -> None:
    """Capture a Jupyter notebook edit.

    Args:
        db: open MemoryDB instance.
        data: PostToolUse hook data.
    """
    tool_input = data.get("tool_input", {})

    notebook_path = tool_input.get("notebook_path", "") or tool_input.get("path", "")
    if not notebook_path or _is_excluded_path(notebook_path):
        return

    rel_path = _relative_path(notebook_path, os.getcwd())
    command = tool_input.get("command", "edit")

    summary = f"Notebook {command}: {rel_path}"

    db.log_event(
        event_type="notebook_edited",
        summary=summary,
        payload={"file": rel_path, "command": command},
    )


def _dispatch_prompt(db, data: dict) -> None:
    """Capture the prompt sent by the user.

    Records the full prompt text and builds a summary from the first line,
    truncated to 100 characters.

    Args:
        db: open MemoryDB instance.
        data: UserPromptSubmit or UserPromptExpansion hook data.
    """
    prompt_text = data.get("prompt", "") or data.get("content", "")
    if not prompt_text:
        return

    _ensure_plugin_root_on_path()
    try:
        from core.continuity import clear_prefetch_consumed_marker, clear_prefetch_result
    except ImportError:
        clear_prefetch_consumed_marker = None
        clear_prefetch_result = None

    if clear_prefetch_consumed_marker is not None:
        clear_prefetch_consumed_marker(os.getcwd())
    if clear_prefetch_result is not None:
        clear_prefetch_result(os.getcwd())

    prefetched = _prefetch_alfred_continuity(prompt_text)
    if prefetched:
        _log_prefetch_event(db, os.getcwd(), prefetched)

    first_line = prompt_text.split("\n")[0][:100]
    summary = f"Prompt: {first_line}"
    if len(prompt_text) > len(first_line):
        summary += "..."

    payload = {
        "length": len(prompt_text),
        "source": data.get("hook_event_name", "UserPromptSubmit"),
    }
    for key in ("expansion_type", "command_name", "command_source"):
        if data.get(key):
            payload[key] = data[key]

    db.log_event(
        event_type="user_prompt",
        summary=summary,
        payload=payload,
        content=prompt_text,
    )


def _dispatch_compact(db, data: dict) -> None:
    """Mark a context compaction event.

    Shows that the Claude Code engine summarized the previous messages.

    Args:
        db: open MemoryDB instance.
        data: PreCompact hook data.
    """
    summary = "Контекст сжат: предыдущие сообщения свёрнуты в резюме"
    db.log_event(
        event_type="context_compacted",
        summary=summary,
        payload={"source": "PreCompact"},
    )


def _dispatch_stop(db, data: dict) -> None:
    """Mark the end of the session.

    Records an end event and closes the active iteration, if any.

    Args:
        db: open MemoryDB instance.
        data: Stop hook data.
    """
    summary = "Сессия завершена"
    db.log_event(
        event_type="session_ended",
        summary=summary,
        payload={"source": "Stop"},
    )

    _ensure_plugin_root_on_path()
    try:
        from core.continuity import clear_prefetch_consumed_marker
    except ImportError:
        clear_prefetch_consumed_marker = None

    if clear_prefetch_consumed_marker is not None:
        clear_prefetch_consumed_marker(os.getcwd())

    active = db.get_active_iteration()
    if active:
        db.complete_iteration(active["id"])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Hook entry point.

    Reads the JSON that Claude Code sends on stdin, finds the event type and
    dispatches it to the matching handler. It never blocks the workflow:
    any error exits with code 0.
    """
    try:
        data = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError) as e:
        print(
            f"{_LOG_PREFIX} Предупреждение: не удалось прочитать вход hook: {e}. "
            f"Запись активности для этой операции отключена.",
            file=sys.stderr,
        )
        sys.exit(0)

    # Find the dispatch key: tool_name first, then hook_event_name
    dispatch_key = data.get("tool_name") or data.get("hook_event_name", "")
    if not dispatch_key:
        sys.exit(0)

    dispatchers = _build_dispatcher_table()
    handler = dispatchers.get(dispatch_key)
    if handler is None:
        sys.exit(0)
    if not _should_record_event(dispatch_key, data):
        sys.exit(0)

    # Check if memory is enabled
    if not _is_memory_enabled():
        sys.exit(0)

    # Open the database
    db = _open_db()
    if db is None:
        sys.exit(0)

    try:
        handler(db, data)
    except Exception as e:
        print(
            f"{_LOG_PREFIX} Предупреждение: ошибка при обработке события '{dispatch_key}': {e}",
            file=sys.stderr,
        )
    finally:
        db.close()

    sys.exit(0)


if __name__ == "__main__":
    main()
