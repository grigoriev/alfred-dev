#!/usr/bin/env bash
# Short synchronous SessionStart. Does not call GitHub. Does not rewrite permissions.
# Routes: /alfred-dev:alfred /alfred-dev:feature /alfred-dev:audit /alfred-dev:progress /alfred-dev:retomar
# CTO on demand. Agent Teams only if it is already active.

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

FALLBACK="## Как говорить с Alfred

Если пользователь описывает работу, баг, просит продолжить, сдать результат или спрашивает, что дальше, без slash command, действуй как /alfred-dev:alfred: выбери маршрут и выполни его. Не предлагай каталог.

Основной маршрут: /alfred-dev:alfred. Процессы: /alfred-dev:feature, /alfred-dev:quick, /alfred-dev:fix, /alfred-dev:spike, /alfred-dev:audit, /alfred-dev:ship. Статус: /alfred-dev:progress. Продолжить: /alfred-dev:retomar.

Если в этой сессии активен Agent Teams, используй его для параллельных фаз; если нет, используй инструмент Agent. Не переписывай .claude/settings.json.

## Briefing

Открытой сессии нет. Спроси, что пользователь хочет сделать, или составь карту репозитория, если это brownfield.
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
