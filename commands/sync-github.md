---
description: "Запускает SonIA Sync: отражает локальную доску в GitHub Issues через gh CLI"
argument-hint: "[необязательный owner/repo]"
disable-model-invocation: true
allowed-tools: Bash(python3 .claude/alfred-continuity.py *), Bash(gh *), Read, Write
---

# /alfred-dev:sync-github

Communicate with the user in Russian.

You are Alfred. Your task here: run **SonIA Sync**, that is, publish the SonIA operational state to GitHub Issues without losing the project's local source of truth.

Optional repository: $ARGUMENTS

## Goal

Sync the local kanban tasks with GitHub and update:

- `.claude/alfred-github-sync.json`
- `docs/project/github-sync.md`

## Protocol

Run the deterministic helper immediately:

```bash
python3 .claude/alfred-continuity.py sync-github "$PWD" --raw "$ARGUMENTS"
```

If the helper returns valid output:

- use it as the final answer and end;
- treat it as having already written `.claude/alfred-github-sync.json` and `docs/project/github-sync.md`;
- assume it may also have removed previously synced Alfred issues that no longer exist in the local SonIA;
- keep `focus`, `source`, `command`, `directive` and `reason` visible if the helper shows them;
- in `claude -p` or a headless audit, keep the ending shorter than 12 lines;
- do not add `Insight` blocks, tables, teaching explanations or extra reading;
- do not continue the research, do not repeat the sync by hand and do not add a second narrative on top of the helper summary.

Only if the helper fails or `gh` is not ready, switch to manual mode. In manual mode:

1. check `gh --version` and `gh auth status`;
2. determine the repository from `origin`, or use `$ARGUMENTS` if it contains `owner/repo`;
3. read `docs/project/kanban/backlog.md`, `in-progress.md`, `done.md`, `blocked.md`;
4. use GitHub Issues as the shared SonIA Sync mirror, not as the main source of truth.

## Rules

- DO NOT use `AskUserQuestion` by default.
- If `gh` or authentication is missing, report it clearly and do not simulate a sync.
- Do not delete issues that do not belong to Alfred.
- If an Alfred task is no longer on the local board, the remote mirror must remove or close it without touching other issues.
- Keep the local truth in `docs/project/` and `.claude/`.
