---
description: "Открывает или закрывает локальный UI памяти: timeline, решения, граф и поиск"
argument-hint: "[stop]"
---

# /alfred-dev:memory-ui

Communicate with the user in Russian.

You are Alfred. This command exists to **open or close the project memory in a local graphical UI**, not to improvise manual analysis in the chat.

User's free argument: $ARGUMENTS

## Semantics

- No argument: opens or reuses the UI at `http://127.0.0.1`.
- `stop`: shuts down the local server if it is alive.

When the Claude session ends, `SessionEnd` stops the UI if it is still running.

## Protocol

Step 0: if `UserPromptSubmit` already prepared a helper-first UI in this session, use it BEFORE anything else. Run this Bash immediately. If it returns text, use it as is as the final answer:

```bash
python3 .claude/alfred-continuity.py consume-prefetch "$PWD" --expected memory-ui
```

If it returns nothing or fails, continue.

Then run the deterministic helper immediately:

```bash
python3 .claude/alfred-continuity.py memory-ui "$PWD" --raw "$ARGUMENTS"
```

The helper also accepts `--stop` as an alias for `stop`.

If the helper returns a valid answer, use it as is as the final answer. Do not wrap it in extra prose. The helper already shows the URL, the UI state or the shutdown confirmation.

Only if the helper fails, switch to manual mode.

## What the answer must show

If the UI opens:

- the opened or reused local URL;
- that the source of truth is `.claude/alfred-memory.db`;
- that the view shows overview, timeline, decisions, graph, commits and search;
- how to close: `/alfred-dev:memory-ui stop`.

If it closes: confirmation that the process stopped or that it was not running.

## Rules

- DO NOT turn this command into a long text report.
- DO NOT read SQLite by hand if the helper worked.
- DO NOT launch a multi-agent flow.
- DO NOT add a second explanation on top of the Markdown the helper already returns.
- If memory is still empty, say so directly, but open the UI anyway.
- DO NOT use `AskUserQuestion` as a mandatory step.
