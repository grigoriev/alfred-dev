#!/usr/bin/env bash
# Short synchronous SessionStart. Does not call GitHub. Does not rewrite permissions.
# Routes: /alfred-dev:alfred /alfred-dev:feature /alfred-dev:audit /alfred-dev:progress /alfred-dev:resume
# CTO reviews finished features. Agent Teams only if it is already active.

set -euo pipefail

PROJECT_DIR="${PWD}"
PLUGIN_ROOT=$(cd "$(dirname "$0")/.." && pwd)

emit_hook_json() {
  python3 -c "
import json, sys
context = sys.stdin.read()
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': context,
    }
}, ensure_ascii=False))
"
}

FALLBACK="## Working with Alfred

Communicate with the user in Russian.

If the user describes work or a bug, asks to continue, to deliver, or what is next, without a slash command, act as /alfred-dev:alfred: choose the route and run it. Do not offer a catalog.

Main route: /alfred-dev:alfred. Flows: /alfred-dev:feature, /alfred-dev:quick, /alfred-dev:fix, /alfred-dev:spike, /alfred-dev:audit, /alfred-dev:ship. Status: /alfred-dev:progress. Continue: /alfred-dev:resume.

If Agent Teams is active in this session, use it for parallel phases; otherwise use the Agent tool. Do not rewrite .claude/settings.json.

## Briefing

No open session. Ask what the user wants to do, or map the repository if it is brownfield.
"

CONTEXT=$(
  PYTHONPATH="${PLUGIN_ROOT}" python3 - "${PROJECT_DIR}" <<'PY' 2>/dev/null || true
import sys
from core.session_brief import render_session_start_context

print(render_session_start_context(sys.argv[1]), end="")
PY
)

if [[ -z "${CONTEXT//[[:space:]]/}" ]]; then
  CONTEXT="$FALLBACK"
fi

printf '%s' "$CONTEXT" | emit_hook_json
