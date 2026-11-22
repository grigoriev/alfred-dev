#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Alfred Dev -- install script for Claude Code
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/install.sh | bash
#   bash ./install.sh
#
# What it does:
#   1. Checks that Claude Code is installed
#   2. Registers the plugin GitHub source globally in Claude Code
#   3. Installs the plugin with claude plugin install
#   4. Does not touch ~/.claude/skills and does not install a global /alfred alias
#   5. Ready to use: /alfred-dev:alfred
#
# The script delegates all management to the native Claude Code CLI
# (claude plugin marketplace / claude plugin install). It registers a
# custom, unofficial GitHub source and stays compatible with future versions.
# ---------------------------------------------------------------------------

set -euo pipefail

REPO="grigoriev/alfred-dev"
PLUGIN_NAME="alfred-dev"
VERSION="0.9.0"

# -- Colors -----------------------------------------------------------------

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
DIM='\033[2m'
BOLD='\033[1m'
NC='\033[0m'

info()  { printf "${BLUE}>${NC} %s\n" "$1"; }
ok()    { printf "${GREEN}+${NC} %s\n" "$1"; }
error() { printf "${RED}x${NC} %s\n" "$1" >&2; }

resolve_installed_plugin_root() {
    local cache_dir="${HOME}/.claude/plugins/cache/${PLUGIN_NAME}"
    local exact="${cache_dir}/${PLUGIN_NAME}/${VERSION}"
    local legacy="${cache_dir}/${VERSION}"

    if [[ -d "${exact}" ]]; then
        printf '%s\n' "${exact}"
        return 0
    fi

    if [[ -d "${legacy}" ]]; then
        printf '%s\n' "${legacy}"
        return 0
    fi

    "${PYTHON_CMD}" - "${cache_dir}" "${VERSION}" <<'PYEOF'
import json
import os
import sys

cache_dir, target_version = sys.argv[1:3]
candidates = []

for root, _dirs, files in os.walk(cache_dir):
    if "plugin.json" not in files or ".claude-plugin" not in root:
        continue
    plugin_json = os.path.join(root, "plugin.json")
    try:
        with open(plugin_json, "r", encoding="utf-8") as fh:
            version = json.load(fh).get("version")
    except (OSError, json.JSONDecodeError):
        continue
    if version != target_version:
        continue
    plugin_root = os.path.dirname(root)
    try:
        mtime = os.path.getmtime(plugin_json)
    except OSError:
        mtime = 0
    candidates.append((mtime, plugin_root))

if not candidates:
    sys.exit(1)

candidates.sort(key=lambda item: item[0], reverse=True)
print(candidates[0][1])
PYEOF
}

is_global_source_registered() {
    local known_marketplaces_file="${HOME}/.claude/plugins/known_marketplaces.json"

    [[ -f "${known_marketplaces_file}" ]] || return 1

    "${PYTHON_CMD}" - "${known_marketplaces_file}" "${PLUGIN_NAME}" "${REPO}" <<'PYEOF'
import json
import sys

path, plugin_name, repo = sys.argv[1:4]

try:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
except (OSError, json.JSONDecodeError):
    sys.exit(1)

entry = data.get(plugin_name)
source = entry.get("source", {}) if isinstance(entry, dict) else {}

if source.get("source") == "github" and source.get("repo") == repo:
    sys.exit(0)

sys.exit(1)
PYEOF
}

normalize_to_user_scope_installation() {
    # Alfred Dev supports only a global user install. If someone installed it
    # before in local/project scope, clean up that trace in the current context
    # before reinstalling with --scope user.
    claude plugin uninstall "${PLUGIN_NAME}@${PLUGIN_NAME}" --scope local >/dev/null 2>&1 || true
    claude plugin uninstall "${PLUGIN_NAME}@${PLUGIN_NAME}" --scope project >/dev/null 2>&1 || true
    claude plugin marketplace remove "${PLUGIN_NAME}" --scope local >/dev/null 2>&1 || true
    claude plugin marketplace remove "${PLUGIN_NAME}" --scope project >/dev/null 2>&1 || true
    ok "Scopes local/project нормализованы; Alfred будет установлен глобально для пользователя"
}

remove_stale_user_marketplace_checkout() {
    local marketplace_dir="${HOME}/.claude/plugins/marketplaces/${PLUGIN_NAME}"

    if [[ -d "${marketplace_dir}" ]]; then
        rm -rf "${marketplace_dir}"
        ok "Локальный checkout marketplace очищен, чтобы не было устаревшего cache"
    fi
}

