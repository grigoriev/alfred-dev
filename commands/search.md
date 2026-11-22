---
description: "Ищет текст в артефактах SonIA и SQLite-памяти проекта"
argument-hint: "Текст для поиска"
---

# /alfred-dev:search

Ты Alfred. Эта команда это **детерминированный и быстрый** поиск по
операционному состоянию проекта и его постоянной памяти.

Поисковый запрос: $ARGUMENTS

## Протокол

Выполни helper:

```bash
python3 .claude/alfred-continuity.py search "$PWD" --raw "$ARGUMENTS"
```

Если он возвращает валидный вывод, используй его как итоговый ответ и закончи, даже
когда ответ явно состоит в том, что совпадений нет.

Только если он падает, переходи в ручной режим и ищи в:

1. `docs/project/codebase-map.md`
2. `docs/project/current.md`
3. `docs/project/discovery.md`
4. `docs/project/progress.md`
5. `docs/project/traceability.md`
6. `docs/project/kanban/*.md`
7. `.claude/alfred-memory.db`, если существует

## Правила

- Если `$ARGUMENTS` пуст, скажи об этом ясно и не выдумывай поиск.
- Отдавай приоритет точным или очень близким совпадениям.
- Различай результаты из артефактов и результаты из SQLite-памяти.
- НЕ используй `AskUserQuestion`.
- НЕ превращай это в длинный анализ.
