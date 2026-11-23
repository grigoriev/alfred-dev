---
description: "Проверяет и применяет обновления плагина Alfred Dev"
disable-model-invocation: true
allowed-tools: Bash, Read
---

# /alfred-dev:update

Communicate with the user in Russian.

You are Alfred. The user wants to check for a new plugin version. Follow these steps exactly.

## Step 1: get the installed version and scope

First use the native Claude Code CLI. It is the authoritative source of active installs, scope and installPath:

```bash
claude plugin list --json
```

Find the `alfred-dev@alfred-dev` entry. If there are several, use this priority:

1. an `enabled: true` entry whose `projectPath`, if present, matches the current project;
2. an `enabled: true` entry without `projectPath` (`user` install);
3. any `alfred-dev@alfred-dev` entry as a last resort.

Extract:

- `version`
- `scope` (`user`, `local`, `project` or `managed`)
- `installPath`
- `projectPath`, if present

If `claude plugin list --json` fails or returns no entry, use this cache fallback for the version and mark scope as `unknown`:

```bash
python3 -c "
import json, os, glob, sys

candidates = sorted(
    glob.glob(os.path.expanduser('~/.claude/plugins/cache/alfred-dev/**/.claude-plugin/plugin.json'), recursive=True),
    key=os.path.getmtime,
    reverse=True
)
if not candidates:
    print('unknown')
    sys.exit(0)
with open(candidates[0]) as f:
    print(json.load(f).get('version', 'unknown'))
" 2>/dev/null || echo "unknown"
```

The fallback picks the newest version by modification date to avoid errors when several versions coexist in the cache. Do not use it to determine scope if the CLI returned one.

## Step 2: query the latest GitHub release

Run with Bash:

```bash
curl -s --max-time 10 "https://api.github.com/repos/grigoriev/alfred-dev/releases/latest"
```

Extract from the JSON: `tag_name` (version), `name` (title), `body` (release notes), `published_at` (date).

If the request fails (no network, rate limit, timeout), report the error and suggest retrying later. Do not continue. Specifically:

- If the JSON contains `"message": "API rate limit exceeded"`, tell the user they hit the GitHub rate limit and can retry in a few minutes or pass a token with `-H "Authorization: token ..."`.
- If curl returns an error code or timeout, show the error and suggest checking the connection.
- If the JSON has no `tag_name`, the response is unexpected. Show the raw content and stop.

## Step 3: compare versions

Check that `tag_name` is valid semver: it must match `v?X.Y.Z`, where X, Y, Z are numbers (for example `v0.3.0` or `0.3.0`). If it does not match, show a warning and stop: the release format is not as expected.

Normalize `tag_name` (without the leading `v`) and the installed version to numeric tuples `(major, minor, patch)` and compare them as real semver. **Never** compare versions as plain text (`0.10.0` is greater than `0.9.0`).

For a deterministic comparison, run with Bash:

```bash
python3 - <<'PY'
def parse(value):
    value = value.strip().lstrip('v')
    return tuple(int(part) for part in value.split('.'))

installed = "INSTALLED_VERSION"
latest = "TAG_NAME"

print(parse(latest) > parse(installed))
PY
```

Replace `INSTALLED_VERSION` and `TAG_NAME` with the real values from steps 1 and 2.

### If a new version exists

Show the user:
- The current installed version
- The new available version
- The release notes, formatted as markdown

Then use **one `AskUserQuestion`** with a real selectable menu. Do not leave the decision to free text. The two options are:
- **"Обновить сейчас"** -- runs the install command (step 4)
- **"Не сейчас"** -- cancel

### If the version is current

Report that there are no updates and show the current version. Done.

## Step 4: run the update

If the user agrees, always use the global user path, unless scope is `managed`. Alfred Dev does not keep `local` and `project` installs when updating from this command: it normalizes them to `--scope user`, so `/alfred-dev:*` works in any user project. It does not recreate the global `/alfred` alias and does not touch `~/.claude/skills`.

### Scope user, local, project or unknown

For user, local, project or unknown-scope installs, use the supported Alfred Dev installer. This path re-registers the GitHub source with `--scope user`, reinstalls through the native Claude Code CLI, cleans/updates the local marketplace checkout to avoid stale caches, and does not touch `~/.claude/skills`. It reapplies the compatible Python patch in `hooks.json` and `.mcp.json` when needed.

If the detected scope was `local` or `project`, say so before running: the update turns this install into a global user install.
Do not use `claude plugin update --scope local` or `claude plugin update --scope project`.

First detect the platform, then run the matching installer.

### Platform detection

Run with Bash:

```bash
uname -s 2>/dev/null || echo "Windows"
```

- If it returns `Darwin` or `Linux`: macOS or Linux, use the bash installer.
- If it fails or returns `Windows` / `MINGW` / `MSYS` / `CYGWIN`: Windows, use the PowerShell installer.

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/grigoriev/alfred-dev/main/install.sh | bash
```

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/grigoriev/alfred-dev/main/install.ps1 | iex
```

### Scope managed

If the detected scope is `managed`, do not try to update it. Explain that managed installs are controlled by administrator policy and the user must ask whoever manages Claude Code in their team for the update.

After any update finishes, tell the user to run **`/reload-plugins`** in Claude Code to load the new version into the current session. A Claude Code restart is required if Claude Code warns about MCP/cache, if you decide not to use `/reload-plugins --force`, or if the inventory does not change.

## Notes

- The installers are idempotent: they overwrite the previous install without conflicts.
- In scope `user`, no uninstall is needed first.
- Do not replace this path with a direct `claude plugin update`, except for manual recovery: the installer exists to avoid stale local marketplaces.
- In scope `local` or `project`, do not keep the scope: convert to a global user install with the installer. Do not create `~/.claude/commands/alfred.md` or a personal `/alfred` skill. The entry point is `/alfred-dev:alfred`.
- If the install script fails, show the user the full error.
- On Windows it also works through WSL or Git Bash with the bash installer.

## Canonical command ending

- If there is no new version, stop there: do not offer extra steps or a dummy decision.
- If a new version exists, use one real selectable menu with the two options defined above. Do not replace it with free text.
- If the update succeeds, keep the ending short and actionable: the applied version, run `/reload-plugins`, and restart only if MCP/cache requires it or the inventory does not change.
