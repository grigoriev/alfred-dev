#!/usr/bin/env python3
"""
Stdio MCP server for the persistent Alfred Dev memory.

Implements the Model Context Protocol over stdin/stdout with only the Python
standard library (json, sys, logging). The modern MCP stdio transport uses
JSON-RPC 2.0 with one JSON message per line. The server can also read the
legacy Content-Length framing for older tools.

The server exposes fifteen tools that let Alfred agents query, record and
manage the project memory database:

    Query (10 original):
    - memory_search: text search with time, tag and status filters.
    - memory_log_decision: records a formal design decision with tags.
    - memory_log_commit: records a commit with the changed files.
    - memory_get_iteration: details of one iteration (or the latest).
    - memory_get_timeline: event timeline of one iteration.
    - memory_stats: general memory statistics.
    - memory_log_decision / memory_manage_iteration / memory_log_event / memory_log_commit
    - memory_link_decisions: links two related decisions.
    - memory_get_decisions: filtered list of decisions.

    Management (5 new in v0.2.3):
    - memory_update_decision: updates the status and tags of a decision.
    - memory_link_decisions: creates relations between decisions.
    - memory_health: checks database integrity.
    - memory_export: exports decisions to Markdown (ADR format).
    - memory_import: imports from Git history or ADR files.

Lifecycle:
    Claude Code starts this process at session start and keeps it alive.
    At startup the server resolves the DB path relative to the working
    directory (``$PWD/.claude/alfred-memory.db``), opens the connection,
    ensures the schema and waits for MCP calls on stdin.

Security:
    MemoryDB sanitizes secrets internally. This server only passes the
    received parameters to the core/memory.py API.

Usage:
    Do not run it by hand. Claude Code manages it through the MCP
    configuration in ``.mcp.json``.
"""

import json
import logging
import os
import sys
import traceback
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
# Logs go to stderr so they do not interfere with the MCP protocol on
# stdout. By default we emit only warnings: some MCP health checks treat
# any early stderr noise as a connection failure.

