#!/usr/bin/env python3
"""
Persistent per-project memory layer for Alfred Dev.

This module provides local SQLite storage that keeps design decisions,
workflow events and commit metadata between sessions. Full traceability
(problem -> decision -> commit -> validation) lets Alfred and the Librarian
answer history questions with real evidence, not with guesses.

The memory is an optional side layer: if it is off, the plugin flow stays the
same as always. When it is on, each project has its own database in
``.claude/alfred-memory.db``.

Main components:
    - sanitize_content(): removes possible secrets from text before storage.
    - MemoryDB: class that wraps the SQLite connection, the schema and all
      read and write operations on the memory.

Security:
    All text that enters the database goes through sanitize_content(), which
    applies the same regex patterns as secret-guard.sh. Detected secrets are
    replaced by [REDACTED:<type>] markers to prevent accidental leaks.
"""

import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.secrets import SECRET_PATTERNS as _SECRET_PATTERNS

# Current schema version. It is stored in the meta table and is used to
# detect if migrations must run.
_SCHEMA_VERSION = 4

# Margin factor for searches with post-filtering.
# When time, tag or status filters apply, the code asks SQLite for
# N * _FETCH_MARGIN results to make up for rows dropped by post-filtering,
# then truncates to the original limit.
_FETCH_MARGIN = 3

# Logical version of the content indexed in FTS. Increase it when the set
# of searchable fields changes. This rebuilds legacy indexes automatically.
_FTS_CONTENT_VERSION = 2

# Database file permissions: read and write for the owner only (same as
# chmod 600). They apply to the .db file and to the WAL and SHM helper
# files.
_DB_PERMISSIONS = stat.S_IRUSR | stat.S_IWUSR

# Schema migrations. Each entry is a list of SQL statements that move the
# database from version N to N+1. They run in sequence inside a
# transaction. Before any migration runs, a backup copy (.bak) of the file
# is made.
_MIGRATIONS: Dict[int, List[str]] = {
    1: [
        # v1 -> v2: tags and status in decisions, files in commits,
        # table of links between decisions.
        "ALTER TABLE decisions ADD COLUMN tags TEXT DEFAULT '[]'",
        "ALTER TABLE decisions ADD COLUMN status TEXT DEFAULT 'active'",
        "ALTER TABLE commits ADD COLUMN files TEXT DEFAULT '[]'",
        """CREATE TABLE IF NOT EXISTS decision_links (
            source_id   INTEGER NOT NULL REFERENCES decisions(id),
            target_id   INTEGER NOT NULL REFERENCES decisions(id),
            link_type   TEXT    NOT NULL,
            created_at  TEXT    NOT NULL,
            PRIMARY KEY (source_id, target_id)
        )""",
        "CREATE INDEX IF NOT EXISTS idx_decision_links_target ON decision_links(target_id)",
    ],
    3: [
        # v3 -> v4: summary and content columns for full capture
        "ALTER TABLE events ADD COLUMN summary TEXT",
        "ALTER TABLE events ADD COLUMN content TEXT",
    ],
    2: [
        # v2 -> v3: gui_actions and pinned_items tables (obsolete, removed
        # in v0.3.7). The CREATE statements stay so the migration remains
        # idempotent and existing DBs do not fail.
        "CREATE TABLE IF NOT EXISTS gui_actions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, action_type TEXT, payload TEXT, "
        "status TEXT, created_at TEXT, processed_at TEXT, processed_by TEXT)",
        "CREATE TABLE IF NOT EXISTS pinned_items ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, item_type TEXT, item_id INTEGER, "
        "item_ref TEXT, note TEXT, auto_pinned INTEGER, priority INTEGER, "
        "pinned_at TEXT, session_id TEXT)",
    ],
}

# Valid decision statuses. update_decision_status uses them to validate
# the input before it changes the database.
_VALID_DECISION_STATUSES = {"active", "superseded", "deprecated"}


def sanitize_content(text: Optional[str]) -> Optional[str]:
    """
    Remove possible secrets from text before storage.

    Walks the known secret patterns (API keys, tokens, connection strings,
    hardcoded credentials) and replaces each match with a
    ``[REDACTED:<type>]`` marker. This makes sure the project memory never
    stores sensitive material, even if an agent tries to log text that
    contains it.

    The patterns are the same as in the secret-guard.sh hook, so the whole
    plugin security chain stays consistent.

    Args:
        text: text to sanitize. If None, None is returned as is.

    Returns:
        Clean text with secrets replaced by markers, or None if the input
        was None.
    """
    if text is None:
        return None

    result = text
    for pattern, label in _SECRET_PATTERNS:
        result = pattern.sub(f"[REDACTED:{label}]", result)
    return result


