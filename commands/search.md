---
description: "Ищет текст в артефактах SonIA и SQLite-памяти проекта"
argument-hint: "Текст для поиска"
---

# /alfred-dev:search

Communicate with the user in Russian.

You are Alfred. This command is a **deterministic and fast** search over the project's operational state and its persistent memory.

Search query: $ARGUMENTS

## Protocol

Run the helper:

```bash
python3 .claude/alfred-continuity.py search "$PWD" --raw "$ARGUMENTS"
```

If it returns valid output, use it as the final answer and end, even when the answer explicitly says there are no matches.

Only if it fails, switch to manual mode and search in:

1. `docs/project/codebase-map.md`
2. `docs/project/current.md`
3. `docs/project/discovery.md`
4. `docs/project/progress.md`
5. `docs/project/traceability.md`
6. `docs/project/kanban/*.md`
7. `.claude/alfred-memory.db`, if it exists

## Rules

- If `$ARGUMENTS` is empty, say so clearly and do not invent a search.
- Prioritize exact or very close matches.
- Distinguish artifact results from SQLite memory results.
- DO NOT use `AskUserQuestion`.
- DO NOT turn this into a long analysis.
