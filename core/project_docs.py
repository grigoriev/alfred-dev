#!/usr/bin/env python3
"""Living project docs: skeleton, index and per-gate check.

The helper does not write prose. It creates structural files, updates the
index and reports what is missing to close a phase. Agents write the content.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


SCAFFOLD_MARKER = "<!-- alfred-doc:scaffold -->"
FILLED_MARKER = "<!-- alfred-doc:filled -->"
INDEX_MARKER = "<!-- alfred-doc:index -->"

PROJECT_DOCS_DIR = os.path.join("docs", "project")
ADR_DIR = os.path.join("docs", "adr")

DOC_FILES = {
    "index": os.path.join(PROJECT_DOCS_DIR, "README.md"),
    "architecture": os.path.join(PROJECT_DOCS_DIR, "architecture.md"),
    "compliance": os.path.join(PROJECT_DOCS_DIR, "compliance.md"),
    "threat_model": os.path.join(PROJECT_DOCS_DIR, "threat-model.md"),
    "dependencies": os.path.join(PROJECT_DOCS_DIR, "dependencies.md"),
}

DOC_TITLES = {
    "index": "Индекс живой документации",
    "architecture": "Архитектура проекта",
    "compliance": "Реестр compliance",
    "threat_model": "Модель угроз",
    "dependencies": "Оценённые зависимости",
}

# (document, "exists" | "filled")
_Req = Tuple[str, str]

REQUIREMENTS: Dict[Tuple[str, str], Tuple[_Req, ...]] = {
    ("feature", "product"): (("index", "exists"),),
    ("feature", "visual_style"): (("index", "exists"),),
    ("feature", "architecture"): (
        ("index", "exists"),
        ("architecture", "filled"),
        ("threat_model", "filled"),
    ),
    ("feature", "development"): (("index", "exists"),),
    ("feature", "quality"): (
        ("index", "exists"),
        ("compliance", "filled"),
    ),
    ("feature", "documentation"): (
        ("index", "exists"),
        ("architecture", "filled"),
    ),
    ("feature", "delivery"): (("index", "exists"),),
    ("fix", "diagnosis"): (("index", "exists"),),
    ("fix", "correction"): (("index", "exists"),),
    ("fix", "validation"): (("index", "exists"),),
    ("quick", "scoped_execution"): (("index", "exists"),),
    ("quick", "quick_validation"): (("index", "exists"),),
    ("spike", "exploration"): (("index", "exists"),),
    ("spike", "conclusions"): (("index", "exists"),),
    ("audit", "*"): (
        ("index", "exists"),
        ("compliance", "filled"),
        ("threat_model", "exists"),
    ),
    ("ship", "final_audit"): (
        ("index", "exists"),
        ("compliance", "exists"),
    ),
    ("ship", "documentation"): (("index", "exists"),),
    ("ship", "packaging"): (("index", "exists"),),
    ("ship", "deployment"): (("index", "exists"),),
    ("map-codebase", "*"): (
        ("index", "exists"),
        ("architecture", "exists"),
    ),
    ("discuss", "*"): (("index", "exists"),),
}

_SCAFFOLDS: Dict[str, str] = {
    "architecture": f"""# Архитектура проекта

{SCAFFOLD_MARKER}

## Контекст

_(заполнить)_

## Диаграмма

```mermaid
flowchart LR
    pending[Ещё не нарисовано]
```

## Компоненты

| Компонент | Ответственность | Границы |
|-----------|-----------------|---------|
| _(заполнить)_ |  |  |

## Потоки данных

_(заполнить)_

## Открытые решения

_(заполнить)_
""",
    "compliance": f"""# Реестр compliance

{SCAFFOLD_MARKER}

Это не юридическое заключение. Это технический реестр с подтверждениями.

## Объём

| Рамка | Применимо | Причина |
|-------|-----------|---------|
| GDPR (RGPD) | уточнить |  |
| NIS2 | уточнить |  |
| CRA | уточнить |  |

## Контроли

| Контроль | Рамка | Статус | Подтверждение |
|----------|-------|--------|---------------|
| _(заполнить)_ |  | pending |  |

Статусы: `compliant` (с подтверждением), `partial`, `pending`, `not-applicable`, `accepted-risk`.

## Принятые риски

| Пробел | Кто | Когда | Причина |
|--------|-----|-------|---------|
| _(нет)_ |  |  |  |
""",
    "threat_model": f"""# Модель угроз

{SCAFFOLD_MARKER}

**Методология:** STRIDE

## Поверхность атаки