logging.basicConfig(
    stream=sys.stderr,
    level=getattr(
        logging,
        os.environ.get("ALFRED_MEMORY_LOG_LEVEL", "WARNING").upper(),
        logging.WARNING,
    ),
    format="[alfred-memory] %(asctime)s %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
_log = logging.getLogger("alfred-memory")

_SEARCH_LIMIT_DEFAULT = 20
_SEARCH_LIMIT_MAX = 100
_DECISIONS_LIMIT_DEFAULT = 50
_DECISIONS_LIMIT_MAX = 200
_GIT_IMPORT_LIMIT_DEFAULT = 100
_GIT_IMPORT_LIMIT_MAX = 1000
_EVENT_TYPE_MAX = 80
_EVENT_PHASE_MAX = 80
_EVENT_SUMMARY_MAX = 500
_EVENT_CONTENT_MAX = 8000
_EVENT_PAYLOAD_MAX = 8000


def _bounded_text(value: Any, maximum: int) -> tuple[Optional[str], bool, int]:
    """Normalize MCP text and truncate inputs that are too large."""
    if value is None:
        return None, False, 0

    text = str(value)
    if len(text) <= maximum:
        return text, False, len(text)

    suffix = (
        f"\n\n[содержимое обрезано alfred-memory: "
        f"исходно {len(text)} символов, максимум {maximum}]"
    )
    return text[:maximum].rstrip() + suffix, True, len(text)


def _bounded_event_payload(
    value: Any,
) -> tuple[Optional[Dict[str, Any]], bool, int]:
    """Limit event payloads received over MCP without losing traceability."""
    if value is None:
        return None, False, 0
    if not isinstance(value, dict):
        raise ValueError("Поле 'payload' должно быть JSON-объектом.")

    serialized = json.dumps(value, ensure_ascii=False, default=str)
    if len(serialized) <= _EVENT_PAYLOAD_MAX:
        return value, False, len(serialized)

    return (
        {
            "_truncated": True,
            "preview": serialized[:_EVENT_PAYLOAD_MAX].rstrip(),
            "original_chars": len(serialized),
            "max_chars": _EVENT_PAYLOAD_MAX,
        },
        True,
        len(serialized),
    )


def _load_plugin_version() -> str:
    """Read the published plugin version to expose it over MCP."""
    plugin_path = os.path.join(_PLUGIN_ROOT, ".claude-plugin", "plugin.json")
    try:
        with open(plugin_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return str(data.get("version", "0.7.0"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return "0.7.0"


def _bounded_limit(
    value: Any,
    default: int,
    maximum: int,
) -> tuple[int, bool, Optional[int]]:
    """
    Normalize limits received over MCP to prevent huge outputs or loads.

    Returns ``(limit, capped, requested)``. ``requested`` is ``None``
    when the client did not send a usable value.
    """
    if value is None:
        return default, False, None

    try:
        requested = int(value)
    except (TypeError, ValueError):
        return default, False, None

    if requested < 1:
        return 1, True, requested
    if requested > maximum:
        return maximum, True, requested
    return requested, False, requested

# ---------------------------------------------------------------------------
# MemoryDB import
# ---------------------------------------------------------------------------
# The server imports core.memory, which lives in the plugin root.
# Add the plugin root (the parent directory of mcp/) to sys.path.

_PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PLUGIN_ROOT not in sys.path:
    sys.path.insert(0, _PLUGIN_ROOT)

from core.memory import MemoryDB  # noqa: E402
from core.memory_config import load_memory_config  # noqa: E402


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------
# Each tool has a name, a description and an inputSchema (JSON Schema
# draft-07). The server returns this list for the ``tools/list`` method
# and uses it to dispatch ``tools/call``.

_TOOLS: List[Dict[str, Any]] = [
    {
        "name": "memory_search",
        "description": (
            "Ищет по тексту в памяти проекта (решения и commits). "
            "Использует FTS5, если он доступен, иначе LIKE как fallback."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Текст поискового запроса.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Максимальное число результатов "
                        f"(по умолчанию {_SEARCH_LIMIT_DEFAULT}, максимум {_SEARCH_LIMIT_MAX})."
                    ),
                    "default": _SEARCH_LIMIT_DEFAULT,
                    "minimum": 1,
                    "maximum": _SEARCH_LIMIT_MAX,
                },
                "iteration_id": {
                    "type": "integer",
                    "description": "Фильтр результатов по ID итерации.",
                },
                "since": {
                    "type": "string",
                    "description": "Только результаты после этой даты (ISO 8601).",
                },
                "until": {
                    "type": "string",
                    "description": "Только результаты до этой даты (ISO 8601).",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Только решения с любой из этих меток.",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "superseded", "deprecated"],
                    "description": "Фильтр решений по статусу.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_log_decision",
        "description": (
            "Записывает формальное проектное решение в память проекта. "
            "Если другая итерация не указана, решение автоматически привязывается к активной."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Краткое название решения.",
                },
                "chosen": {
                    "type": "string",
                    "description": "Выбранный вариант.",
                },
                "context": {
                    "type": "string",
                    "description": "Проблема или ситуация, которую решали.",
                },
                "alternatives": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Отклонённые варианты.",
                },
                "rationale": {
                    "type": "string",
                    "description": "Обоснование выбора.",
                },
                "impact": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Уровень влияния решения.",
                },
                "phase": {
                    "type": "string",
                    "description": "Фаза процесса, в которой принято решение.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Метки для классификации решения.",
                },
            },
            "required": ["title", "chosen"],
        },
    },
    {
        "name": "memory_log_commit",
        "description": (
            "Записывает commit в память и при необходимости привязывает его к "
            "ранее принятым решениям. Если SHA уже есть, запись пропускается (идемпотентно)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "sha": {
                    "type": "string",
                    "description": "SHA-хеш commit.",
                },
                "message": {
                    "type": "string",
                    "description": "Сообщение commit.",
                },
                "author": {
                    "type": "string",
                    "description": "Автор commit.",
                },
                "committed_at": {
                    "type": "string",
                    "description": "Дата commit в формате ISO 8601.",
                },
                "decision_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": (
                        "ID решений, которые нужно привязать к этому commit."
                    ),
                },
                "iteration_id": {
                    "type": "integer",
                    "description": (
                        "ID итерации. Если не указан, используется активная."
                    ),
                },
                "files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Список файлов, затронутых commit.",
                },
            },
            "required": ["sha"],
        },
    },
    {
        "name": "memory_get_iteration",
        "description": (
            "Возвращает полные данные итерации. Если ID не указан, "
            "возвращает активную или самую последнюю итерацию."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": (
                        "ID итерации. Если не указан, возвращает активную "
                        "или последнюю записанную."
                    ),
                },
            },
            "required": [],
        },
    },
    {
        "name": "memory_get_timeline",
        "description": (
            "Возвращает полную хронологию событий итерации, "
            "от самых старых к самым новым."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "iteration_id": {
                    "type": "integer",
                    "description": "ID итерации, хронологию которой нужно получить.",
                },
            },
            "required": ["iteration_id"],
        },
    },
    {
        "name": "memory_stats",
        "description": (
            "Возвращает общую статистику памяти проекта: "
            "число итераций, решений, commits и событий, режим "
            "поиска и метаданные."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "memory_manage_iteration",
        "description": (
            "Управляет жизненным циклом итераций: запускает новую "
            "или завершает существующую. Позволяет агентам управлять "
            "процессом без hook автоматического захвата."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "complete"],
                    "description": (
                        "Действие: 'start' запускает новую "
                        "итерацию, 'complete' закрывает существующую."
                    ),
                },
                "command": {
                    "type": "string",
                    "description": (
                        "Команда, которая запустила итерацию (например, 'feature', 'fix'). "
                        "Нужна только для action='start'."
                    ),
                },
                "description": {
                    "type": "string",
                    "description": "Произвольное описание итерации.",
                },
                "iteration_id": {
                    "type": "integer",
                    "description": (
                        "ID итерации для завершения. Только для action='complete'. "
                        "Если не указан, завершается активная итерация."
                    ),
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "memory_log_event",
        "description": (
            "Записывает произвольное событие в хронологию итерации. "
            "Подходит для учёта одобренных gates, запущенных агентов и "
            "собственных вех процесса."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_type": {
                    "type": "string",
                    "maxLength": _EVENT_TYPE_MAX,
                    "description": (
                        "Тип события (например, 'gate_approved', 'agent_executed', "
                        "'phase_completed', 'custom')."
                    ),
                },
                "phase": {
                    "type": "string",
                    "maxLength": _EVENT_PHASE_MAX,
                    "description": "Фаза процесса, в которой произошло событие.",
                },
                "payload": {
                    "type": "object",
                    "description": (
                        "JSON-данные события. Если после сериализации они длиннее "
                        f"{_EVENT_PAYLOAD_MAX} символов, сохраняется только preview."
                    ),
                },
                "summary": {
                    "type": "string",
                    "maxLength": _EVENT_SUMMARY_MAX,
                    "description": "Краткое резюме события для быстрых запросов.",
                },
                "content": {
                    "type": "string",
                    "maxLength": _EVENT_CONTENT_MAX,
                    "description": (
                        "Полный индексируемый текст. Если не указан, как fallback используется "
                        "сериализованный payload. Слишком большие записи обрезаются."
                    ),
                },
                "iteration_id": {
                    "type": "integer",
                    "description": (
                        "ID итерации. Если не указан, используется активная."
                    ),
                },
            },
            "required": ["event_type"],
        },
    },
    {
        "name": "memory_get_decisions",
        "description": (
            "Возвращает список проектных решений из памяти. "
            "Можно фильтровать по итерации. Подходит для Библиотекаря "
            "и для отчётов по решениям."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "iteration_id": {
                    "type": "integer",
                    "description": "Фильтр решений по ID итерации.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Максимальное число решений "
                        f"(по умолчанию {_DECISIONS_LIMIT_DEFAULT}, максимум {_DECISIONS_LIMIT_MAX})."
                    ),
                    "default": _DECISIONS_LIMIT_DEFAULT,
                    "minimum": 1,
                    "maximum": _DECISIONS_LIMIT_MAX,
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Фильтр решений по меткам.",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "superseded", "deprecated"],
                    "description": "Фильтр решений по статусу.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "memory_purge",
        "description": (
            "Удаляет старые события из памяти. Решения и итерации "
            "сохраняются всегда: удаляются только события старше "
            "указанного срока хранения."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "retention_days": {
                    "type": "integer",
                    "description": (
                        "Срок хранения в днях. Более старые события удаляются."
                    ),
                },
            },
            "required": ["retention_days"],
        },
    },
    {
        "name": "memory_update_decision",
        "description": (
            "Обновляет статус или метки существующего решения. "
            "Позволяет пометить решение как superseded или deprecated и "
            "добавить метки для классификации."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {
                    "type": "integer",
                    "description": "ID решения, которое нужно обновить.",
                },
                "status": {
                    "type": "string",
                    "enum": ["active", "superseded", "deprecated"],
                    "description": "Новый статус решения.",
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Метки, которые нужно добавить к решению.",
                },
            },
            "required": ["id"],
        },
    },
    {
        "name": "memory_link_decisions",
        "description": (
            "Создаёт связь между двумя решениями. Позволяет зафиксировать, "
            "что одно решение заменяет другое, зависит от него, противоречит ему "
            "или связано с ним."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "integer",
                    "description": "ID исходного решения.",
                },
                "target_id": {
                    "type": "integer",
                    "description": "ID целевого решения.",
                },
                "link_type": {
                    "type": "string",
                    "enum": ["supersedes", "depends_on", "contradicts", "relates"],
                    "description": "Тип связи.",
                },
            },
            "required": ["source_id", "target_id", "link_type"],
        },
    },
    {
        "name": "memory_health",
        "description": (
            "Проверяет целостность базы данных памяти: "
            "версию схемы, синхронизацию FTS5, "
            "права на файл и размер БД."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "memory_export",
        "description": (
            "Экспортирует решения проекта в Markdown-файл "
            "в формате, похожем на ADR. Включает дату, статус, метки, "
            "контекст, решение, альтернативы и обоснование."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "format": {
                    "type": "string",
                    "enum": ["markdown"],
                    "description": "Формат экспорта (пока только markdown).",
                },
                "path": {
                    "type": "string",
                    "description": "Путь к выходному файлу. По умолчанию DECISIONS.md.",
                },
                "iteration_id": {
                    "type": "integer",
                    "description": "Экспортировать только решения этой итерации.",
                },
            },
            "required": ["format"],
        },
    },
    {
        "name": "memory_import",
        "description": (
            "Импортирует данные в память из внешних источников: "
            "история Git (commits) или файлы ADR (решения)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["git", "adr"],
                    "description": "Источник импорта.",
                },
                "path": {
                    "type": "string",
                    "description": "Путь к Git-репозиторию или каталогу с ADR.",
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Максимальное число записей для импорта (для git; "
                        f"по умолчанию {_GIT_IMPORT_LIMIT_DEFAULT}, максимум {_GIT_IMPORT_LIMIT_MAX})."
                    ),
                    "default": _GIT_IMPORT_LIMIT_DEFAULT,
                    "minimum": 1,
                    "maximum": _GIT_IMPORT_LIMIT_MAX,
                },
            },
            "required": ["source"],
        },
    },
]