def _sanitize_json_value(value: Any) -> Any:
    """Sanitize strings inside JSON structures without changing their shape."""
    if isinstance(value, str):
        return sanitize_content(value)
    if isinstance(value, dict):
        return {
            str(sanitize_content(str(key))): _sanitize_json_value(inner)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_json_value(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Schema creation SQL
# ---------------------------------------------------------------------------
# A multiline string keeps it readable. The statements run inside a
# transaction for atomicity.

_SCHEMA_SQL = """
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
    tags          TEXT    DEFAULT '[]',
    status        TEXT    DEFAULT 'active',
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
    files         TEXT    DEFAULT '[]',
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
    summary       TEXT,
    content       TEXT,
    created_at    TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_iterations_status
    ON iterations(status);
CREATE INDEX IF NOT EXISTS idx_decisions_iteration
    ON decisions(iteration_id);
CREATE INDEX IF NOT EXISTS idx_commits_iteration
    ON commits(iteration_id);
CREATE INDEX IF NOT EXISTS idx_events_iteration
    ON events(iteration_id);
CREATE INDEX IF NOT EXISTS idx_events_type
    ON events(event_type);

CREATE TABLE IF NOT EXISTS decision_links (
    source_id   INTEGER NOT NULL REFERENCES decisions(id),
    target_id   INTEGER NOT NULL REFERENCES decisions(id),
    link_type   TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    PRIMARY KEY (source_id, target_id)
);
CREATE INDEX IF NOT EXISTS idx_decision_links_target ON decision_links(target_id);

"""


class MemoryDB:
    """
    Access interface to the persistent memory of a project.

    Wraps a SQLite connection with WAL and foreign keys on. Manages the
    schema life cycle (creation, FTS5 detection, versioning) and exposes
    write and read methods for iterations, decisions, commits and events.

    The database file is created with 0600 permissions (only the owner can
    read and write) to protect the stored data.

    Args:
        db_path: absolute or relative path to the SQLite file.
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._fts_enabled = False

        # Create the parent directory if it does not exist
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row

        # Turn on WAL for better concurrency and foreign keys for integrity
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.execute("PRAGMA busy_timeout=5000")

        self._ensure_schema()
        self._detect_fts5()

        # 0600 permissions: only the owner can read and write.
        # Applied after creation to cover the new DB case.
        try:
            os.chmod(db_path, _DB_PERMISSIONS)
        except OSError:
            # On some file systems (e.g. FAT32) chmod does not work.
            # Not critical: continue without strict permissions.
            pass

    # --- Schema management -------------------------------------------------

    def _ensure_schema(self) -> None:
        """
        Create the tables and indexes if they do not exist.

        If the database is new, record the schema version and the creation
        date in the meta table. If it exists, it stays intact (the statements
        use ``IF NOT EXISTS``).
        """
        self._conn.executescript(_SCHEMA_SQL)

        # Record metadata on the first run
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()

        if row is None:
            now = datetime.now(timezone.utc).isoformat()
            self._conn.executemany(
                "INSERT INTO meta (key, value) VALUES (?, ?)",
                [
                    ("schema_version", str(_SCHEMA_VERSION)),
                    ("created_at", now),
                ],
            )
            self._conn.commit()
        else:
            # Existing DB: check if it needs a migration
            current = int(row[0])
            if current < _SCHEMA_VERSION:
                self._run_migrations(current)

    def _run_migrations(self, current_version: int) -> None:
        """Apply pending migrations in sequence.

        Makes a backup of the file before the first migration and runs each
        step inside a transaction. If a migration fails, the transaction is
        rolled back and the DB stays in the last consistent state.

        Args:
            current_version: current schema version in the DB.
        """
        # Migrate only if versions are pending
        pending = [v for v in sorted(_MIGRATIONS.keys()) if v >= current_version]
        if not pending:
            return

        # Backup before the migration
        bak_path = self._db_path + ".bak"
        try:
            shutil.copy2(self._db_path, bak_path)
        except OSError:
            # If the backup fails (permissions, full disk), continue and do
            # not abort the migration.
            pass

        for version in pending:
            statements = _MIGRATIONS[version]
            try:
                for sql in statements:
                    self._conn.execute(sql)
                # Update the version in meta
                new_version = version + 1
                self._conn.execute(
                    "UPDATE meta SET value = ? WHERE key = 'schema_version'",
                    (str(new_version),),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _detect_fts5(self) -> None:
        """
        Check if the SQLite build supports FTS5 and create the virtual table.

        If FTS5 is available, create the ``memory_fts`` table and the triggers
        that keep it in sync with ``decisions`` and ``commits``. If it is not
        available, record the result so searches use the LIKE fallback.
        """
        try:
            # Try to create a temporary FTS5 table to detect support
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS _fts5_test "
                "USING fts5(test_col)"
            )
            self._conn.execute("DROP TABLE IF EXISTS _fts5_test")

            # FTS5 is available: create the real search table
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts "
                "USING fts5(source_type, source_id, content)"
            )

            # Reinstall the triggers so they always index the current set of
            # fields, also when the DB comes from older versions.
            self._conn.executescript("""
                DROP TRIGGER IF EXISTS fts_insert_decision;
                DROP TRIGGER IF EXISTS fts_insert_commit;

                CREATE TRIGGER IF NOT EXISTS fts_insert_decision
                AFTER INSERT ON decisions
                BEGIN
                    INSERT INTO memory_fts(source_type, source_id, content)
                    VALUES (
                        'decision',
                        CAST(NEW.id AS TEXT),
                        COALESCE(NEW.title, '') || ' ' ||
                        COALESCE(NEW.context, '') || ' ' ||
                        COALESCE(NEW.chosen, '') || ' ' ||
                        COALESCE(NEW.alternatives, '') || ' ' ||
                        COALESCE(NEW.rationale, '')
                    );
                END;

                CREATE TRIGGER IF NOT EXISTS fts_insert_commit
                AFTER INSERT ON commits
                BEGIN
                    INSERT INTO memory_fts(source_type, source_id, content)
                    VALUES (
                        'commit',
                        CAST(NEW.id AS TEXT),
                        COALESCE(NEW.message, '') || ' ' ||
                        COALESCE(NEW.files, '')
                    );
                END;
            """)

            self._fts_enabled = True
        except sqlite3.OperationalError:
            # FTS5 is not available: LIKE is the fallback
            self._fts_enabled = False

        # Record the result in meta for other components
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("fts_enabled", "1" if self._fts_enabled else "0"),
        )

        if self._fts_enabled and self._fts_rebuild_required():
            self._rebuild_fts_index()

        self._conn.commit()

    @staticmethod
    def _compose_decision_search_content(row: Dict[str, Any]) -> str:
        """Build the indexable text of a decision."""
        return " ".join(
            part
            for part in (
                row.get("title"),
                row.get("context"),
                row.get("chosen"),
                row.get("alternatives"),
                row.get("rationale"),
            )
            if part
        ).strip()

    @staticmethod
    def _compose_commit_search_content(row: Dict[str, Any]) -> str:
        """Build the indexable text of a commit."""
        files_raw = row.get("files")
        files_text = ""
        if files_raw:
            if isinstance(files_raw, str):
                files_text = files_raw
            else:
                files_text = json.dumps(files_raw, ensure_ascii=False)

        return " ".join(
            part
            for part in (
                row.get("message"),
                files_text,
            )
            if part
        ).strip()

    @staticmethod
    def _compose_event_search_content(row: Dict[str, Any]) -> str:
        """Build the indexable text of an event."""
        return " ".join(
            part
            for part in (
                row.get("summary"),
                row.get("content"),
            )
            if part
        ).strip()

    def _expected_fts_counts(self) -> Dict[str, int]:
        """Return the expected number of FTS entries per type."""
        decision_count = self._conn.execute(
            "SELECT COUNT(*) FROM decisions"
        ).fetchone()[0]
        commit_count = self._conn.execute(
            "SELECT COUNT(*) FROM commits"
        ).fetchone()[0]
        event_count = self._conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE (summary IS NOT NULL AND TRIM(summary) != '') "
            "   OR (content IS NOT NULL AND TRIM(content) != '')"
        ).fetchone()[0]
        return {
            "decision": int(decision_count),
            "commit": int(commit_count),
            "event": int(event_count),
        }

    def _fts_rebuild_required(self) -> bool:
        """Detect if the FTS index must be rebuilt."""
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'fts_content_version'"
        ).fetchone()
        current_version = row[0] if row else None
        if current_version != str(_FTS_CONTENT_VERSION):
            return True

        expected_counts = self._expected_fts_counts()
        for source_type, expected in expected_counts.items():
            actual = self._conn.execute(
                "SELECT COUNT(*) FROM memory_fts WHERE source_type = ?",
                (source_type,),
            ).fetchone()[0]
            if actual != expected:
                return True

        unknown_sources = self._conn.execute(
            "SELECT COUNT(*) FROM memory_fts "
            "WHERE source_type NOT IN ('decision', 'commit', 'event')"
        ).fetchone()[0]
        if unknown_sources:
            return True

        orphan_queries = (
            "SELECT COUNT(*) FROM memory_fts f "
            "LEFT JOIN decisions d ON CAST(f.source_id AS INTEGER) = d.id "
            "WHERE f.source_type = 'decision' AND d.id IS NULL",
            "SELECT COUNT(*) FROM memory_fts f "
            "LEFT JOIN commits c ON CAST(f.source_id AS INTEGER) = c.id "
            "WHERE f.source_type = 'commit' AND c.id IS NULL",
            "SELECT COUNT(*) FROM memory_fts f "
            "LEFT JOIN events e ON CAST(f.source_id AS INTEGER) = e.id "
            "WHERE f.source_type = 'event' AND e.id IS NULL",
        )
        return any(self._conn.execute(sql).fetchone()[0] for sql in orphan_queries)

    def _rebuild_fts_index(self) -> None:
        """Fully rebuild the FTS index from the source tables."""
        self._conn.execute("DELETE FROM memory_fts")

        decision_rows = self._conn.execute(
            "SELECT id, title, context, chosen, alternatives, rationale FROM decisions"
        ).fetchall()
        commit_rows = self._conn.execute(
            "SELECT id, message, files FROM commits"
        ).fetchall()
        event_rows = self._conn.execute(
            "SELECT id, summary, content FROM events"
        ).fetchall()

        fts_rows: List[Tuple[str, str, str]] = []
        for row in decision_rows:
            content = self._compose_decision_search_content(dict(row))
            if content:
                fts_rows.append(("decision", str(row["id"]), content))

        for row in commit_rows:
            content = self._compose_commit_search_content(dict(row))
            if content:
                fts_rows.append(("commit", str(row["id"]), content))

        for row in event_rows:
            content = self._compose_event_search_content(dict(row))
            if content:
                fts_rows.append(("event", str(row["id"]), content))

        if fts_rows:
            self._conn.executemany(
                "INSERT INTO memory_fts (source_type, source_id, content) "
                "VALUES (?, ?, ?)",
                fts_rows,
            )

        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            ("fts_content_version", str(_FTS_CONTENT_VERSION)),
        )

    @property
    def fts_enabled(self) -> bool:
        """Tell if full-text search (FTS5) is on."""
        return self._fts_enabled

    # --- Write: iterations --------------------------------------------------

    def start_iteration(
        self,
        command: str,
        description: Optional[str] = None,
    ) -> int:
        """
        Start a new work iteration.

        Each iteration is one full cycle of a flow (feature, fix, spike,
        etc.). It starts in the ``active`` status and stays there until it is
        completed or abandoned.

        Args:
            command: flow type (feature, fix, spike, ship, audit).
            description: natural language description of the task.

        Returns:
            ID of the created iteration.
        """
        now = datetime.now(timezone.utc).isoformat()
        description = sanitize_content(description)
        cursor = self._conn.execute(
            "INSERT INTO iterations (command, description, status, started_at) "
            "VALUES (?, ?, 'active', ?)",
            (command, description, now),
        )
        self._conn.commit()
        return cursor.lastrowid

    def complete_iteration(
        self,
        iteration_id: int,
        status: str = "completed",
    ) -> None:
        """
        Mark an iteration as completed or abandoned.

        Args:
            iteration_id: ID of the iteration to close.
            status: final status (``completed`` or ``abandoned``).
        """
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE iterations SET status = ?, completed_at = ? WHERE id = ?",
            (status, now, iteration_id),
        )
        self._conn.commit()

    # --- Write: decisions ---------------------------------------------------

    def log_decision(
        self,
        title: str,
        chosen: str,
        context: Optional[str] = None,
        alternatives: Optional[List[str]] = None,
        rationale: Optional[str] = None,
        impact: Optional[str] = None,
        phase: Optional[str] = None,
        iteration_id: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> int:
        """
        Record a design decision.

        If ``iteration_id`` is not given, the decision links to the active
        iteration (if any). All text fields are sanitized before storage.
        Tags are stored as JSON. If no tags are given, an empty list is
        stored.

        Args:
            title: short title of the decision.
            chosen: chosen option.
            context: problem that the decision solved.
            alternatives: list of rejected options.
            rationale: reason for the choice.
            impact: impact level (low, medium, high, critical).
            phase: flow phase in which the decision was made.
            iteration_id: iteration ID (detected if omitted).
            tags: list of tags that classify the decision.

        Returns:
            ID of the created decision.
        """
        # Link to the active iteration if none is given
        if iteration_id is None:
            active = self.get_active_iteration()
            if active is not None:
                iteration_id = active["id"]

        now = datetime.now(timezone.utc).isoformat()

        # Sanitize all text fields
        title = sanitize_content(title) or title
        chosen = sanitize_content(chosen) or chosen
        context = sanitize_content(context)
        rationale = sanitize_content(rationale)

        # Alternatives are stored as JSON
        alt_json = None
        if alternatives is not None:
            sanitized_alts = [sanitize_content(a) or a for a in alternatives]
            alt_json = json.dumps(sanitized_alts, ensure_ascii=False)

        # Tags are stored as JSON. The default is an empty list
        tags_json = json.dumps(tags or [], ensure_ascii=False)

        cursor = self._conn.execute(
            "INSERT INTO decisions "
            "(iteration_id, title, context, chosen, alternatives, "
            " rationale, impact, phase, tags, decided_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                iteration_id, title, context, chosen, alt_json,
                rationale, impact, phase, tags_json, now,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    # --- Write: decision status and tags -------------------------------------

    def update_decision_status(self, decision_id: int, status: str) -> None:
        """
        Update the status of an existing decision.

        The valid statuses are ``active``, ``superseded`` and ``deprecated``.
        Any other value raises ``ValueError`` to prevent inconsistent
        statuses in the database.

        Args:
            decision_id: ID of the decision to update.
            status: new status (must be in ``_VALID_DECISION_STATUSES``).

        Raises:
            ValueError: if the given status is not valid.
        """
        if status not in _VALID_DECISION_STATUSES:
            raise ValueError(
                f"Недопустимый статус: '{status}'. "
                f"Допустимые значения: {sorted(_VALID_DECISION_STATUSES)}"
            )
        self._conn.execute(
            "UPDATE decisions SET status = ? WHERE id = ?",
            (status, decision_id),
        )
        self._conn.commit()

    def add_decision_tags(
        self, decision_id: int, tags: List[str]
    ) -> None:
        """
        Add tags to a decision without duplicating the existing ones.

        Reads the current tags, merges them with the new ones in insertion
        order and removes duplicates. The result is stored back in the
        ``tags`` column as JSON.

        Args:
            decision_id: ID of the decision to tag.
            tags: list of new tags to add.
        """
        row = self._conn.execute(
            "SELECT tags FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()

        # Read the current tags. If the decision does not exist or has no
        # tags, start from an empty list
        existing: List[str] = []
        if row and row["tags"]:
            existing = json.loads(row["tags"])

        # Merge without duplicates and keep the order of appearance
        merged = list(dict.fromkeys(existing + tags))
        merged_json = json.dumps(merged, ensure_ascii=False)

        self._conn.execute(
            "UPDATE decisions SET tags = ? WHERE id = ?",
            (merged_json, decision_id),
        )
        self._conn.commit()

    # --- Write: links between decisions -------------------------------------

    def link_decisions(
        self,
        source_id: int,
        target_id: int,
        link_type: str,
    ) -> None:
        """
        Create a directed link between two decisions.

        The link goes from ``source_id`` to ``target_id`` with a type that
        describes it (e.g. ``supersedes``, ``relates``, ``depends_on``). If
        the link exists, the operation is idempotent and raises no exception.

        Args:
            source_id: ID of the source decision.
            target_id: ID of the target decision.
            link_type: type of link between the two decisions.
        """
        now = datetime.now(timezone.utc).isoformat()
        try:
            self._conn.execute(
                "INSERT INTO decision_links "
                "(source_id, target_id, link_type, created_at) "
                "VALUES (?, ?, ?, ?)",
                (source_id, target_id, link_type, now),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            # The link exists: idempotent
            pass

    def get_decision_links(
        self, decision_id: int
    ) -> List[Dict[str, Any]]:
        """
        Get all links that include a decision.

        The lookup goes both ways: it returns links where the decision is the
        source and links where it is the target. This lets callers walk the
        decision graph in both directions.

        Args:
            decision_id: ID of the decision to query.

        Returns:
            List of dictionaries with the ``source_id``, ``target_id``,
            ``link_type`` and ``created_at`` fields of each link found.
        """
        rows = self._conn.execute(
            "SELECT * FROM decision_links "
            "WHERE source_id = ? OR target_id = ?",
            (decision_id, decision_id),
        ).fetchall()
        return [dict(r) for r in rows]

    # --- Write: commits -----------------------------------------------------

    def log_commit(
        self,
        sha: str,
        message: Optional[str] = None,
        author: Optional[str] = None,
        files_changed: Optional[int] = None,
        insertions: Optional[int] = None,
        deletions: Optional[int] = None,
        iteration_id: Optional[int] = None,
        files: Optional[List[str]] = None,
        committed_at: Optional[str] = None,
        auto_link_iteration: bool = True,
    ) -> Optional[int]:
        """
        Record a commit in the memory.

        If the SHA exists, it is ignored silently (idempotent). If
        ``iteration_id`` is not given, the commit links to the active
        iteration. The list of changed files is serialized as JSON after each
        path is sanitized, to prevent leaks of sensitive data in file names.

        Args:
            sha: SHA hash of the commit.
            message: commit message (sanitized).
            author: commit author.
            files_changed: number of changed files.
            insertions: added lines.
            deletions: deleted lines.
            iteration_id: iteration ID.
            files: list of paths of the files changed in the commit.
            committed_at: real ISO 8601 date of the commit. If omitted, the
                current capture time is used.
            auto_link_iteration: if ``False``, do not attach the commit to
                the active iteration (for imported history).

        Returns:
            ID of the created commit, or None if it already existed.
        """
        # Link to the active iteration if none is given and the caller logs
        # work of the current flow, not imported history.
        if iteration_id is None and auto_link_iteration:
            active = self.get_active_iteration()
            if active is not None:
                iteration_id = active["id"]

        now = datetime.now(timezone.utc).isoformat()
        committed_at = str(committed_at).strip() if committed_at else now
        message = sanitize_content(message)
        author = sanitize_content(author)

        # Serialize the file list with preventive sanitization.
        # The original value is the fallback if sanitize_content
        # returns None.
        files_json = json.dumps(
            [sanitize_content(f) or f for f in (files or [])],
            ensure_ascii=False,
        )

        try:
            cursor = self._conn.execute(
                "INSERT INTO commits "
                "(sha, message, author, files_changed, insertions, "
                " deletions, files, committed_at, iteration_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    sha, message, author, files_changed,
                    insertions, deletions, files_json, committed_at, iteration_id,
                ),
            )
            self._conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            # The SHA exists: idempotent, not an error
            return None

    def link_commit_decision(
        self,
        commit_id: int,
        decision_id: int,
        link_type: str = "implements",
    ) -> None:
        """
        Link a commit to a decision.

        Gives traceability between design decisions and the commits that
        implement them, revert them or relate to them.

        Args:
            commit_id: commit ID.
            decision_id: decision ID.
            link_type: link type (implements, reverts, relates).
        """
        try:
            self._conn.execute(
                "INSERT INTO commit_links (commit_id, decision_id, link_type) "
                "VALUES (?, ?, ?)",
                (commit_id, decision_id, link_type),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            # The link exists: idempotent
            pass

    # --- Write: events ------------------------------------------------------

    def log_event(
        self,
        event_type: str,
        phase: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        summary: Optional[str] = None,
        content: Optional[str] = None,
        iteration_id: Optional[int] = None,
    ) -> int:
        """
        Record a workflow event.

        Events capture mechanical facts (phase completed, gate passed, user
        approval) that add the detailed flow timeline to the decisions.

        Args:
            event_type: event type (phase_completed, gate_passed, etc.).
            phase: flow phase in which it happened.
            payload: extra data as a dictionary.
            summary: short event summary for quick queries.
            content: full event content, indexed in FTS if it is on.
            iteration_id: iteration ID (detected if omitted).

        Returns:
            ID of the created event.
        """
        if iteration_id is None:
            active = self.get_active_iteration()
            if active is not None:
                iteration_id = active["id"]

        now = datetime.now(timezone.utc).isoformat()
        payload_json = None
        if payload is not None:
            # Sanitize nested payloads in case they contain secrets.
            sanitized = _sanitize_json_value(payload)
            payload_json = json.dumps(sanitized, ensure_ascii=False)

        sanitized_event_type = sanitize_content(event_type) or ""
        sanitized_phase = sanitize_content(phase) if phase else None
        sanitized_summary = sanitize_content(summary) if summary else None
        sanitized_content = sanitize_content(content) if content else None

        cursor = self._conn.execute(
            "INSERT INTO events "
            "(iteration_id, event_type, phase, payload, summary, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (iteration_id, sanitized_event_type, sanitized_phase, payload_json,
             sanitized_summary, sanitized_content, now),
        )

        # Index summary and content so short events are also searchable
        # through FTS without the LIKE fallback.
        event_search_content = self._compose_event_search_content(
            {
                "summary": sanitized_summary,
                "content": sanitized_content,
            }
        )
        if self._fts_enabled and event_search_content:
            self._conn.execute(
                "INSERT INTO memory_fts (source_type, source_id, content) "
                "VALUES (?, ?, ?)",
                ("event", cursor.lastrowid, event_search_content),
            )

        self._conn.commit()
        return cursor.lastrowid

    # --- Read: iterations ---------------------------------------------------

    def get_iteration(self, iteration_id: int) -> Optional[Dict[str, Any]]:
        """
        Get the full data of an iteration by its ID.

        Args:
            iteration_id: ID of the iteration to query.

        Returns:
            Dictionary with the iteration data, or None if it does not exist.
        """
        row = self._conn.execute(
            "SELECT * FROM iterations WHERE id = ?", (iteration_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_active_iteration(self) -> Optional[Dict[str, Any]]:
        """
        Get the most recent active iteration.

        In normal use only one iteration is active at a time. If there are
        several (an inconsistency), the most recent by ID is returned.

        Returns:
            Dictionary with the active iteration data, or None.
        """
        row = self._conn.execute(
            "SELECT * FROM iterations WHERE status = 'active' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_latest_iteration(self) -> Optional[Dict[str, Any]]:
        """
        Get the most recent iteration, whatever its status.

        Unlike ``get_active_iteration``, it does not filter by status. Useful
        as a fallback when no iteration is active and the context of the last
        recorded iteration is needed.

        Returns:
            Dictionary with the most recent iteration data, or None.
        """
        row = self._conn.execute(
            "SELECT * FROM iterations ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    def get_iterations(
        self,
        limit: int = 50,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return recent iterations with pagination."""
        params: List[Any] = []
        where = ""
        if status is not None:
            where = "WHERE status = ?"
            params.append(status)

        params.extend([limit, offset])
        rows = self._conn.execute(
            f"SELECT * FROM iterations {where} "
            "ORDER BY id DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    # --- Read: decisions ----------------------------------------------------

    def get_decisions(
        self,
        iteration_id: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get decisions with optional filters by iteration, tags and status.

        The SQL query is built from the given filters. The tag filter matches
        the JSON ``tags`` field with ``LIKE`` for each tag. One match is
        enough to include the row (OR logic). The status filter uses an exact
        match.

        Args:
            iteration_id: if given, only decisions of that iteration.
            limit: maximum number of results.
            offset: offset for pagination.
            tags: list of tags. At least one must match the tags of the row
                for the row to be included.
            status: if given, only decisions with this status.

        Returns:
            List of dictionaries with the data of each decision.
        """
        # Build the SQL query from the filters
        conditions: List[str] = []
        params: List[Any] = []

        if iteration_id is not None:
            conditions.append("iteration_id = ?")
            params.append(iteration_id)

        if status is not None:
            conditions.append("status = ?")
            params.append(status)

        # Tags use LIKE on the JSON field. At least one tag must be present
        # (OR logic). The '"%tag%"' pattern relies on tags being serialized
        # as a JSON array with quotes (e.g. '["security", "api"]').
        if tags:
            tag_clauses = []
            for tag in tags:
                tag_clauses.append("tags LIKE ?")
                params.append(f'%"{tag}"%')
            conditions.append(f"({' OR '.join(tag_clauses)})")

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        sql = (
            f"SELECT * FROM decisions {where} "
            "ORDER BY decided_at DESC LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def iter_decisions(
        self,
        iteration_id: Optional[int] = None,
        batch_size: int = 500,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None,
    ) -> Iterable[Dict[str, Any]]:
        """Iterate decisions page by page to avoid silent caps."""
        offset = 0
        while True:
            batch = self.get_decisions(
                iteration_id=iteration_id,
                limit=batch_size,
                offset=offset,
                tags=tags,
                status=status,
            )
            if not batch:
                break
            for item in batch:
                yield item
            if len(batch) < batch_size:
                break
            offset += batch_size

    def get_decision(self, decision_id: int) -> Optional[Dict[str, Any]]:
        """Return a decision by ID, or None if it does not exist."""
        row = self._conn.execute(
            "SELECT * FROM decisions WHERE id = ?",
            (decision_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_commits(
        self,
        limit: int = 50,
        offset: int = 0,
        iteration_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return recent commits with pagination."""
        params: List[Any] = []
        where = ""
        if iteration_id is not None:
            where = "WHERE iteration_id = ?"
            params.append(iteration_id)

        params.extend([limit, offset])
        rows = self._conn.execute(
            f"SELECT * FROM commits {where} "
            "ORDER BY committed_at DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    # --- Read: search -------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 20,
        iteration_id: Optional[int] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search decisions and commits by text with optional filters.

        If FTS5 is available, use MATCH for full-text search. Otherwise use
        LIKE as a fallback (slower but it works).

        Results carry the source type and the full data of the original row.
        After the first search, post-processing filters apply to dates, tags
        and status.

        Args:
            query: search term.
            limit: maximum number of results.
            iteration_id: if given, filter by iteration.
            since: minimum ISO 8601 date. Excludes results whose
                ``decided_at`` or ``committed_at`` is earlier.
            until: maximum ISO 8601 date. Excludes results whose
                ``decided_at`` or ``committed_at`` is later.
            tags: list of tags. For decisions, at least one must match the
                tags of the row.
            status: required status. Applies to decisions only.

        Returns:
            List of result dictionaries, each with the ``source_type`` key
            ('decision' or 'commit') and the row data.
        """
        results: List[Dict[str, Any]] = []

        if self._fts_enabled:
            results = self._search_fts(
                query, limit, iteration_id,
                since=since, until=until, tags=tags, status=status,
            )
        else:
            results = self._search_like(
                query, limit, iteration_id,
                since=since, until=until, tags=tags, status=status,
            )

        return results

    @staticmethod
    def _search_date_value(result: Dict[str, Any]) -> str:
        """Return the relevant date of the result for tie-breaks."""
        source_type = result.get("source_type", "")
        if source_type == "decision":
            return str(result.get("decided_at", ""))
        if source_type == "event":
            return str(result.get("created_at", ""))
        return str(result.get("committed_at", ""))

    @staticmethod
    def _like_pattern(query: str) -> str:
        """Escape LIKE wildcards so the query is treated as literal text."""
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        return f"%{escaped}%"

    def _iter_search_field_values(
        self, result: Dict[str, Any]
    ) -> Iterable[Tuple[int, str]]:
        """Expose searchable fields with weights for relevance sorting."""
        source_type = result.get("source_type", "")
        fields = {
            "decision": [
                ("title", 6, False),
                ("chosen", 5, False),
                ("context", 4, False),
                ("alternatives", 3, True),
                ("rationale", 2, False),
            ],
            "commit": [
                ("message", 6, False),
                ("files", 5, True),
            ],
            "event": [
                ("summary", 5, False),
                ("content", 4, False),
            ],
        }.get(source_type, [])

        for field_name, weight, is_json_list in fields:
            raw_value = result.get(field_name)
            if not raw_value:
                continue

            values: List[Any]
            if is_json_list:
                try:
                    parsed = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
                except (json.JSONDecodeError, TypeError):
                    parsed = raw_value
                values = parsed if isinstance(parsed, list) else [parsed]
            else:
                values = [raw_value]

            for value in values:
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    yield weight, text

    @staticmethod
    def _search_match_signature(text: str, normalized_query: str) -> Optional[Tuple[int, int, int, int, int]]:
        """Compute a match signature where larger values are better."""
        normalized_text = text.casefold()
        index = normalized_text.find(normalized_query)
        if index < 0:
            return None

        exact = 1 if normalized_text == normalized_query else 0
        starts = 1 if normalized_text.startswith(normalized_query) else 0
        word_boundary = 1 if re.search(rf"(?<!\w){re.escape(normalized_query)}", normalized_text) else 0
        occurrences = normalized_text.count(normalized_query)
        # Indexes closer to the start are more relevant.
        position_score = max(0, 10_000 - index)
        return (exact, starts, word_boundary, occurrences, position_score)

    def _search_sort_key(self, result: Dict[str, Any], normalized_query: str) -> Tuple[Any, ...]:
        """Build a sort key that is consistent between FTS and LIKE."""
        best_match = (0, 0, 0, 0, 0, 0)
        for weight, text in self._iter_search_field_values(result):
            signature = self._search_match_signature(text, normalized_query)
            if signature is None:
                continue
            candidate = (weight, *signature)
            if candidate > best_match:
                best_match = candidate

        raw_fts_rank = result.get("_fts_rank")
        fts_rank_score = 0.0
        if isinstance(raw_fts_rank, (int, float)):
            # bm25() gives better results with smaller values.
            fts_rank_score = -float(raw_fts_rank)

        return (
            *best_match,
            fts_rank_score,
            self._search_date_value(result),
            int(result.get("id", 0) or 0),
        )

    def _dedupe_search_results(
        self,
        results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Deduplicate by type+id and keep the best helper data available."""
        deduped: Dict[Tuple[str, int], Dict[str, Any]] = {}

        for item in results:
            source_type = str(item.get("source_type", ""))
            item_id = int(item.get("id", 0) or 0)
            key = (source_type, item_id)

            existing = deduped.get(key)
            if existing is None:
                deduped[key] = dict(item)
                continue

            new_rank = item.get("_fts_rank")
            current_rank = existing.get("_fts_rank")
            if isinstance(new_rank, (int, float)) and (
                not isinstance(current_rank, (int, float))
                or float(new_rank) < float(current_rank)
            ):
                existing["_fts_rank"] = new_rank

        return list(deduped.values())

    def _search_like_candidates(
        self,
        query: str,
        fetch_limit: int,
        iteration_id: Optional[int],
    ) -> List[Dict[str, Any]]:
        """Collect LIKE candidates from all sources with no type bias."""
        like_pattern = self._like_pattern(query)
        results: List[Dict[str, Any]] = []

        if iteration_id is not None:
            decision_rows = self._conn.execute(
                "SELECT * FROM decisions "
                "WHERE (title LIKE ? ESCAPE '\\' OR context LIKE ? ESCAPE '\\' "
                "       OR chosen LIKE ? ESCAPE '\\' OR rationale LIKE ? ESCAPE '\\' "
                "       OR alternatives LIKE ? ESCAPE '\\') "
                "  AND iteration_id = ? "
                "ORDER BY decided_at DESC LIMIT ?",
                (
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    iteration_id,
                    fetch_limit,
                ),
            ).fetchall()
        else:
            decision_rows = self._conn.execute(
                "SELECT * FROM decisions "
                "WHERE title LIKE ? ESCAPE '\\' OR context LIKE ? ESCAPE '\\' "
                "   OR chosen LIKE ? ESCAPE '\\' OR rationale LIKE ? ESCAPE '\\' "
                "   OR alternatives LIKE ? ESCAPE '\\' "
                "ORDER BY decided_at DESC LIMIT ?",
                (
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    like_pattern,
                    fetch_limit,
                ),
            ).fetchall()

        for row in decision_rows:
            results.append({"source_type": "decision", **dict(row)})

        if iteration_id is not None:
            commit_rows = self._conn.execute(
                "SELECT * FROM commits "
                "WHERE (message LIKE ? ESCAPE '\\' OR files LIKE ? ESCAPE '\\') "
                "  AND iteration_id = ? "
                "ORDER BY committed_at DESC LIMIT ?",
                (like_pattern, like_pattern, iteration_id, fetch_limit),
            ).fetchall()
        else:
            commit_rows = self._conn.execute(
                "SELECT * FROM commits "
                "WHERE message LIKE ? ESCAPE '\\' OR files LIKE ? ESCAPE '\\' "
                "ORDER BY committed_at DESC LIMIT ?",
                (like_pattern, like_pattern, fetch_limit),
            ).fetchall()

        for row in commit_rows:
            results.append({"source_type": "commit", **dict(row)})

        if iteration_id is not None:
            event_rows = self._conn.execute(
                "SELECT * FROM events "
                "WHERE (summary LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\') "
                "  AND iteration_id = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (like_pattern, like_pattern, iteration_id, fetch_limit),
            ).fetchall()
        else:
            event_rows = self._conn.execute(
                "SELECT * FROM events "
                "WHERE summary LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' "
                "ORDER BY created_at DESC LIMIT ?",
                (like_pattern, like_pattern, fetch_limit),
            ).fetchall()

        for row in event_rows:
            results.append({"source_type": "event", **dict(row)})

        return results

    def _apply_post_filters(
        self,
        results: List[Dict[str, Any]],
        since: Optional[str] = None,
        until: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Apply post-processing filters to the search results.

        This method holds the filter logic that FTS5 search and the LIKE
        fallback share. Date filters apply to all result types (decisions
        and commits). Tag and status filters apply only to results of type
        ``decision``.

        Args:
            results: list of unfiltered results.
            since: minimum ISO date (inclusive).
            until: maximum ISO date (inclusive).
            tags: required tags (at least one must match).
            status: required status for decisions.

        Returns:
            Filtered list of results.
        """
        filtered: List[Dict[str, Any]] = []

        for r in results:
            source_type = r.get("source_type", "")

            # --- Date filter ---
            # decided_at for decisions, committed_at for commits
            if source_type == "decision":
                date_field = "decided_at"
            elif source_type == "event":
                date_field = "created_at"
            else:
                date_field = "committed_at"
            record_date = r.get(date_field, "")

            if since and record_date and record_date < since:
                continue
            if until and record_date and record_date > until:
                continue

            # --- Decision-only filters ---
            if source_type == "decision":
                # Tag filter: at least one must match
                if tags:
                    record_tags_raw = r.get("tags", "[]")
                    try:
                        record_tags = json.loads(record_tags_raw)
                    except (json.JSONDecodeError, TypeError):
                        record_tags = []
                    if not any(t in record_tags for t in tags):
                        continue

                # Status filter
                if status and r.get("status") != status:
                    continue

            # Commits and events have no tags or status. If those filters
            # are given, they are excluded.
            elif source_type in {"commit", "event"} and (tags or status):
                continue

            filtered.append(r)

        return filtered

    def _execute_search(
        self,
        fetch_fn,
        query: str,
        limit: int,
        since: Optional[str] = None,
        until: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Run a search with the given strategy and apply post-filters.

        Holds the logic shared by FTS5 and LIKE: margin calculation,
        post-filtering by date/tags/status and truncation to the limit.
        ``fetch_fn`` gets the raw results: it receives the computed
        ``fetch_limit`` and returns a list of dicts with ``source_type``.

        Args:
            fetch_fn: function that takes (fetch_limit: int) and returns a
                list of dicts with the raw results.
            limit: maximum number of final results.
            since: minimum ISO date (post-filter).
            until: maximum ISO date (post-filter).
            tags: required tags (post-filter, decisions only).
            status: required status (post-filter, decisions only).
        """
        fetch_limit = max(limit * _FETCH_MARGIN, limit)

        results = fetch_fn(fetch_limit)
        results = self._dedupe_search_results(results)

        if since or until or tags or status:
            results = self._apply_post_filters(
                results, since=since, until=until, tags=tags, status=status,
            )

        normalized_query = query.casefold().strip()
        results = sorted(
            results,
            key=lambda item: self._search_sort_key(item, normalized_query),
            reverse=True,
        )

        return results[:limit]

    def _search_fts(
        self,
        query: str,
        limit: int,
        iteration_id: Optional[int],
        since: Optional[str] = None,
        until: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search with FTS5 MATCH. _execute_search does the post-filtering."""
        # FTS5 needs special characters in the query escaped.
        # Double quotes wrap the query so it is a literal phrase.
        safe_query = '"' + query.replace('"', '""') + '"'

        def fetch(fetch_limit: int) -> List[Dict[str, Any]]:
            rows = self._conn.execute(
                "SELECT source_type, source_id, bm25(memory_fts) AS fts_rank "
                "FROM memory_fts "
                "WHERE memory_fts MATCH ? "
                "ORDER BY bm25(memory_fts), rowid DESC LIMIT ?",
                (safe_query, fetch_limit),
            ).fetchall()
            results: List[Dict[str, Any]] = []
            for row in rows:
                source_type = row["source_type"]
                source_id = int(row["source_id"])
                record = self._fetch_source_record(source_type, source_id)
                if record is None:
                    continue
                if iteration_id is not None:
                    if record.get("iteration_id") != iteration_id:
                        continue
                results.append(
                    {
                        "source_type": source_type,
                        "_fts_rank": float(row["fts_rank"]),
                        **record,
                    }
                )

            # FTS does not cover some helper fields such as commit.files.
            # LIKE fills the gap so the public contract stays stable.
            results.extend(self._search_like_candidates(query, fetch_limit, iteration_id))
            return results

        return self._execute_search(
            fetch, query, limit, since=since, until=until, tags=tags, status=status,
        )

    def _search_like(
        self,
        query: str,
        limit: int,
        iteration_id: Optional[int],
        since: Optional[str] = None,
        until: Optional[str] = None,
        tags: Optional[List[str]] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search with LIKE as a fallback. _execute_search does the post-filtering."""
        def fetch(fetch_limit: int) -> List[Dict[str, Any]]:
            return self._search_like_candidates(query, fetch_limit, iteration_id)

        return self._execute_search(
            fetch, query, limit, since=since, until=until, tags=tags, status=status,
        )

    def _fetch_source_record(
        self, source_type: str, source_id: int
    ) -> Optional[Dict[str, Any]]:
        """Get the full row of a source indexed in FTS."""
        tables = {
            "decision": "decisions",
            "commit": "commits",
            "event": "events",
        }
        table = tables.get(source_type)
        if table is None:
            return None
        row = self._conn.execute(
            f"SELECT * FROM {table} WHERE id = ?", (source_id,)
        ).fetchone()
        return dict(row) if row else None

    # --- Read: timeline -----------------------------------------------------

    def get_timeline(
        self,
        iteration_id: int,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get the event timeline of an iteration.

        Args:
            iteration_id: iteration ID.
            limit: maximum number of events.

        Returns:
            List of dictionaries with the data of each event, in
            chronological order.
        """
        rows = self._conn.execute(
            "SELECT * FROM events WHERE iteration_id = ? "
            "ORDER BY created_at ASC LIMIT ?",
            (iteration_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_events(
        self,
        limit: int = 50,
        offset: int = 0,
        iteration_id: Optional[int] = None,
        event_type: Optional[str] = None,
        ascending: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return recent events with optional filters."""
        params: List[Any] = []
        conditions: List[str] = []

        if iteration_id is not None:
            conditions.append("iteration_id = ?")
            params.append(iteration_id)

        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        order = "ASC" if ascending else "DESC"
        params.extend([limit, offset])
        rows = self._conn.execute(
            f"SELECT * FROM events {where} "
            f"ORDER BY created_at {order} LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def count_events(
        self,
        iteration_id: Optional[int] = None,
        event_type: Optional[str] = None,
    ) -> int:
        """Count events with the same filters as get_events."""
        params: List[Any] = []
        conditions: List[str] = []

        if iteration_id is not None:
            conditions.append("iteration_id = ?")
            params.append(iteration_id)

        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)

        where = ""
        if conditions:
            where = "WHERE " + " AND ".join(conditions)

        row = self._conn.execute(
            f"SELECT COUNT(*) AS cnt FROM events {where}",
            params,
        ).fetchone()
        return int(row["cnt"]) if row else 0

    def get_event_counts_by_type(self, limit: int = 12) -> List[Dict[str, Any]]:
        """Summarize events grouped by type, sorted by frequency."""
        rows = self._conn.execute(
            "SELECT event_type, COUNT(*) AS total "
            "FROM events "
            "GROUP BY event_type "
            "ORDER BY total DESC, event_type ASC "
            "LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    # --- Read: stats --------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """
        Return general stats of the project memory.

        Returns:
            Dictionary with counters (iterations, decisions, commits,
            events), FTS5 state, schema version and creation date.
        """
        stats: Dict[str, Any] = {}

        # Counters
        for table in ("iterations", "decisions", "commits", "events"):
            row = self._conn.execute(
                f"SELECT COUNT(*) as cnt FROM {table}"
            ).fetchone()
            stats[f"total_{table}"] = row["cnt"]

        # Metadata
        meta_rows = self._conn.execute("SELECT key, value FROM meta").fetchall()
        for row in meta_rows:
            stats[row["key"]] = row["value"]

        return stats

    # --- Maintenance --------------------------------------------------------

    def check_health(self) -> Dict[str, Any]:
        """Validate the integrity of the memory database.

        Runs a set of diagnostic checks to detect configuration, sync or
        capacity problems before they affect the normal plugin operation.

        Checks:
            - Correct schema version.
            - FTS5 in sync (FTS count vs source tables).
            - File permissions (0600).
            - DB size (warning if > 50 MB).

        Returns:
            Dictionary with status (healthy, warnings, errors), the list of
            issues and DB metadata.
        """
        issues: List[str] = []

        # Schema version
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        schema_version = row[0] if row else "unknown"
        if schema_version != str(_SCHEMA_VERSION):
            issues.append(
                f"Версия схемы устарела: {schema_version} "
                f"(ожидалась: {_SCHEMA_VERSION})"
            )

        # FTS5 in sync
        if self._fts_enabled:
            expected_counts = self._expected_fts_counts()

            for source_type, expected in expected_counts.items():
                actual = self._conn.execute(
                    "SELECT COUNT(*) FROM memory_fts WHERE source_type = ?",
                    (source_type,),
                ).fetchone()[0]
                if actual != expected:
                    issues.append(
                        f"FTS5 рассинхронизирован для {source_type}: "
                        f"записей {actual}, ожидалось {expected}"
                    )

            unknown_sources = self._conn.execute(
                "SELECT COUNT(*) FROM memory_fts "
                "WHERE source_type NOT IN ('decision', 'commit', 'event')"
            ).fetchone()[0]
            if unknown_sources:
                issues.append(
                    f"FTS5 содержит записи с неизвестным source_type: {unknown_sources}"
                )

            orphan_queries = {
                "decision": (
                    "SELECT COUNT(*) FROM memory_fts f "
                    "LEFT JOIN decisions d ON CAST(f.source_id AS INTEGER) = d.id "
                    "WHERE f.source_type = 'decision' AND d.id IS NULL"
                ),
                "commit": (
                    "SELECT COUNT(*) FROM memory_fts f "
                    "LEFT JOIN commits c ON CAST(f.source_id AS INTEGER) = c.id "
                    "WHERE f.source_type = 'commit' AND c.id IS NULL"
                ),
                "event": (
                    "SELECT COUNT(*) FROM memory_fts f "
                    "LEFT JOIN events e ON CAST(f.source_id AS INTEGER) = e.id "
                    "WHERE f.source_type = 'event' AND e.id IS NULL"
                ),
            }
            for source_type, sql in orphan_queries.items():
                orphan_count = self._conn.execute(sql).fetchone()[0]
                if orphan_count:
                    issues.append(
                        f"FTS5 содержит осиротевшие записи {source_type}: {orphan_count}"
                    )

        # File permissions
        permissions_ok = True
        try:
            mode = os.stat(self._db_path).st_mode
            perms = stat.S_IMODE(mode)
            if perms != stat.S_IMODE(_DB_PERMISSIONS):
                permissions_ok = False
                issues.append(
                    f"Неверные права доступа: {oct(perms)} (ожидалось: 0600)"
                )
        except OSError:
            permissions_ok = False
            issues.append("Не удалось проверить права доступа к файлу")

        # DB size
        size_bytes = 0
        try:
            size_bytes = os.path.getsize(self._db_path)
            for suffix in ("-wal", "-shm"):
                aux_path = self._db_path + suffix
                if os.path.exists(aux_path):
                    size_bytes += os.path.getsize(aux_path)
            if size_bytes > 50 * 1024 * 1024:  # 50 MB
                issues.append(
                    f"База данных слишком большая: {size_bytes / (1024*1024):.1f} MB"
                )
        except OSError:
            pass

        # Global status: critical errors (schema or FTS) vs minor warnings
        if any("устарела" in i or "рассинхронизирован" in i for i in issues):
            status = "errors"
        elif issues:
            status = "warnings"
        else:
            status = "healthy"

        return {
            "status": status,
            "issues": issues,
            "schema_version": schema_version,
            "fts_enabled": self._fts_enabled,
            "permissions_ok": permissions_ok,
            "size_bytes": size_bytes,
        }

    def purge_old_events(self, retention_days: int) -> int:
        """
        Delete events older than the retention window.

        Only events are purged. Decisions and iterations are always kept
        because of their high value for traceability.

        Args:
            retention_days: number of retention days.

        Returns:
            Number of deleted events.
        """
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=retention_days)
        ).isoformat()
        event_rows = self._conn.execute(
            "SELECT id FROM events WHERE created_at < ?",
            (cutoff,),
        ).fetchall()
        event_ids = [row[0] for row in event_rows]

        cursor = self._conn.execute(
            "DELETE FROM events WHERE created_at < ?", (cutoff,)
        )

        if self._fts_enabled and event_ids:
            self._conn.executemany(
                "DELETE FROM memory_fts "
                "WHERE source_type = 'event' AND source_id = ?",
                [(event_id,) for event_id in event_ids],
            )
        self._conn.commit()
        return cursor.rowcount

    # --- Export and import --------------------------------------------------

    def export_decisions_markdown(
        self,
        path: str,
        iteration_id: Optional[int] = None,
    ) -> int:
        """Export the decisions to a Markdown file in an ADR-like format.

        Builds a structured document where each decision is an Architecture
        Decision Record with title, date, status, tags, context, chosen
        decision, rejected alternatives and rationale.

        Args:
            path: path of the target Markdown file. The parent directory is
                created if it does not exist.
            iteration_id: if given, export only the decisions of that
                iteration.

        Returns:
            Number of exported decisions.
        """
        decisions = self.get_decisions(
            limit=1000, iteration_id=iteration_id,
        )
        if iteration_id is None:
            decisions = list(self.iter_decisions(batch_size=500))
        else:
            decisions = list(
                self.iter_decisions(iteration_id=iteration_id, batch_size=500)
            )

        lines: List[str] = []
        lines.append("# Журнал архитектурных решений\n")
        lines.append("")

        for dec in decisions:
            lines.append(f"## {dec['title']}")
            lines.append("")
            lines.append(f"- **Дата:** {dec.get('decided_at', 'N/A')}")
            lines.append(f"- **Статус:** {dec.get('status', 'active')}")

            # Tags
            tags_raw = dec.get("tags", "[]")
            try:
                tags = json.loads(tags_raw) if tags_raw else []
            except (json.JSONDecodeError, TypeError):
                tags = []
            if tags:
                lines.append(f"- **Теги:** {', '.join(tags)}")

            lines.append("")

            # Context
            if dec.get("context"):
                lines.append("### Контекст")
                lines.append("")
                lines.append(dec["context"])
                lines.append("")

            # Chosen decision
            lines.append("### Решение")
            lines.append("")
            lines.append(dec["chosen"])
            lines.append("")

            # Rejected alternatives
            if dec.get("alternatives"):
                try:
                    alts = json.loads(dec["alternatives"])
                except (json.JSONDecodeError, TypeError):
                    alts = []
                if alts:
                    lines.append("### Отклонённые альтернативы")
                    lines.append("")
                    for alt in alts:
                        lines.append(f"- {alt}")
                    lines.append("")

            # Rationale
            if dec.get("rationale"):
                lines.append("### Обоснование")
                lines.append("")
                lines.append(dec["rationale"])
                lines.append("")

            lines.append("---")
            lines.append("")

        # Create the parent directory if it does not exist
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return len(decisions)

    def import_git_history(
        self,
        repo_path: str,
        limit: int = 100,
    ) -> int:
        """Import the commit history of a Git repository.

        Runs ``git log`` on the given repository and records each commit in
        the memory with its author, real date and file list. The operation
        is idempotent: commits whose SHA already exists in the database are
        ignored silently.

        Args:
            repo_path: path to the root directory of the Git repository.
            limit: maximum number of commits to import (default 100).

        Returns:
            Number of new imported commits (excludes the ones that already
            existed in the database).
        """
        result = subprocess.run(
            [
                "git", "log",
                f"--max-count={limit}",
                "--format=%H%x1f%s%x1f%an%x1f%aI",
                "--name-only",
            ],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )

        # Parse the output: each commit starts with the format line (it
        # contains the \x1f separator), the next lines without it are file
        # names, and an empty line separates blocks.
        new_count = 0
        current_commit: Optional[Dict[str, str]] = None
        current_files: List[str] = []

        for line in result.stdout.splitlines():
            if "\x1f" in line:
                # If a commit is pending, record it
                if current_commit is not None:
                    commit_id = self.log_commit(
                        sha=current_commit["sha"],
                        message=current_commit["message"],
                        author=current_commit["author"],
                        files=current_files,
                        files_changed=len(current_files),
                        committed_at=current_commit.get("committed_at"),
                        auto_link_iteration=False,
                    )
                    if commit_id is not None:
                        new_count += 1

                # New commit
                parts = line.split("\x1f", 3)
                current_commit = {
                    "sha": parts[0],
                    "message": parts[1] if len(parts) > 1 else "",
                    "author": parts[2] if len(parts) > 2 else "",
                    "committed_at": parts[3] if len(parts) > 3 else "",
                }
                current_files = []
            elif line.strip():
                # File name
                current_files.append(line.strip())
            # Empty line: block separator (nothing special to do)

        # Record the last pending commit
        if current_commit is not None:
            commit_id = self.log_commit(
                sha=current_commit["sha"],
                message=current_commit["message"],
                author=current_commit["author"],
                files=current_files,
                files_changed=len(current_files),
                committed_at=current_commit.get("committed_at"),
                auto_link_iteration=False,
            )
            if commit_id is not None:
                new_count += 1

        return new_count

    def import_adrs(self, adr_dir: str = "docs/adr") -> int:
        """Import ADR (Architecture Decision Record) files as decisions.

        Walks the ``*.md`` files of the given directory and extracts from
        each one the title (first ``#`` heading), the context (section
        ``## Context``, ``## Contexto`` or ``## Контекст``) and the decision
        (section ``## Decision``, ``## Decisión`` or ``## Решение``). Each
        file is recorded as a new decision with the ``imported-adr`` tag.

        Args:
            adr_dir: path to the directory with the ADR files.
                Default ``docs/adr``.

        Returns:
            Number of imported decisions.
        """
        adr_path = Path(adr_dir)
        if not adr_path.is_dir():
            return 0

        count = 0
        for md_file in sorted(adr_path.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            title = self._extract_heading(content)
            context = self._extract_section(
                content, ["## Context", "## Contexto", "## Контекст"]
            )
            chosen = self._extract_section(
                content, ["## Decision", u"## Decisi\u00f3n", "## Решение"]
            )

            if title and chosen:
                self.log_decision(
                    title=title,
                    chosen=chosen,
                    context=context,
                    tags=["imported-adr"],
                )
                count += 1

        return count

    @staticmethod
    def _extract_heading(content: str) -> Optional[str]:
        """Extract the title from the first ``#`` heading of Markdown content.

        Args:
            content: full Markdown text of the file.

        Returns:
            Title text without the ``#`` marker, or None if no level 1
            heading is found.
        """
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped[2:].strip()
        return None

    @staticmethod
    def _extract_section(
        content: str, headers: List[str]
    ) -> Optional[str]:
        """Extract the body of a Markdown section found by its heading.

        Looks for any of the given headings and returns the text between
        that heading and the next heading of the same or higher level.

        Args:
            content: full Markdown text of the file.
            headers: list of headings to look for (e.g.
                ``["## Context", "## Contexto"]``).

        Returns:
            Section text without the heading, or None if none of the
            headings is found.
        """
        lines = content.splitlines()
        capture = False
        result_lines: List[str] = []

        for line in lines:
            stripped = line.strip()
            if any(stripped.startswith(h) for h in headers):
                capture = True
                continue
            if capture:
                # Stop at the next heading of level 2 or higher
                if stripped.startswith("## ") or stripped.startswith("# "):
                    break
                result_lines.append(line)

        if not result_lines:
            return None

        text = "\n".join(result_lines).strip()
        return text if text else None


    def get_session_context(self) -> Dict[str, Any]:
        """Build the structured context to inject when a session resumes.

        Collects the active iteration and the decisions in one dictionary
        that can be serialized and injected as context in Claude Code.

        Returns:
            Dictionary with the keys: iteration, decisions.
        """
        active = self.get_active_iteration()
        decisions = []
        if active:
            decisions = self.get_decisions(iteration_id=active["id"], limit=20)

        return {
            "iteration": active,
            "decisions": decisions,
        }

    # --- Life cycle ---------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