refresh_user_marketplace() {
    # Claude Code can keep a stale local clone of the marketplace even when
    # 'plugin install' succeeds. Force a refresh before install so that
    # cache/alfred-dev gets the current published version.
    if claude plugin marketplace update "${PLUGIN_NAME}" 2>&1; then
        ok "Локальный marketplace обновлён"
    else
        info "Не удалось выполнить 'claude plugin marketplace update'; продолжаю с только что зарегистрированным checkout"
    fi
}

verify_user_scope_installation() {
    local plugin_key="${PLUGIN_NAME}@${PLUGIN_NAME}"
    local list_json
    local verify_output

    if ! list_json=$(claude plugin list --json 2>/dev/null); then
        error "Не удалось подтвердить глобальный scope через 'claude plugin list --json'"
        error "Alfred Dev должен быть установлен со scope user."
        return 1
    fi

    if verify_output=$(
        CLAUDE_PLUGIN_LIST_JSON="${list_json}" "${PYTHON_CMD}" - "${plugin_key}" <<'PYEOF'
import json
import os
import sys

plugin_key = sys.argv[1]

try:
    entries = json.loads(os.environ.get("CLAUDE_PLUGIN_LIST_JSON", ""))
except json.JSONDecodeError as exc:
    print(f"Некорректный JSON в claude plugin list --json: {exc}", file=sys.stderr)
    sys.exit(1)

if not isinstance(entries, list):
    print("claude plugin list --json вернул не список", file=sys.stderr)
    sys.exit(1)

matches = [entry for entry in entries if isinstance(entry, dict) and entry.get("id") == plugin_key]
if not matches:
    print(f"{plugin_key} нет в claude plugin list --json", file=sys.stderr)
    sys.exit(1)

active_non_user = [
    entry for entry in matches
    if entry.get("enabled") is True and entry.get("scope") != "user"
]
if active_non_user:
    details = ", ".join(
        f"scope={entry.get('scope', 'unknown')} projectPath={entry.get('projectPath', '')}"
        for entry in active_non_user
    )
    print(f"Есть активные неглобальные установки {plugin_key}: {details}", file=sys.stderr)
    sys.exit(1)

enabled_user = [
    entry for entry in matches
    if entry.get("enabled") is True and entry.get("scope") == "user"
]
if not enabled_user:
    scopes = ", ".join(str(entry.get("scope", "unknown")) for entry in matches)
    print(f"{plugin_key} есть, но нет записи enabled со scope user. Найденные scopes: {scopes}", file=sys.stderr)
    sys.exit(1)

stale_non_user = [
    entry for entry in matches
    if entry.get("enabled") is not True and entry.get("scope") != "user"
]
if stale_non_user:
    details = ", ".join(
        f"scope={entry.get('scope', 'unknown')} projectPath={entry.get('projectPath', '')}"
        for entry in stale_non_user
    )
    print(f"ВНИМАНИЕ: остались старые неактивные записи {plugin_key}: {details}")
PYEOF
    ); then
        if [[ -n "${verify_output}" ]]; then
            info "${verify_output}"
        fi
        ok "Глобальная установка для пользователя подтверждена (--scope user)"
        return 0
    fi

    error "${verify_output}"
    return 1
}

# -- Checks ----------------------------------------------------------------

# The plugin hooks and core need Python 3.10+.
# On macOS, /usr/bin/python3 is often 3.9 (Apple). Users can have
# 3.10+ via Homebrew, pyenv or the official installer as python3.13,
# python3.12, etc. Find the best available version.

PYTHON_CMD=""
PYTHON_VERSION=""

# Search the most common candidates in descending order
for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [[ "$major" -ge 3 ]] && [[ "$minor" -ge 10 ]]; then
            PYTHON_CMD="$candidate"
            PYTHON_VERSION="$ver"
            break
        fi
    fi
done