# Set of tool names for fast lookup in tools/call
_TOOL_NAMES = {t["name"] for t in _TOOLS}


# ---------------------------------------------------------------------------
# JSON-RPC transport over stdio
# ---------------------------------------------------------------------------

_TRANSPORT_MODE = "jsonl"


def _read_message() -> Optional[Dict[str, Any]]:
    """
    Read one JSON-RPC message from stdin.

    Current MCP stdio sends one JSON object per line:
        {"jsonrpc":"2.0","id":1,"method":"initialize"}\\n

    For compatibility it also accepts the legacy LSP-style framing:
        Content-Length: <N>\\r\\n
        \\r\\n
        <N bytes of JSON>

    Returns:
        Dict with the parsed message, or None if stdin closes.

    Raises:
        ValueError: if the message does not have the expected format.
    """
    global _TRANSPORT_MODE

    while True:
        first_line = sys.stdin.buffer.readline()

        # Stop if stdin closes
        if not first_line:
            return None

        if first_line.strip():
            break

    # Modern JSONL: one complete JSON-RPC message per line.
    if first_line.lstrip().startswith(b"{"):
        _TRANSPORT_MODE = "jsonl"
        return json.loads(first_line.decode("utf-8"))

    # Legacy framing: header block followed by the exact body.
    content_length: Optional[int] = None
    header_lines = [first_line]

    while True:
        line = header_lines.pop(0) if header_lines else sys.stdin.buffer.readline()
        if not line:
            return None

        line_str = line.decode("ascii").strip()
        if line_str == "":
            break

        if line_str.lower().startswith("content-length:"):
            try:
                content_length = int(line_str.split(":", 1)[1].strip())
            except (ValueError, IndexError) as exc:
                raise ValueError(
                    f"Некорректный заголовок Content-Length: {line_str!r}"
                ) from exc

        # Ignore other headers (for example Content-Type)

    if content_length is None:
        preview = first_line.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Некорректное MCP-сообщение: {preview!r}")

    # Read the exact body
    body = sys.stdin.buffer.read(content_length)
    if len(body) < content_length:
        _log.warning(
            "Body truncated: expected %d bytes, got %d",
            content_length,
            len(body),
        )
        return None

    _TRANSPORT_MODE = "content-length"
    return json.loads(body.decode("utf-8"))


def _write_message(msg: Dict[str, Any]) -> None:
    """
    Write one JSON-RPC message to stdout.

    Uses JSONL by default, which is the current MCP stdio transport. If the
    client sent the message with Content-Length framing, reply the same way
    to stay compatible with old probes.

    Args:
        msg: dict with the JSON-RPC message to send.
    """
    body = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    if _TRANSPORT_MODE == "content-length":
        header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
        sys.stdout.buffer.write(header + body)
    else:
        sys.stdout.buffer.write(body + b"\n")
    sys.stdout.buffer.flush()


def _make_response(request_id: Any, result: Any) -> Dict[str, Any]:
    """
    Build a successful JSON-RPC 2.0 response.

    Args:
        request_id: ID of the original request.
        result: result data.

    Returns:
        Dict with the formatted response.
    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def _make_error(
    request_id: Any,
    code: int,
    message: str,
    data: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Build a JSON-RPC 2.0 error response.

    Standard error codes:
        -32700  Parse error
        -32600  Invalid Request
        -32601  Method not found
        -32602  Invalid params
        -32603  Internal error

    Args:
        request_id: ID of the original request (can be None).
        code: numeric error code.
        message: readable error description.
        data: optional extra data.

    Returns:
        Dict with the formatted error response.
    """
    error: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error,
    }


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------


