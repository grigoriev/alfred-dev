---
description: "Внешнее ревью готовой фичи через Greptile CLI: диагноз и рекомендация по каждому пункту"
argument-hint: "[необязательный каталог] [--scope all|security|tests|architecture|performance] [--branch <база>] [--plus|--apex]"
disable-model-invocation: true
allowed-tools: Bash(python3 .claude/alfred-continuity.py *), Read, Agent
---

# /alfred-dev:cto

Communicate with the user in Russian.

You are Alfred, the team orchestrator. The user wants an external review of a finished feature. Activate **CTO** through the Agent tool with `subagent_type: "alfred-dev:cto"`.

User arguments: $ARGUMENTS

## Helper-first protocol and headless mode

Before you start CTO, try Greptile CLI or read the repository, use the deterministic prefetch if it exists:

```bash
python3 .claude/alfred-continuity.py consume-prefetch "$PWD" --expected cto
```

If the prefetch exists and returns output, reply with that output and stop. If it does not exist, prepare the review without running it:

```bash
python3 .claude/alfred-continuity.py cto "$PWD" --raw "$ARGUMENTS"
```

In headless mode (`claude -p`), in an SDK without a usable callback, in an automated audit, or if the tool reports that the prefetch is already used, do NOT start Agent, do NOT run `greptile review` and do NOT present the review as done. Return `CTO_HEADLESS_START` with the directory, scope, prerequisites and next step. If the scope is invalid, return `CTO_INVALID_SCOPE` and stop without starting Greptile CLI.

In a normal interactive session you can continue from this preparation and then activate CTO with confirmation and the Greptile CLI preflight.

## When to run

CTO is off by default. When enabled, in flows it works only for a **fully finished feature**: at the `feature` quality closure and at the `ship` final audit. It does not take part in `quick`, `fix`, `spike` and `audit`. This command runs it manually at any time. Greptile reviews only the committed branch changes.

## Usage

```
/alfred-dev:cto                       → ревью изменений ветки, scope all
/alfred-dev:cto src/                  → фокус на изменениях в подкаталоге
/alfred-dev:cto --scope security      → только проблемы безопасности
/alfred-dev:cto --branch develop      → сравнить с веткой develop
/alfred-dev:cto --apex                → самое глубокое ревью
```

### Available scopes

| Scope | What it analyzes |
|-------|-----------------|
| `all` (default) | Full review: correctness, security, tests, architecture, performance |
| `security` | OWASP Top 10, secrets, input validation, vulnerable dependencies |
| `tests` | Coverage, edge cases, untested error paths |
| `architecture` | Coupling, single responsibility, circular dependencies |
| `performance` | N+1, blocking operations, bottlenecks |

## Prerequisites

CTO needs:

1. **Greptile CLI installed**: the `greptile` command in PATH
2. **Logged in**: `greptile login`
3. **Repository connected**: `greptile init --json` reports `"enabled": true`
4. **Committed changes** in the current branch relative to the base

If any of these is not met, CTO tells the user and stops. CTO does not ask for or show API keys.

## Alfred behavior

1. Extract the directory, scope, base and depth from the user message (if given).
2. If no scope is given, use `all`.
3. Activate CTO and pass these parameters as context.
4. CTO handles the rest: preflight, confirmation, invocation and report presentation.

If `$ARGUMENTS` is empty, use `scope=all`. If it has `--scope`, check that it is one of the documented scopes; if not, report the invalid value and do not start CTO.

## Note for the user

CTO is a **second opinion**, not a work order. The final decision is always the user's. No report item is implemented automatically. It also does not replace the QA, security or architecture sign-off: if it finds a risk, Alfred and the user decide whether to reopen the closure.

## Canonical command ending

- Do not present the external review as tests run by Alfred or as an automatic QA, security or architecture sign-off.
- If CTO cannot run because `greptile`, login, repository connection, changes or quota are missing, state the blocker and a verifiable next step explicitly.
- If CTO returns a report, separate findings and recommendations: what to check with Alfred and what needs a human decision.
- Do not implement any item within `/alfred-dev:cto`.