if [[ -z "$PYTHON_CMD" ]]; then
    # Last attempt: Homebrew in the usual macOS paths
    for brew_path in /opt/homebrew/bin /usr/local/bin; do
        for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
            full="${brew_path}/${candidate}"
            if [[ -x "$full" ]]; then
                ver=$("$full" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
                major=$(echo "$ver" | cut -d. -f1)
                minor=$(echo "$ver" | cut -d. -f2)
                if [[ "$major" -ge 3 ]] && [[ "$minor" -ge 10 ]]; then
                    PYTHON_CMD="$full"
                    PYTHON_VERSION="$ver"
                    break 2
                fi
            fi
        done
    done
fi

if [[ -z "$PYTHON_CMD" ]]; then
    error "Python 3.10 или новее не найден"
    error "Искали: python3, python3.13, python3.12, python3.11, python3.10"
    error "Также в /opt/homebrew/bin и /usr/local/bin"
    error ""
    error "Установи Python с https://www.python.org/downloads/"
    error "или через Homebrew: brew install python@3.12"
    exit 1
fi

ok "Найден Python $PYTHON_VERSION ($PYTHON_CMD)"

# If python3 in PATH is not the one we found, warn the user
DEFAULT_PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
if [[ "$PYTHON_CMD" != "python3" ]] && [[ "$DEFAULT_PY_VER" != "$PYTHON_VERSION" ]]; then
    info "Примечание: 'python3' в твоём PATH это $DEFAULT_PY_VER (слишком старая версия)"
    info "Hooks плагина будут использовать '$PYTHON_CMD' вместо него"
fi

if [[ -z "${HOME:-}" ]] || [[ ! -d "${HOME}" ]]; then
    error "Переменная HOME не задана или не указывает на существующий каталог"
    exit 1
fi

if [ ! -d "${HOME}/.claude" ]; then
    error "Каталог ~/.claude не найден"
    error "Убедись, что Claude Code установлен: https://code.claude.com/docs/en/setup"
    exit 1
fi

if ! command -v claude &>/dev/null; then
    error "Команды 'claude' нет в PATH"
    error "Убедись, что Claude Code установлен и доступен из терминала"
    exit 1
fi

# -- Install ----------------------------------------------------------------

printf "\n${BOLD}Alfred Dev${NC} ${DIM}v${VERSION}${NC}\n"
printf "${DIM}Плагин автоматизированной разработки ПО${NC}\n\n"

# -- 1. Register the global source in Claude Code ---------------------------
# If it exists, remove it first to force a refresh of the global registry
# and the cache with the latest repo files.

info "Регистрирую глобальный GitHub-источник в Claude Code..."
normalize_to_user_scope_installation

# If a previous install exists, remove it before the marketplace refresh.
# This prevents intermediate states where the plugin still points to a
# corrupt or incomplete marketplace on disk.
if claude plugin list 2>/dev/null | grep -q "${PLUGIN_NAME}@${PLUGIN_NAME}"; then
    claude plugin uninstall "${PLUGIN_NAME}@${PLUGIN_NAME}" --scope user >/dev/null 2>&1 || true
fi

if claude plugin marketplace list 2>/dev/null | grep -q "${PLUGIN_NAME}"; then
    claude plugin marketplace remove "${PLUGIN_NAME}" --scope user >/dev/null 2>&1 || true
fi
remove_stale_user_marketplace_checkout

if claude plugin marketplace add "${REPO}" --scope user 2>&1; then
    ok "GitHub-источник объявлен"
else
    error "Не удалось зарегистрировать GitHub-источник"
    error "Проверь подключение к интернету и доступность репозитория:"
    error "  https://github.com/${REPO}"
    exit 1
fi

# The install is global not because of a specific folder, but because
# Claude Code records the source in known_marketplaces.json.
if is_global_source_registered; then
    ok "GitHub-источник зарегистрирован глобально"
else
    info "CLI ответил OK, но источник не зарегистрирован; пробую снова..."
    claude plugin marketplace remove "${PLUGIN_NAME}" --scope user >/dev/null 2>&1 || true
    if claude plugin marketplace add "${REPO}" --scope user 2>&1 && is_global_source_registered; then
        ok "GitHub-источник зарегистрирован глобально со второй попытки"
    else
        error "Claude Code не зарегистрировал глобальный источник плагина"
        error "Ожидаемый файл: ${HOME}/.claude/plugins/known_marketplaces.json"
        error "Попробуй выполнить вручную:"
        error "  claude plugin marketplace remove ${PLUGIN_NAME} --scope user"
        error "  claude plugin marketplace add ${REPO} --scope user"
        exit 1
    fi
fi

refresh_user_marketplace

# -- 2. Install the plugin --------------------------------------------------

info "Устанавливаю плагин..."

if claude plugin install "${PLUGIN_NAME}@${PLUGIN_NAME}" --scope user 2>&1; then
    ok "Плагин установлен и включён"
else
    error "Не удалось установить плагин"
    error "Можно установить его вручную:"
    error "  claude plugin marketplace add ${REPO} --scope user"
    error "  claude plugin install ${PLUGIN_NAME}@${PLUGIN_NAME} --scope user"
    exit 1
fi

info "Используй /alfred-dev:alfred или /alfred-dev:feature. ~/.claude/skills не затрагивается."
verify_user_scope_installation

# -- 3. Patch hooks and MCP if python3 is not 3.10+ ------------------------
# If the default system python3 is too old but we found a compatible
# version (python3.12, python3.11, etc.), update the installed config
# so that the hooks and the MCP server use that exact version.

if [[ "$PYTHON_CMD" != "python3" ]]; then
    _patch_in_place() {
        local file="$1"
        local expression="$2"

        if sed -i.bak "$expression" "$file" 2>/dev/null; then
            rm -f "${file}.bak"
            return 0
        fi

        # macOS sed has a different -i syntax
        sed -i '' "$expression" "$file" 2>/dev/null
    }

    # Get the absolute path of the compatible Python
    PYTHON_ABS=$(command -v "$PYTHON_CMD" 2>/dev/null || echo "$PYTHON_CMD")

    # Resolve the root of the freshly installed plugin deterministically.
    # If several versions are in the cache, prefer the exact path of the
    # version that was just installed and, as a last resort, the newest
    # one whose plugin.json declares that version.
    PLUGIN_ROOT=$(resolve_installed_plugin_root 2>/dev/null || true)
    HOOKS_JSON=""
    MCP_JSON=""
    if [[ -n "${PLUGIN_ROOT}" ]]; then
        HOOKS_JSON="${PLUGIN_ROOT}/hooks/hooks.json"
        MCP_JSON="${PLUGIN_ROOT}/.mcp.json"
    fi

    if [[ -f "$HOOKS_JSON" ]]; then
        if "${PYTHON_CMD}" - "$HOOKS_JSON" "$PYTHON_ABS" <<'PYEOF'
import json
import os
import sys
import tempfile

path, python_abs = sys.argv[1:3]

with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

patched = False
for event_group in data.get("hooks", {}).values():
    if not isinstance(event_group, list):
        continue
    for matcher in event_group:
        if not isinstance(matcher, dict):
            continue
        for hook in matcher.get("hooks", []):
            if not isinstance(hook, dict) or hook.get("type") != "command":
                continue
            command = hook.get("command")
            if command == "python3":
                hook["command"] = python_abs
                patched = True
            elif isinstance(command, str) and "python3 ${CLAUDE_PLUGIN_ROOT}" in command:
                hook["command"] = command.replace(
                    "python3 ${CLAUDE_PLUGIN_ROOT}",
                    f"{python_abs} ${{CLAUDE_PLUGIN_ROOT}}",
                )
                patched = True

if not patched:
    raise SystemExit("в hooks.json нет Python hooks для патча")

directory = os.path.dirname(path)
fd, tmp_path = tempfile.mkstemp(prefix=".tmp-plugin-", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp_path, path)
except Exception:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    raise
PYEOF
        then
            ok "hooks.json пропатчен на $PYTHON_ABS"
        else
            info "Внимание: не удалось пропатчить hooks.json, hooks будут использовать 'python3'"
        fi
    else
        info "Внимание: в активной установке нет hooks.json для патча Python"
    fi

    if [[ -f "$MCP_JSON" ]]; then
        if "${PYTHON_CMD}" - "$MCP_JSON" "$PYTHON_ABS" <<'PYEOF'
import json
import os
import sys
import tempfile

path, python_abs = sys.argv[1:3]

with open(path, "r", encoding="utf-8") as fh:
    data = json.load(fh)

mcp_servers = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else data
if not isinstance(mcp_servers, dict):
    raise SystemExit("в .mcp.json не объявлены MCP-серверы")

alfred_memory = mcp_servers.get("alfred-memory")
if not isinstance(alfred_memory, dict):
    raise SystemExit("в .mcp.json не объявлен alfred-memory")

alfred_memory["command"] = python_abs

directory = os.path.dirname(path)
fd, tmp_path = tempfile.mkstemp(prefix=".tmp-plugin-", dir=directory)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp_path, path)
except Exception:
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    raise
PYEOF
        then
            ok ".mcp.json пропатчен на $PYTHON_ABS"
        else
            info "Внимание: не удалось пропатчить .mcp.json, MCP будет использовать 'python3'"
        fi
    else
        info "Внимание: в активной установке нет .mcp.json для патча Python"
    fi
fi

# -- Result ----------------------------------------------------------------

printf "\n${GREEN}${BOLD}Установка завершена${NC}\n\n"
printf "  В Claude Code выполни ${BOLD}/reload-plugins${NC}, а затем:\n"
printf "  ${BOLD}/alfred-dev:alfred${NC}\n"
printf "  ${DIM}Статус: /alfred-dev:progress · продолжить: /alfred-dev:resume${NC}\n\n"
printf "  ${DIM}Если /reload-plugins предупреждает о MCP/стоимости cache или плагин не появился, перезапусти Claude Code.${NC}\n"
printf "  ${DIM}Репозиторий: https://github.com/${REPO}${NC}\n"
printf "  ${DIM}Документация: https://alfred-dev.com${NC}\n\n"