class MemoryMCPServer:
    """
    Stdio MCP server for the persistent Alfred Dev memory.

    Manages the lifecycle of the SQLite database connection and dispatches
    the JSON-RPC messages from stdin to the matching handlers. Responses go
    to stdout as modern MCP JSONL or, if the client uses it, with legacy
    Content-Length framing.

    The server supports four MCP protocol methods:
        - ``initialize``: capability negotiation.
        - ``notifications/initialized``: client confirmation.
        - ``tools/list``: list of available tools.
        - ``tools/call``: call of one tool.

    Args:
        db_path: path to the SQLite memory file. If it does not exist, it is
                 created with the full schema.
        retention_days: retention days for the purge of old events.
                        If 0 or negative, no purge runs.
    """

    # Explicit dict of handlers per tool.
    # A dict instead of dynamic getattr has two benefits:
    # 1. Smaller attack surface: only the listed handlers are exposed.
    # 2. Maintainability: a missing handler is easy to see here.
    _TOOL_HANDLERS: Dict[str, Any] = {}  # Set at the end of the class

    def __init__(self, db_path: str, retention_days: int = 365) -> None:
        self._db: Optional[MemoryDB] = None
        self._db_path = db_path
        self._retention_days = retention_days
        self._initialized = False
        self._project_dir = os.getcwd()

    def _memory_config(self) -> Dict[str, Any]:
        """Load the effective memory configuration of the current project."""
        return load_memory_config(self._project_dir)

    def _ensure_db(self) -> MemoryDB:
        """
        Open the DB connection lazily.

        The open is deferred until it is needed, so the DB is not created
        if the client never calls a tool (for example, if it only does
        initialize + shutdown).

        Returns:
            MemoryDB instance ready to use.

        Raises:
            RuntimeError: if the DB path is not accessible.
        """
        if self._db is not None:
            return self._db

        _log.info("Opening database: %s", self._db_path)
        try:
            self._db = MemoryDB(self._db_path)
        except Exception as exc:
            _log.error("Failed to open database: %s", exc)
            raise RuntimeError(
                f"Не удалось открыть базу данных: {exc}"
            ) from exc

        # Purge old events if needed
        if self._retention_days > 0:
            try:
                purged = self._db.purge_old_events(self._retention_days)
                if purged > 0:
                    _log.info(
                        "Purged %d events older than %d days",
                        purged,
                        self._retention_days,
                    )
            except Exception as exc:
                _log.warning("Failed to purge events: %s", exc)

        return self._db

    def _resolve_project_path(self, path: Optional[str], default: str) -> str:
        """
        Resolve MCP paths inside the current project and block escapes.

        The memory tools work with project artifacts. We accept normal
        relative paths and absolute paths inside the project, but reject
        ``..``/symlinks that leave ``self._project_dir``.
        """
        raw = path if isinstance(path, str) and path.strip() else default
        candidate = raw if os.path.isabs(raw) else os.path.join(self._project_dir, raw)
        candidate_abs = os.path.abspath(candidate)
        candidate_real = os.path.realpath(candidate_abs)
        project_root = os.path.realpath(self._project_dir)

        probe = candidate_abs if os.path.exists(candidate_abs) else os.path.dirname(candidate_abs)
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent

        targets = [candidate_real]
        if probe and os.path.exists(probe):
            targets.append(os.path.realpath(probe))

        for target in targets:
            try:
                if os.path.commonpath([project_root, target]) != project_root:
                    raise ValueError
            except ValueError as exc:
                raise ValueError(
                    "Путь должен быть внутри текущего проекта."
                ) from exc

        return candidate_real

    # --- MCP protocol handlers --------------------------------------------

    def _handle_initialize(
        self, request_id: Any, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Answer the ``initialize`` method with the server information.

        Returns the name, the version and the supported capabilities. This
        server exposes only tools (``tools``).
        """
        self._initialized = True
        _log.info("Client requested initialization")
        protocol_version = str(params.get("protocolVersion") or "2025-06-18")
        return _make_response(request_id, {
            "protocolVersion": protocol_version,
            "serverInfo": {
                "name": "alfred-memory",
                "version": _load_plugin_version(),
            },
            "capabilities": {
                "tools": {},
            },
        })

    def _handle_tools_list(
        self, request_id: Any, _params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Answer the ``tools/list`` method with the tool catalog.

        Each tool includes its name, description and the JSON Schema
        of its input parameters.
        """
        _log.debug("Tool list requested")
        return _make_response(request_id, {"tools": _TOOLS})

    def _handle_tools_call(
        self, request_id: Any, params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Dispatch a tool call to the matching method.

        Checks that the tool exists, opens the DB if needed and delegates
        to the ``_call_<tool_name>`` method. The result is serialized as
        JSON and returned in a ``content`` block of type ``text``.

        Args:
            request_id: ID of the JSON-RPC request.
            params: must contain ``name`` (str) and optionally ``arguments`` (dict).

        Returns:
            JSON-RPC response with the result or an error.
        """
        tool_name: str = params.get("name", "")
        arguments: Dict[str, Any] = params.get("arguments", {})

        _log.info("Tool call: %s", tool_name)
        _log.debug("Arguments: %s", arguments)

        if tool_name not in _TOOL_NAMES:
            return _make_error(
                request_id,
                -32602,
                f"Неизвестный инструмент: {tool_name}",
            )

        # Open the DB if it is not open yet
        try:
            db = self._ensure_db()
        except RuntimeError as exc:
            return _make_error(
                request_id,
                -32603,
                str(exc),
            )

        # Dispatch to the handler through the explicit dict.
        # No dynamic getattr: this reduces the attack surface and helps
        # maintenance, because a missing handler is visible here.
        handler = self._TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return _make_error(
                request_id,
                -32603,
                f"Handler не реализован для: {tool_name}",
            )

        try:
            # _TOOL_HANDLERS stores unbound class functions so the map is
            # stable and verifiable. When dispatching from an instance,
            # pass self explicitly.
            result = handler(self, db, arguments)
            text_content = json.dumps(result, ensure_ascii=False, indent=2)
            # If the handler returns {"error": ...}, set isError so the
            # MCP consumer can tell validation errors from successful
            # results (MCP tools/call protocol).
            is_error = isinstance(result, dict) and "error" in result
            return _make_response(request_id, {
                "content": [
                    {"type": "text", "text": text_content},
                ],
                "isError": is_error,
            })
        except Exception as exc:
            _log.error(
                "Error while running %s: %s\n%s",
                tool_name,
                exc,
                traceback.format_exc(),
            )
            return _make_error(
                request_id,
                -32603,
                f"Ошибка в {tool_name}: {exc}",
            )

    # --- Tool implementations ---------------------------------------------

    def _call_memory_search(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Run a text search over decisions and commits.

        The search uses FTS5 if the SQLite build has it. Otherwise it
        uses LIKE as a transparent fallback.

        Args:
            db: open MemoryDB instance.
            args: ``query`` (str, required), ``limit`` (int), ``iteration_id`` (int).

        Returns:
            Dict with the result list and search metadata.
        """
        query: str = args.get("query", "")
        limit, limit_capped, requested_limit = _bounded_limit(
            args.get("limit"),
            _SEARCH_LIMIT_DEFAULT,
            _SEARCH_LIMIT_MAX,
        )
        iteration_id: Optional[int] = args.get("iteration_id")
        since: Optional[str] = args.get("since")
        until: Optional[str] = args.get("until")
        tags: Optional[List[str]] = args.get("tags")
        status: Optional[str] = args.get("status")

        if not query.strip():
            return {"results": [], "message": "Запрос пустой."}

        results = db.search(
            query,
            limit=limit,
            iteration_id=iteration_id,
            since=since,
            until=until,
            tags=tags,
            status=status,
        )
        payload = {
            "results": results,
            "total": len(results),
            "query": query,
            "fts_enabled": db.fts_enabled,
        }
        if limit_capped:
            payload.update({
                "limit_capped": True,
                "requested_limit": requested_limit,
                "applied_limit": limit,
            })
        return payload

    def _call_memory_log_decision(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Record a design decision in memory.

        The ``title`` and ``chosen`` fields are required. The others are
        optional and add traceability to the decision.

        Args:
            db: open MemoryDB instance.
            args: decision parameters as in the inputSchema.

        Returns:
            Dict with the ID of the new decision and a confirmation.
        """
        title: str = args.get("title", "")
        chosen: str = args.get("chosen", "")

        if not title or not chosen:
            return {"error": "Поля 'title' и 'chosen' обязательны."}

        decision_id = db.log_decision(
            title=title,
            chosen=chosen,
            context=args.get("context"),
            alternatives=args.get("alternatives"),
            rationale=args.get("rationale"),
            impact=args.get("impact"),
            phase=args.get("phase"),
            tags=args.get("tags"),
        ) if self._memory_config().get("capture_decisions", True) else None

        if decision_id is None:
            return {
                "decision_id": None,
                "message": (
                    "Автоматический захват решений отключён "
                    "в конфигурации проекта."
                ),
                "skipped": True,
            }

        return {
            "decision_id": decision_id,
            "message": f"Решение записано с ID {decision_id}.",
        }

    def _call_memory_log_commit(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Record a commit and optionally link it to decisions.

        If the SHA already exists in the database, the operation is skipped
        (idempotent). Links to decisions are created with the
        ``implements`` type.

        Args:
            db: open MemoryDB instance.
            args: ``sha`` (str, required), ``message`` (str),
                  ``author`` (str), ``committed_at`` (str ISO),
                  ``decision_ids`` (list[int]), ``iteration_id`` (int).

        Returns:
            Dict with the result of the record.
        """
        sha: str = args.get("sha", "")

        if not sha:
            return {"error": "Поле 'sha' обязательно."}

        if not self._memory_config().get("capture_commits", True):
            return {
                "commit_id": None,
                "message": (
                    "Автоматический захват commits отключён "
                    "в конфигурации проекта."
                ),
                "skipped": True,
            }

        commit_id = db.log_commit(
            sha=sha,
            message=args.get("message"),
            author=args.get("author"),
            iteration_id=args.get("iteration_id"),
            files=args.get("files"),
            committed_at=args.get("committed_at"),
        )

        # Link to decisions if any were given
        decision_ids: List[int] = args.get("decision_ids", [])
        linked: List[int] = []

        if commit_id is not None and decision_ids:
            for did in decision_ids:
                try:
                    db.link_commit_decision(commit_id, did)
                    linked.append(did)
                except Exception as exc:
                    _log.warning(
                        "Failed to link commit %d to decision %d: %s",
                        commit_id,
                        did,
                        exc,
                    )

        if commit_id is None:
            return {
                "commit_id": None,
                "message": f"Commit {sha[:8]} уже есть. Пропущен.",
                "duplicate": True,
            }

        return {
            "commit_id": commit_id,
            "message": f"Commit {sha[:8]} записан с ID {commit_id}.",
            "linked_decisions": linked,
        }

    def _call_memory_get_iteration(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get the full data of an iteration.

        If no ID is given, try to return the active iteration.
        If none is active, return the latest one (highest ID).

        Args:
            db: open MemoryDB instance.
            args: ``id`` (int, optional).

        Returns:
            Dict with the iteration data, or a message if it does not exist.
        """
        iteration_id: Optional[int] = args.get("id")

        if iteration_id is not None:
            iteration = db.get_iteration(iteration_id)
        else:
            # Try the active one first, then the latest
            iteration = db.get_active_iteration()
            if iteration is None:
                # Find the latest one by descending ID
                stats = db.get_stats()
                total = stats.get("total_iterations", 0)
                if total > 0:
                    # Get the one with the highest ID by direct lookup
                    iteration = self._get_latest_iteration(db)

        if iteration is None:
            return {"iteration": None, "message": "Записанных итераций нет."}

        # The tool promises the full iteration: avoid silent caps.
        decisions = list(db.iter_decisions(iteration_id=iteration["id"]))

        return {
            "iteration": iteration,
            "decisions": decisions,
            "total_decisions": len(decisions),
        }

    @staticmethod
    def _get_latest_iteration(db: MemoryDB) -> Optional[Dict[str, Any]]:
        """
        Get the latest iteration from the database.

        Used as a fallback when no iteration is active and the user gives
        no ID. Delegates to the public MemoryDB method to keep
        encapsulation.

        Args:
            db: open MemoryDB instance.

        Returns:
            Dict with the latest iteration, or None if there is none.
        """
        return db.get_latest_iteration()

    def _call_memory_get_timeline(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Get the event timeline of an iteration.

        Events come in chronological order (oldest first), so the full
        workflow sequence can be rebuilt.

        Args:
            db: open MemoryDB instance.
            args: ``iteration_id`` (int, required).

        Returns:
            Dict with the event list and metadata.
        """
        iteration_id: Optional[int] = args.get("iteration_id")

        if iteration_id is None:
            return {"error": "Поле 'iteration_id' обязательно."}

        # The public tool promises the full timeline. get_timeline() in
        # MemoryDB has a defensive default limit for general use, so here
        # we raise the cap to the real number of events.
        total_events = db.count_events(iteration_id=iteration_id)
        events = db.get_timeline(iteration_id, limit=max(total_events, 1))
        return {
            "iteration_id": iteration_id,
            "events": events,
            "total": len(events),
        }

    def _call_memory_stats(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Return general statistics of the project memory.

        Includes counters for each record type, the active search mode
        (FTS5 or LIKE), the schema version and the creation date.

        Args:
            db: open MemoryDB instance.
            args: no parameters (ignored).

        Returns:
            Dict with all statistics.
        """
        stats = db.get_stats()
        stats["fts_enabled"] = db.fts_enabled
        stats["db_path"] = self._db_path
        return stats

    def _call_memory_manage_iteration(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Manage the iteration lifecycle.

        Supports two actions: ``start`` starts a new iteration and
        ``complete`` closes an existing one. Starting an iteration while
        another one is active returns an error.

        Args:
            db: open MemoryDB instance.
            args: ``action`` (str, required), ``command`` (str),
                  ``description`` (str), ``iteration_id`` (int).

        Returns:
            Dict with the result of the operation.
        """
        action: str = args.get("action", "")

        if action == "start":
            command: str = args.get("command", "")
            if not command:
                return {"error": "Поле 'command' обязательно для action='start'."}

            # Check that no iteration is active
            active = db.get_active_iteration()
            if active is not None:
                return {
                    "error": (
                        f"Активная итерация уже есть (ID {active['id']}, "
                        f"команда '{active.get('command', '?')}'). "
                        f"Заверши её, прежде чем запускать новую."
                    ),
                    "active_iteration": active,
                }

            iteration_id = db.start_iteration(
                command=command,
                description=args.get("description"),
            )
            return {
                "iteration_id": iteration_id,
                "message": f"Итерация {iteration_id} запущена для '{command}'.",
            }

        elif action == "complete":
            iteration_id_param: Optional[int] = args.get("iteration_id")

            if iteration_id_param is None:
                active = db.get_active_iteration()
                if active is None:
                    return {"error": "Нет активной итерации для завершения."}
                iteration_id_param = active["id"]

            db.complete_iteration(iteration_id_param)
            return {
                "iteration_id": iteration_id_param,
                "message": f"Итерация {iteration_id_param} завершена.",
            }

        else:
            return {"error": f"Неизвестное действие: '{action}'. Используй 'start' или 'complete'."}

    def _call_memory_log_event(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Record an arbitrary event in the timeline of an iteration.

        Events are linked to an iteration. If ``iteration_id`` is not
        given, the active iteration is used. If none is active, an error
        is returned.

        Args:
            db: open MemoryDB instance.
            args: ``event_type`` (str, required), ``phase`` (str),
                  ``payload`` (dict), ``summary`` (str), ``content`` (str),
                  ``iteration_id`` (int).

        Returns:
            Dict with the ID of the recorded event.
        """
        event_type_value = args.get("event_type")
        if not isinstance(event_type_value, str) or not event_type_value.strip():
            return {"error": "Поле 'event_type' обязательно."}
        event_type = event_type_value.strip()
        if len(event_type) > _EVENT_TYPE_MAX:
            return {
                "error": (
                    f"Поле 'event_type' не может быть длиннее "
                    f"{_EVENT_TYPE_MAX} символов."
                ),
            }

        phase_value = args.get("phase")
        if phase_value is not None and not isinstance(phase_value, str):
            return {"error": "Поле 'phase', если указано, должно быть текстом."}
        phase = phase_value.strip() if isinstance(phase_value, str) else None
        if phase and len(phase) > _EVENT_PHASE_MAX:
            return {
                "error": (
                    f"Поле 'phase' не может быть длиннее "
                    f"{_EVENT_PHASE_MAX} символов."
                ),
            }

        iteration_id: Optional[int] = args.get("iteration_id")
        if iteration_id is None:
            active = db.get_active_iteration()
            if active is None:
                return {
                    "error": (
                        "Нет активной итерации. Укажи 'iteration_id' "
                        "или запусти итерацию через memory_manage_iteration."
                    ),
                }
            iteration_id = active["id"]

        try:
            payload, payload_truncated, payload_chars = _bounded_event_payload(
                args.get("payload")
            )
        except ValueError as exc:
            return {"error": str(exc)}

        summary, summary_truncated, summary_chars = _bounded_text(
            args.get("summary"),
            _EVENT_SUMMARY_MAX,
        )
        content, content_truncated, content_chars = _bounded_text(
            args.get("content"),
            _EVENT_CONTENT_MAX,
        )

        if content is None and payload is not None:
            # The public tool promises useful traceability. If no indexable
            # content is given, use the serialized payload as a fallback.
            content, content_truncated, content_chars = _bounded_text(
                json.dumps(payload, ensure_ascii=False, default=str),
                _EVENT_CONTENT_MAX,
            )

        truncation: Dict[str, Any] = {}
        if payload_truncated:
            truncation["payload"] = {
                "original_chars": payload_chars,
                "max_chars": _EVENT_PAYLOAD_MAX,
            }
        if summary_truncated:
            truncation["summary"] = {
                "original_chars": summary_chars,
                "max_chars": _EVENT_SUMMARY_MAX,
            }
        if content_truncated:
            truncation["content"] = {
                "original_chars": content_chars,
                "max_chars": _EVENT_CONTENT_MAX,
            }
        if truncation:
            payload = dict(payload or {})
            payload["_alfred_mcp_truncation"] = truncation

        event_id = db.log_event(
            event_type=event_type,
            phase=phase,
            payload=payload,
            summary=summary,
            content=content,
            iteration_id=iteration_id,
        )

        return {
            "event_id": event_id,
            "iteration_id": iteration_id,
            "payload_truncated": payload_truncated,
            "summary_truncated": summary_truncated,
            "content_truncated": content_truncated,
            "message": f"Событие '{event_type}' записано с ID {event_id}.",
        }

    def _call_memory_get_decisions(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        List the design decisions recorded in memory.

        Decisions come newest first. They can be filtered by iteration.

        Args:
            db: open MemoryDB instance.
            args: ``iteration_id`` (int, optional), ``limit`` (int).

        Returns:
            Dict with the decision list and metadata.
        """
        iteration_id: Optional[int] = args.get("iteration_id")
        limit, limit_capped, requested_limit = _bounded_limit(
            args.get("limit"),
            _DECISIONS_LIMIT_DEFAULT,
            _DECISIONS_LIMIT_MAX,
        )
        tags: Optional[List[str]] = args.get("tags")
        status: Optional[str] = args.get("status")

        decisions = db.get_decisions(
            iteration_id=iteration_id,
            limit=limit,
            tags=tags,
            status=status,
        )

        payload = {
            "decisions": decisions,
            "total": len(decisions),
            "iteration_id": iteration_id,
        }
        if limit_capped:
            payload.update({
                "limit_capped": True,
                "requested_limit": requested_limit,
                "applied_limit": limit,
            })
        return payload

    def _call_memory_purge(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Delete old events from memory.

        Only events are purged: decisions and iterations are always kept.
        The number of retention days sets the cutoff.

        Args:
            db: open MemoryDB instance.
            args: ``retention_days`` (int, required).

        Returns:
            Dict with the number of deleted events.
        """
        retention_days: Optional[int] = args.get("retention_days")

        if retention_days is None or retention_days < 1:
            return {
                "error": (
                    "Поле 'retention_days' обязательно и должно быть "
                    "положительным целым числом."
                ),
            }

        purged = db.purge_old_events(retention_days)
        return {
            "purged_events": purged,
            "retention_days": retention_days,
            "message": (
                f"Удалено событий старше {retention_days} дней: "
                f"{purged}."
            ),
        }

    def _call_memory_update_decision(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Update the status or the tags of an existing decision.

        Can mark decisions as ``superseded`` or ``deprecated`` and add
        classification tags. Both changes are optional and independent.

        Args:
            db: open MemoryDB instance.
            args: ``id`` (int, required), ``status`` (str), ``tags`` (list[str]).

        Returns:
            Dict with a confirmation, or an error if the ID is missing.
        """
        decision_id: Optional[int] = args.get("id")

        if decision_id is None:
            return {"error": "Поле 'id' обязательно."}

        new_status: Optional[str] = args.get("status")
        new_tags: Optional[List[str]] = args.get("tags")

        if new_status:
            try:
                db.update_decision_status(decision_id, new_status)
            except ValueError as exc:
                return {"error": str(exc)}

        if new_tags:
            db.add_decision_tags(decision_id, new_tags)

        return {
            "message": "Решение обновлено.",
            "id": decision_id,
        }

    def _call_memory_link_decisions(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Create a directed relation between two decisions.

        Records that a decision supersedes, depends on, contradicts or
        relates to another one. The operation is idempotent: an existing
        relation is not duplicated.

        Args:
            db: open MemoryDB instance.
            args: ``source_id`` (int), ``target_id`` (int), ``link_type`` (str).
                  All three fields are required.

        Returns:
            Dict with a confirmation, or an error if fields are missing.
        """
        source_id: Optional[int] = args.get("source_id")
        target_id: Optional[int] = args.get("target_id")
        link_type: Optional[str] = args.get("link_type")

        if source_id is None or target_id is None or link_type is None:
            return {
                "error": (
                    "Поля 'source_id', 'target_id' и 'link_type' "
                    "обязательны."
                ),
            }

        db.link_decisions(source_id, target_id, link_type)

        return {
            "message": (
                f"Связь '{link_type}' создана между решениями "
                f"{source_id} и {target_id}."
            ),
            "source_id": source_id,
            "target_id": target_id,
            "link_type": link_type,
        }

    def _call_memory_health(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Check the integrity of the memory database.

        Delegates to ``MemoryDB.check_health()`` and returns its result
        as is: schema version, FTS5 status, permissions and file size.

        Args:
            db: open MemoryDB instance.
            args: no parameters (ignored).

        Returns:
            Dict with the database health report.
        """
        return db.check_health()

    def _call_memory_export(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Export the decisions to an ADR-like Markdown file.

        Only the ``markdown`` format is supported for now. For each
        decision the output file has the date, status, tags, context,
        chosen option, alternatives and rationale.

        Args:
            db: open MemoryDB instance.
            args: ``format`` (str, required), ``path`` (str),
                  ``iteration_id`` (int).

        Returns:
            Dict with the number of exported decisions, the path
            and the format.
        """
        fmt: str = args.get("format", "")
        path: Optional[str] = args.get("path")
        iteration_id: Optional[int] = args.get("iteration_id")

        if fmt != "markdown":
            return {
                "error": (
                    f"Формат не поддерживается: '{fmt}'. "
                    "Поддерживается только 'markdown'."
                ),
            }

        try:
            export_path = self._resolve_project_path(path, "DECISIONS.md")
        except ValueError as exc:
            return {"error": str(exc)}

        count = db.export_decisions_markdown(export_path, iteration_id)

        return {
            "exported": count,
            "path": export_path,
            "format": fmt,
        }

    def _call_memory_import(
        self, db: MemoryDB, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Import data into memory from external sources.

        Supports two sources: ``git`` imports the commit history of a
        repository, and ``adr`` imports ADR files as decisions. The
        operation is idempotent for commits (duplicate SHAs are skipped).

        Args:
            db: open MemoryDB instance.
            args: ``source`` (str, required), ``path`` (str),
                  ``limit`` (int, git only).

        Returns:
            Dict with the number of imported records and the source.
        """
        source: str = args.get("source", "")
        path: Optional[str] = args.get("path")
        limit, limit_capped, requested_limit = _bounded_limit(
            args.get("limit"),
            _GIT_IMPORT_LIMIT_DEFAULT,
            _GIT_IMPORT_LIMIT_MAX,
        )

        if source == "git":
            try:
                repo_path = self._resolve_project_path(path, ".")
            except ValueError as exc:
                return {"error": str(exc)}
            count = db.import_git_history(repo_path, limit)
        elif source == "adr":
            try:
                adr_path = self._resolve_project_path(path, "docs/adr")
            except ValueError as exc:
                return {"error": str(exc)}
            count = db.import_adrs(adr_path)
        else:
            return {
                "error": (
                    f"Источник не поддерживается: '{source}'. "
                    "Используй 'git' или 'adr'."
                ),
            }

        payload = {
            "imported": count,
            "source": source,
        }
        if source == "git" and limit_capped:
            payload.update({
                "limit_capped": True,
                "requested_limit": requested_limit,
                "applied_limit": limit,
            })
        return payload

    # --- Handler dict (initialization) ------------------------------------
    # Defined here, after all _call_* methods, so the references to
    # self.<method> resolve correctly at runtime. This replaces the empty
    # placeholder at the top of the class.

    @classmethod
    def _init_handlers(cls) -> Dict[str, Any]:
        """Build the MCP handler dict."""
        return {
            "memory_search": cls._call_memory_search,
            "memory_log_decision": cls._call_memory_log_decision,
            "memory_log_commit": cls._call_memory_log_commit,
            "memory_get_iteration": cls._call_memory_get_iteration,
            "memory_get_timeline": cls._call_memory_get_timeline,
            "memory_stats": cls._call_memory_stats,
            "memory_manage_iteration": cls._call_memory_manage_iteration,
            "memory_log_event": cls._call_memory_log_event,
            "memory_get_decisions": cls._call_memory_get_decisions,
            "memory_purge": cls._call_memory_purge,
            "memory_update_decision": cls._call_memory_update_decision,
            "memory_link_decisions": cls._call_memory_link_decisions,
            "memory_health": cls._call_memory_health,
            "memory_export": cls._call_memory_export,
            "memory_import": cls._call_memory_import,
        }

    # --- Main loop --------------------------------------------------------

    def _run_fastmcp(self) -> bool:
        """Start the server with the official SDK if it is installed."""
        try:
            from mcp.server.fastmcp import FastMCP
        except ImportError:
            _log.warning(
                "Package 'mcp' is not available. "
                "Install the official SDK (pip install mcp). Using the built-in transport."
            )
            return False

        mcp = FastMCP("alfred-memory")
        server = self

        for tool_name, handler in self._TOOL_HANDLERS.items():
            meta = next((item for item in _TOOLS if item["name"] == tool_name), None)
            description = meta["description"] if meta else tool_name

            def _bind(name: str, fn, doc: str):
                def tool_fn(**kwargs):
                    db = server._ensure_db()
                    return fn(server, db, kwargs)

                tool_fn.__name__ = name
                tool_fn.__doc__ = doc
                return tool_fn

            mcp.tool(name=tool_name)(_bind(tool_name, handler, description))

        _log.info("alfred-memory MCP server started with FastMCP")
        _log.info("DB path: %s", self._db_path)
        try:
            mcp.run()
        finally:
            if self._db is not None:
                self._db.close()
        return True

    def run(self) -> None:
        """Main loop: official FastMCP SDK, with a built-in stdio fallback."""
        if self._run_fastmcp():
            return
        self._run_legacy_stdio()

    def _run_legacy_stdio(self) -> None:
        """Built-in stdio transport (fallback if the mcp package is missing)."""
        _log.info("alfred-memory MCP server started")
        _log.info("DB path: %s", self._db_path)

        try:
            while True:
                try:
                    message = _read_message()
                except ValueError as exc:
                    _log.error("Failed to read message: %s", exc)
                    # Try to send a parse error if possible
                    _write_message(_make_error(None, -32700, str(exc)))
                    continue
                except Exception as exc:
                    _log.error(
                        "Unexpected error while reading stdin: %s\n%s",
                        exc,
                        traceback.format_exc(),
                    )
                    break

                # stdin closed: the parent process exited
                if message is None:
                    _log.info("Stdin closed. Server is shutting down.")
                    break

                _log.debug("Received message: %s", json.dumps(message)[:200])

                # Extract the JSON-RPC message fields
                method: str = message.get("method", "")
                request_id = message.get("id")
                params: Dict[str, Any] = message.get("params", {})

                # Notifications have no id and need no response
                is_notification = request_id is None

                # Dispatch by method
                response: Optional[Dict[str, Any]] = None

                if method == "initialize":
                    response = self._handle_initialize(request_id, params)

                elif method == "notifications/initialized":
                    # Client confirmation notification. The protocol needs
                    # no response.
                    _log.info("Client confirmed initialization")

                elif method == "tools/list":
                    response = self._handle_tools_list(request_id, params)

                elif method == "tools/call":
                    response = self._handle_tools_call(request_id, params)

                elif method == "ping":
                    # Heartbeat method: reply with an empty object
                    response = _make_response(request_id, {})

                else:
                    # Unknown method: return an error for a request with an
                    # id. Ignore a notification silently.
                    if not is_notification:
                        response = _make_error(
                            request_id,
                            -32601,
                            f"Метод не поддерживается: {method}",
                        )
                    else:
                        _log.debug(
                            "Notification skipped: %s", method
                        )

                # Send a response only for a request (it has an id)
                if response is not None and not is_notification:
                    _write_message(response)
                    _log.debug(
                        "Response sent for id=%s", request_id
                    )

        except KeyboardInterrupt:
            _log.info("Interrupt received. Server is shutting down.")
        finally:
            if self._db is not None:
                _log.info("Closing database connection")
                self._db.close()

        _log.info("alfred-memory MCP server stopped")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


# Initialize the handler dict after all _call_* methods are defined.
# This replaces the empty placeholder.
MemoryMCPServer._TOOL_HANDLERS = MemoryMCPServer._init_handlers()


def resolve_retention_days(project_dir: str) -> int:
    """Resolve the effective retention from env or the project config."""
    retention_str = os.environ.get("ALFRED_MEMORY_RETENTION_DAYS")
    if retention_str is None:
        retention_value = load_memory_config(project_dir).get(
            "retention_days", 365
        )
        retention_str = str(retention_value)
    try:
        return int(retention_str)
    except ValueError:
        return 365


def main() -> None:
    """
    MCP server entry point.

    Resolves the database path relative to the current working directory
    (where Claude Code runs the process) and starts the main server loop.
    """
    # The DB lives in the .claude/ directory of the project where Claude
    # Code runs, not in the plugin directory.
    db_path = os.path.join(os.getcwd(), ".claude", "alfred-memory.db")

    # Retention days, configurable with an env variable (fallback 365)
    retention_days = resolve_retention_days(os.getcwd())

    server = MemoryMCPServer(db_path=db_path, retention_days=retention_days)
    server.run()


if __name__ == "__main__":
    main()
