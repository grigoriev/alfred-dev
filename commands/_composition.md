---
description: "Внутренний общий протокол динамического формирования команды Alfred по задаче, стеку и runtime-сигналам."
---

# Dynamic team composition protocol

Communicate with the user in Russian.

This file defines the shared team composition protocol for each session. All Alfred commands use it (feature, quick, fix, spike, audit, ship). Any change here affects all flows.

## Step 0 -- Initial project setup

First check if the project has an autonomy mode configured. Read `.claude/alfred-dev.local.md` and find the `autonomy:` section in the YAML frontmatter.

**If there is NO `autonomy:` section** (first use of Alfred in this project):

1. Write the default configuration, compatible with Claude Code CLI, directly to `.claude/alfred-dev.local.md`:

   ```yaml
   autonomy:
     product: autonomous
     architecture: autonomous
     development: autonomous
     quality: autonomous
     documentation: autonomous
     delivery: autonomous
   ```

2. Do NOT use `AskUserQuestion` in this initial bootstrap. The goal is that Alfred can act automatically from the first session if the user calls `/alfred`, `/alfred-dev:feature`, `/alfred-dev:quick`, `/alfred-dev:fix`, `/alfred-dev:spike`, `/alfred-dev:audit` or `/alfred-dev:ship`.

3. Show a short message: Alfred enabled autopilot mode by default so the flow does not block in the first session, and the user can change it later with `/alfred-dev:config`.

**If the `autonomy:` section ALREADY exists:** skip this step and continue.

**Note:** the user can change the mode at any time with `/alfred-dev:config`.

## Step 1 -- Project context

Call `suggest_optional_agents(project_dir)` to get signals from project I/O (detected stack, ORM, frontend, public HTML, GitHub remote, project size, active memory). These signals are objective and complement your semantic reasoning.

## Step 2 -- Semantic reasoning

Read the task description and the project signals. Decide which optional agents are relevant from semantic understanding, not keywords. Reason about the task domain, not individual words.

### Optional agent catalog

The runtime supports only **CTO**. Do not offer or activate data-engineer, performance-engineer, github-manager, librarian, ux-reviewer, seo-specialist, copywriter and i18n-specialist.

| Agent | Specialization | When useful |
|-------|---------------|---------------|
| **cto** | External review of a finished feature through Greptile CLI, read only. Off by default | Only the `feature` quality closure (`quality`) and the `ship` final audit (`final_audit`) |

### Decision criteria

Ask yourself one question: **does this task close a fully finished feature in `feature` or `ship`?** If not, activate nobody else. The core covers product, design, code, security, QA, documentation and delivery.

## Step 2b -- Autopilot check

Before you ask the user anything, check if autopilot mode is active:

1. Read `.claude/alfred-dev.local.md` and check that all autonomy phases are `autonomous`.
2. Read `.claude/alfred-dev-state.json` and check for `"autopilot": true`.

**If the command is `quick`, `fix`, `spike` or `audit`:** go to step 4. Do not ask about CTO and do not open the optional agents menu. The core is enough. CTO does not take part in the phases of these flows, even if it is on. If the user wants an external review, offer `/alfred-dev:cto` as a separate step.

**If autopilot is active:** go directly to step 4. Use the optional agents configured in `.claude/alfred-dev.local.md` (if any), or those your semantic reasoning (step 2) marked as relevant. Do not use `AskUserQuestion`. Show a short message about which agents are activated and why.

**If autopilot is NOT active:** continue with step 3 (interactive presentation to the user).

## Step 2c -- Evidence check before automatic gates

Before you advance a phase with an automatic or automatic+security gate, read `.claude/alfred-evidence.json` and check that the last entry has `result: "pass"` and a timestamp within the last 10 minutes. If there is no evidence or the last result is not `pass`, do NOT advance. Run the tests first.

## Step 2d -- Save state after a gate

After each attempt to pass a gate (successful or not), save the updated state to `.claude/alfred-dev-state.json`. This includes the iteration counter of the current phase.

## Step 2e -- Operational honesty, no simulation

Before you declare a gate passed, a test run, an audit finished or an external integration verified, make sure you have direct evidence: tool output, a saved artifact or an explicit user answer.

- Do not say «я выполнил», «прошло» or «проверено» if you only assumed it.
- If a helper, command, agent or external service fails, say so with the matching error and keep the next step verifiable; do not turn it into success.
- If credentials, permissions, Docker, network or context are missing, state the limit and leave the flow pending or blocked.
- Always separate «рекомендую выполнить X» from «я выполнил X с таким результатом».

## Step 3 -- Presentation to the user

Before the questions, show an info message:

> **Базовая команда** (всегда активна): Alfred, Product Owner, Designer, если есть
> фронтенд, Architect, Senior Dev, Security Officer, QA Engineer, Tech Writer,
> DevOps. Kanban пишет runtime, а не отдельный агент.

CTO is off by default. If `.claude/alfred-dev.local.md` already has `optional_agents.cto`, use that value and do not ask. Otherwise treat CTO as inactive.

Use `AskUserQuestion` with **one menu** for the `Аудит` group only if the user wants to change the CTO choice for this session. Canonical source: `core/optional_agents.py` (`build_optional_agent_group_menu`). Do not invent Technical or Content groups.

Agents you found relevant (step 2) must have "(Рекомендуется)" at the end of the label. The `description` of each option must explain why it is relevant for this specific task, not be a generic agent description.

**IMPORTANT:** do not print a static list of three blocks without a real choice. Each group must be a selectable menu. If the user wants more than one agent from the same group, repeat the menu and let the user pick **one per interaction** until they pick `Продолжить без включения`.

Example of one group:

```text
AskUserQuestion({
  questions: [
    {
      question: "Хочешь активировать CTO как внешнее второе мнение?",
      header: "Аудит",
      multiSelect: false,
      options: [
        { label: "Продолжить без включения", description: "Перейти к следующей группе" },
        { label: "CTO", description: "<контекстная причина или краткое описание>" }
      ]
    }
  ]
})
```

If the user picks an agent, add it to the accumulated choice and show the same group again with the remaining options. When the user picks the group exit, go to the next group.

For the audit group, the minimal menu must keep this option visible:

```text
{ label: "CTO", description: "<контекстная причина>" }
```

In the `description` of each option:
- If the agent is **recommended**: explain why it is relevant for this task.
  Example: `"Проект использует Prisma, а задача включает миграцию схемы (Рекомендуется)"`.
- If **not recommended**: use a short description of its specialization.
  Example: `"Оптимизация позиций в поиске и Core Web Vitals"`.

The user can select, deselect or add any combination. The user's choice decides, regardless of your recommendations.

## Step 4 -- Build session_team

From the user's answer, build the `session_team` dictionary:

```
session_team = {
    "active_optionals": {
        "cto": True/False,
    },
    "infra": {
        "memory": True/False,
    },
    "source": "dynamic_composition",
}
```

Pass `session_team` through the flow. From now on each phase uses `session_team` instead of the persistent configuration to decide which optional agents take part.
