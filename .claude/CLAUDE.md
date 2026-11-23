# CLAUDE.md

This file guides Claude Code when it works on or reviews this repository.

## Project overview

Alfred Dev is a Claude Code plugin for software engineering: an orchestrator agent, specialist agents,
flows with quality gates (`feature`, `quick`, `fix`, `spike`, `audit`, `ship`), a PR loop that merges
on green, persistent memory over MCP and safety hooks. This is a Russian fork of
[686f6c61/alfred-dev](https://github.com/686f6c61/alfred-dev), now an independent repository.

## Layout

- `agents/*.md`: subagent prompts. `commands/*.md`: slash commands; files starting with `_` are shared
  protocols read by other commands. `skills/*/SKILL.md`: skills.
- `hooks/`: lifecycle hooks registered in `hooks/hooks.json` (session start, prompt routing, activity
  capture, secret, dangerous-command and sensitive-read guards, quality and evidence gates).
- `core/`: Python helpers. `continuity.py` is the deterministic helper behind most commands
  (`python3 .claude/alfred-continuity.py <command>` in a project); `pr_status.py` decides the PR loop
  verdict; `config_loader.py` owns `.claude/alfred-dev.local.md`.
- `mcp/`: the `alfred-memory` MCP server. `visual/`: the Designer browser helper.
- `scripts/release_audit.py`: contract checks between prompts, docs, manifests and code.

## Commands

```sh
python -m pytest tests/ -q
python scripts/release_audit.py --with-human-contracts --with-external-contracts --with-continuity --with-syntax
shellcheck --severity=warning $(git ls-files '*.sh')
actionlint && zizmor --min-severity low .github/
```

CI (`.github/workflows/ci.yml`) runs lint, the tests and the audit on Python 3.15, the plugin install on
Linux, macOS and Windows, and SonarCloud. The plugin itself supports Python 3.10+ at runtime.

## Conventions

- Languages: model prompts (agent, command and skill bodies, hook-injected context), code, comments,
  identifiers, tests and commits are English. What the user reads is Russian: chat, helper output shown
  to the user, menus, report templates, command `description` and `argument-hint`, generated
  documentation and the docs in `docs/`, `README.md` and `CHANGELOG.md`. No Spanish anywhere except
  CHANGELOG history.
- The version lives in `.claude-plugin/plugin.json`, `package.json`, `install.sh`, `install.ps1` and
  `scripts/release_audit.py`. Tags are `vX.Y.Z`; the release title is the tag.
- Conventional Commits without scope, signed commits, squash merge. No em-dashes, American spelling.
- A prompt change that renames or drops a sentence must update the contract needles in `tests/` and
  `scripts/release_audit.py`, never delete them.

## Review focus

Flag these in a pull request:

- Spanish text, or user-facing text that is not Russian, or a model prompt that is not English
- A command or agent rule lost in a rewrite: HARD-GATEs, prohibitions, helper invocations, markers such
  as `PR_STATUS_*`, `/alfred-dev:<name>` names
- A contract check removed or weakened instead of updated
- A hook that can crash, block or slow down every prompt or tool call, or that prints to stdout outside
  the hook protocol
- A guard (secret, dangerous command, sensitive read) that gets weaker or can be bypassed
- A PR loop change that can merge without the verdict `PR_STATUS_MERGE`, uses `--force`, `--admin` or
  `--no-verify`, or weakens the SonarCloud or Greptile thresholds
- Frontmatter that a strict YAML parser rejects
- Version files out of sync, or no `## [Unreleased]` entry in `CHANGELOG.md` for a behavior change
- Missing tests for new behavior
