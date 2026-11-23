---
description: "Настраивает Alfred Dev: автономность, проект, CTO, память и личность."
---

# /alfred-dev:config

Communicate with the user in Russian.

Read `.claude/alfred-dev.local.md` if it exists. If not, create it with the current canonical plugin configuration.

Write only canonical keys to the frontmatter, for example `autonomy`. The runtime reads only them.

## Step 0: deterministic helper

Before you reason or ask anything, run this Bash immediately. It loads or creates the configuration, detects the stack, builds the 7 sections and generates the canonical menu:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/core/config_cli.py" "$PWD" --headless
```

Save this stdout as `CONFIG_SUMMARY`. If the command fails because `CLAUDE_PLUGIN_ROOT` does not exist in local development, retry once with `python3 core/config_cli.py "$PWD" --headless`, only if you are in the plugin repository. In headless mode `CONFIG_SUMMARY` must contain the literal marker `CONFIG_HEADLESS_MENU`.

## Non-interactive mode / `claude -p`

If this call runs in non-interactive/headless mode (`claude -p`, SDK without a `canUseTool` callback, automated audit, or any context where you cannot get the user's choice in the same call), **do not call `AskUserQuestion`**. In this mode:

1. return `CONFIG_SUMMARY` as is, do not rewrite it as another table;
2. do not open submenus;
3. do not end with an open question.

In headless mode, do not wait indefinitely for a human answer. Do not open the optional agents or memory submenus without a real user choice.
If you call `AskUserQuestion` and the tool returns canceled, with no choice, with no usable answer, or with any sign that the user could not choose, treat it as headless mode: return `CONFIG_SUMMARY` as is. Do not turn this cancellation into an open question such as «над какой секцией работать?».

Show the user the current configuration by section:

1. **Autonomy per phase** (`interactive` / `semi-autonomous` / `autonomous`): product, architecture, development, quality, documentation, delivery
2. **Project** (detected or set manually): runtime, language, framework, ORM, test runner, bundler
3. **Optional agents**: CTO only
4. **Persistent memory**: enabled, sync_to_native, sync_commits_limit, capture_decisions, capture_commits, retention_days
5. **Compliance**: style, lint, format_on_save
6. **Integrations**: git, ci, deploy
7. **Personality**: language, verbosity

Use AskUserQuestion to ask which section to change, through a **navigable main menu**. Do not build this menu by hand if you can avoid it: use the canonical functions from `core/config_loader.py` (`build_config_section_summaries()` and `build_config_section_menu()`), so each section description comes from the real effective configuration, not from text rebuilt in the prompt. Update the `.local.md` file after each change.

Before saving, build a **before/after preview** of the affected section. Do not improvise this diff in prose if you can avoid it: use `build_config_section_change_preview()` to confirm what actually changes and to detect a no-op before you overwrite the file.

When the user confirms, do not build the "load → apply → save" loop by hand: use `update_config_section()` or `update_project_config_section()` to save only the affected section without losing notes, stable order and canonical keys.

Do not rewrite the frontmatter by hand if you can avoid it: use the canonical functions from `core/config_loader.py` (`render_config_markdown()`, `save_config()`, `save_project_config()` and `apply_config_section_update()`) to keep stable order, canonical keys and a clean round-trip with `load_config()`.

If the project has no configuration and the current directory has files, run automatic stack detection and show the results to the user for confirmation. On the first project session, SessionStart may already have created `.claude/alfred-dev.local.md` with `autonomous` autonomy for all phases and memory enabled.

## Optional agents section

The runtime supports only **CTO**. Do not offer data-engineer, github-manager, copywriter, librarian or the rest of the 0.6 catalog.

| Agent | Role | When useful |
|-------|------|-------------|
| **cto** | CTO | External review of a finished feature through Greptile CLI. Disabled by default. Runs only at the `feature` quality close and the `ship` final audit |

Use the canonical menu from `core/optional_agents.py` (`build_optional_agent_group_menu`) with the single group `Аудит`.

```text
AskUserQuestion({
  questions: [
    {
      question: "Хочешь активировать CTO как внешнее второе мнение?",
      header: "Аудит",
      multiSelect: false,
      options: [
        { label: "Продолжить без включения", description: "Перейти к следующей группе" },
        { label: "CTO", description: "<контекстная причина>" }
      ]
    }
  ]
})
```

Save only this key. The default is `false`:

```yaml
optional_agents:
  cto: false
```

If the user enables CTO, write `cto: true`.

## Persistent memory section

Persistent memory stores decisions, gates, handoffs, UAT and commits made in an Alfred session. It does not import old Git history and does not fill the UI with operational tips. To access it, use the `alfred-memory` MCP tools or `/alfred-dev:memory-ui`.

### Step 1: check the current state

First read the effective configuration and check `memory.enabled`:

- **If `memory.enabled` is `true` and `.claude/alfred-memory.db` exists**: read statistics with the MCP tool `memory_stats` and show a compact summary: number of decisions, logged commits, iterations and the date of the oldest record. State that memory is **active**.
- **If `memory.enabled` is `true` but the DB does not exist yet**: state that memory is **configured as active** and that the database will be initialized on the next run or when the runtime needs it.
- **If `memory.enabled` is `false`**: state that memory is **inactive**, although historical data can exist in `.claude/alfred-memory.db`.

### Step 2: ask the user

Use AskUserQuestion to ask whether the user wants to enable or disable persistent memory. Present the options clearly:

- **Включить**: Alfred will log project decisions, gates, handoffs, UAT and session commits.
- **Выключить**: nothing new is logged. Existing data is kept, but Alfred does not collect or use it.

### Step 3: apply the configuration

If the user chooses to **enable** memory, write (or update) the `memory:` section in the `.claude/alfred-dev.local.md` frontmatter with these values:

```yaml
memory:
  enabled: true
  sync_to_native: true
  sync_commits_limit: 10
  capture_decisions: true
  capture_commits: true
  retention_days: 365
```

If the user chooses to **disable** memory, update the section to:

```yaml
memory:
  enabled: false
```

### Step 4: confirm

Tell the user the result:

- If enabled: confirm that only useful items are logged (decisions, gates, handoffs, UAT, session commits).
- If disabled: confirm that memory is inactive, but existing data is not deleted.
