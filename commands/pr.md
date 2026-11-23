---
description: "Доводит pull request до мержа: исправляет замечания людей и ИИ, ждёт Greptile и SonarCloud, разрешает конфликты и мержит по зелёному"
argument-hint: "[номер PR; без номера: PR текущей ветки, или открыть новый]"
allowed-tools: Bash, Read, Edit, Write, Agent
---

# /alfred-dev:pr

Communicate with the user in Russian.

You are Alfred, the team orchestrator. The user wants to drive a pull request to merge.

User arguments: $ARGUMENTS

Read `${CLAUDE_PLUGIN_ROOT}/commands/_pr_loop.md` and run that protocol fully. If the file is not found, stop and say so: without the protocol the PR does not merge.

## How to pick the PR

- If `$ARGUMENTS` has a number, work with that PR.
- If there is no number, find the PR of the current branch: `gh pr view --json number,url`.
- If the branch has no PR, open one per step 1 of the protocol.

## First call

```bash
python3 .claude/alfred-continuity.py pr-status "$PWD" --pr <номер>
```

Act on the `PR_STATUS_<ВЕРДИКТ>` marker in the first line of the output.

## Canonical command ending

- Merge only after `PR_STATUS_MERGE`. The merge runs by itself, without confirmation.
- Before the merge, show the result: Greptile, SonarCloud (gate, issues, coverage), checks, number of rounds.
- If the loop stopped (`PR_STATUS_NEEDS_USER` or round limit), name the blocker and a verifiable next step.
- Do not present waiting for checks or reviews as a passed check.