_(заполнить: реальные компоненты, а не общий список)_

## Границы доверия

_(заполнить)_

## STRIDE

| Угроза | Компонент | Вероятность | Влияние | Мера по снижению или принятый риск |
|--------|-----------|-------------|---------|------------------------------------|
| _(заполнить)_ |  |  |  |  |
""",
    "dependencies": f"""# Оценённые зависимости

{SCAFFOLD_MARKER}

| Пакет | Версия | Вердикт | Лицензия | Заметки |
|-------|--------|---------|----------|---------|
| _(пока нет оценённых)_ |  |  |  |  |
""",
}


def _now_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _abs(project_dir: str, relative: str) -> str:
    return os.path.join(os.path.abspath(project_dir), relative)


def _read(path: str) -> str:
    if not os.path.isfile(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def _write(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def doc_status(text: str) -> str:
    """Classify a document: empty, scaffold or filled."""
    if not text.strip():
        return "empty"
    if FILLED_MARKER in text:
        return "filled"
    if SCAFFOLD_MARKER in text:
        return "scaffold"
    return "filled"


def required_docs(command: str, phase: str = "") -> Tuple[_Req, ...]:
    """Return the doc requirements for a command and phase."""
    command = (command or "").strip().lower()
    phase = (phase or "").strip().lower() or "*"
    exact = REQUIREMENTS.get((command, phase))
    if exact is not None:
        return exact
    return REQUIREMENTS.get((command, "*"), ())


def ensure_project_docs(project_dir: str) -> Dict[str, Any]:
    """Create any missing skeleton and refresh the index. Does not write prose."""
    created: List[str] = []
    for key, relative in DOC_FILES.items():
        if key == "index":
            continue
        path = _abs(project_dir, relative)
        if not os.path.isfile(path):
            _write(path, _SCAFFOLDS[key])
            created.append(relative)
    os.makedirs(_abs(project_dir, ADR_DIR), exist_ok=True)
    index_relative = refresh_index(project_dir)
    return {
        "created": created,
        "index": index_relative,
        "docs": inspect_docs(project_dir),
    }


def inspect_docs(project_dir: str) -> List[Dict[str, str]]:
    """Status of each living document."""
    rows: List[Dict[str, str]] = []
    for key, relative in DOC_FILES.items():
        if key == "index":
            continue
        path = _abs(project_dir, relative)
        text = _read(path)
        status = doc_status(text) if text or os.path.isfile(path) else "missing"
        updated = ""
        if os.path.isfile(path):
            updated = datetime.fromtimestamp(
                os.path.getmtime(path), tz=timezone.utc
            ).date().isoformat()
        rows.append(
            {
                "key": key,
                "path": relative,
                "title": DOC_TITLES[key],
                "status": status,
                "updated": updated,
            }
        )
    return rows


def refresh_index(project_dir: str) -> str:
    """Rewrite the index table. Keep the notes below the cut heading."""
    relative = DOC_FILES["index"]
    path = _abs(project_dir, relative)
    existing = _read(path)
    notes = ""
    cut = "## Заметки команды"
    if cut in existing:
        notes = existing.split(cut, 1)[1].strip()

    rows = inspect_docs(project_dir)
    lines = [
        "# Живая документация проекта",
        "",
        INDEX_MARKER,
        "",
        "Обновляется только то, что изменила фаза. tech-writer синхронизирует этот индекс.",
        "",
        "| Документ | Статус | Обновлён |",
        "|----------|--------|----------|",
    ]
    for row in rows:
        lines.append(f"| `{row['path']}` | {row['status']} | {row['updated'] or '—'} |")

    adr_count = len(list_adr_files(project_dir))
    next_number = next_adr_number(project_dir)
    lines.extend(
        [
            "",
            f"ADR в `{ADR_DIR}/`: {adr_count}. Следующий номер: {next_number:03d}.",
            "",
            cut,
            "",
        ]
    )
    lines.append(notes if notes else "_(заметок нет)_")
    lines.append("")
    _write(path, "\n".join(lines))
    return relative


def list_adr_files(project_dir: str) -> List[str]:
    directory = _abs(project_dir, ADR_DIR)
    if not os.path.isdir(directory):
        return []
    names = [
        name
        for name in os.listdir(directory)
        if name.endswith(".md") and name.startswith("ADR-")
    ]
    return sorted(names)


def next_adr_number(project_dir: str) -> int:
    highest = 0
    for name in list_adr_files(project_dir):
        match = re.match(r"ADR-(\d+)", name)
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _slugify(title: str) -> str:
    normalized = title.strip().lower()
    normalized = re.sub(r"[^a-z0-9а-яё]+", "-", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"-+", "-", normalized).strip("-")
    return normalized or "decision"


def scaffold_adr(project_dir: str, title: str) -> Dict[str, Any]:
    """Create the skeleton of the next ADR. Does not write the decision."""
    number = next_adr_number(project_dir)
    slug = _slugify(title)
    relative = os.path.join(ADR_DIR, f"ADR-{number:03d}-{slug}.md")
    path = _abs(project_dir, relative)
    if os.path.isfile(path):
        return {"path": relative, "number": number, "created": False}
    content = (
        f"# ADR-{number:03d}: {title.strip() or 'Решение'}\n\n"
        f"{SCAFFOLD_MARKER}\n\n"
        f"**Дата:** {_now_date()}\n"
        "**Статус:** proposed\n"
        "**Автор:** architect\n\n"
        "## Контекст\n\n_(заполнить)_\n\n"
        "## Рассмотренные варианты\n\n### Вариант 1\n\n_(заполнить)_\n\n"
        "### Вариант 2\n\n_(заполнить)_\n\n"
        "## Решение\n\n_(заполнить)_\n\n"
        "## Последствия\n\n_(заполнить)_\n"
    )
    _write(path, content)
    refresh_index(project_dir)
    return {"path": relative, "number": number, "created": True}


def check_project_docs(
    project_dir: str,
    command: str,
    phase: str = "",
) -> Dict[str, Any]:
    """Check the documents that the gate requires. Writes nothing."""
    requirements = required_docs(command, phase)
    missing: List[str] = []
    empty: List[str] = []
    ok: List[str] = []
    inspected = {row["key"]: row for row in inspect_docs(project_dir)}
    index_path = _abs(project_dir, DOC_FILES["index"])
    inspected["index"] = {
        "key": "index",
        "path": DOC_FILES["index"],
        "status": "filled" if os.path.isfile(index_path) else "missing",
    }

    for key, rule in requirements:
        row = inspected.get(key) or {"path": DOC_FILES.get(key, key), "status": "missing"}
        status = row["status"]
        path = row["path"]
        if status == "missing":
            missing.append(path)
            continue
        if rule == "filled" and status != "filled":
            empty.append(path)
            continue
        ok.append(path)

    passed = not missing and not empty
    return {
        "passed": passed,
        "command": command,
        "phase": phase or "*",
        "required": [
            {"doc": key, "rule": rule, "path": DOC_FILES[key]}
            for key, rule in requirements
        ],
        "ok": ok,
        "missing": missing,
        "empty": empty,
    }


def render_sync_markdown(result: Dict[str, Any]) -> str:
    lines = ["## Документация проекта", ""]
    created = result.get("created") or []
    if created:
        lines.append("Созданы:")
        lines.extend(f"- `{path}`" for path in created)
        lines.append("")
    else:
        lines.append("Все скелеты уже были на месте.")
        lines.append("")
    lines.append("Статус:")
    for row in result.get("docs") or []:
        lines.append(f"- `{row['path']}`: {row['status']}")
    lines.append("")
    lines.append(f"Индекс: `{result.get('index', DOC_FILES['index'])}`")
    return "\n".join(lines)


def render_check_markdown(result: Dict[str, Any]) -> str:
    lines = [
        "## Проверка документации проекта",
        "",
        f"Команда: `{result['command']}` / фаза: `{result['phase']}`",
        "",
    ]
    if result["passed"]:
        lines.append("Результат: готово к gate.")
    else:
        lines.append("Результат: gate закрыть нельзя.")
    if result["missing"]:
        lines.append("")
        lines.append("Отсутствуют:")
        lines.extend(f"- `{path}`" for path in result["missing"])
    if result["empty"]:
        lines.append("")
        lines.append("Всё ещё скелеты (нужно реальное содержимое и `<!-- alfred-doc:filled -->`):")
        lines.extend(f"- `{path}`" for path in result["empty"])
    if result["ok"]:
        lines.append("")
        lines.append("Готовы:")
        lines.extend(f"- `{path}`" for path in result["ok"])
    return "\n".join(lines)


def render_adr_markdown(result: Dict[str, Any]) -> str:
    verb = "Создан" if result.get("created") else "Уже существовал"
    return (
        f"## ADR\n\n{verb}: `{result['path']}`\n\n"
        "Заполни контекст, варианты, решение и последствия. "
        f"По завершении замени `{SCAFFOLD_MARKER}` на `{FILLED_MARKER}`."
    )
