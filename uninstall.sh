#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Alfred Dev -- uninstall script
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/grigoriev/alfred-dev/main/uninstall.sh | bash
#   bash ./uninstall.sh
#
# Strategy:
#   1. If Claude CLI is available, uninstall the plugin and remove the
#      marketplace the native way.
#   2. Remove any leftover files in cache/ and marketplaces/.
#   3. As a safety net, clean known_marketplaces.json,
#      installed_plugins.json and settings.json if they still have traces.
# ---------------------------------------------------------------------------

set -euo pipefail

PLUGIN_NAME="alfred-dev"
PLUGIN_KEY="${PLUGIN_NAME}@${PLUGIN_NAME}"
CLAUDE_DIR="${HOME}/.claude"
PLUGINS_DIR="${CLAUDE_DIR}/plugins"
MARKETPLACE_DIR="${PLUGINS_DIR}/marketplaces/${PLUGIN_NAME}"
INSTALLED_FILE="${PLUGINS_DIR}/installed_plugins.json"
KNOWN_MARKETPLACES="${PLUGINS_DIR}/known_marketplaces.json"
SETTINGS_FILE="${CLAUDE_DIR}/settings.json"
GLOBAL_ALIAS_DIR="${CLAUDE_DIR}/skills/alfred"
GLOBAL_ALIAS_FILE="${GLOBAL_ALIAS_DIR}/SKILL.md"
GLOBAL_COMMAND_ALIAS_DIR="${CLAUDE_DIR}/commands"
GLOBAL_COMMAND_ALIAS_FILE="${GLOBAL_COMMAND_ALIAS_DIR}/alfred.md"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

info()  { printf "${BLUE}>${NC} %s\n" "$1"; }
ok()    { printf "${GREEN}+${NC} %s\n" "$1"; }
error() { printf "${RED}x${NC} %s\n" "$1" >&2; }

remove_global_alfred_alias() {
    local removed=0

    if [[ -f "${GLOBAL_ALIAS_FILE}" ]]; then
        if grep -q "Alfred Dev global alias" "${GLOBAL_ALIAS_FILE}"; then
            rm -f "${GLOBAL_ALIAS_FILE}"
            rmdir "${GLOBAL_ALIAS_DIR}" >/dev/null 2>&1 || true
            ok "Глобальный alias /alfred удалён"
            removed=1
        else
            info "${GLOBAL_ALIAS_FILE} сохранён: похоже, это не alias Alfred Dev"
        fi
    fi

    if [[ -f "${GLOBAL_COMMAND_ALIAS_FILE}" ]]; then
        if grep -q "Alfred Dev global alias" "${GLOBAL_COMMAND_ALIAS_FILE}"; then
            rm -f "${GLOBAL_COMMAND_ALIAS_FILE}"
            rmdir "${GLOBAL_COMMAND_ALIAS_DIR}" >/dev/null 2>&1 || true
            ok "Глобальный shim команды /alfred удалён"
            removed=1
        else
            info "${GLOBAL_COMMAND_ALIAS_FILE} сохранён: похоже, это не alias Alfred Dev"
        fi
    fi

    if [[ "${removed}" -eq 0 ]]; then
        info "Глобальный alias /alfred не найден"
    fi
}

find_compatible_python() {
    local candidate ver major minor

    for candidate in python3 python3.13 python3.12 python3.11 python3.10; do
        if ! command -v "$candidate" &>/dev/null; then
            continue
        fi
        ver=$("$candidate" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [[ "$major" -ge 3 ]] && [[ "$minor" -ge 10 ]]; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    for brew_path in /opt/homebrew/bin /usr/local/bin; do
        for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
            local full="${brew_path}/${candidate}"
            if [[ ! -x "$full" ]]; then
                continue
            fi
            ver=$("$full" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [[ "$major" -ge 3 ]] && [[ "$minor" -ge 10 ]]; then
                printf '%s\n' "$full"
                return 0
            fi
        done
    done

    return 1
}

# Check that HOME points to a real directory
if [[ -z "${HOME:-}" ]] || [[ ! -d "${HOME}" ]]; then
    error "Переменная HOME не задана или не указывает на существующий каталог"
    exit 1
fi

if [[ ! -d "${CLAUDE_DIR}" ]]; then
    info "${CLAUDE_DIR} не найден; пользовательской установки для удаления нет"
    exit 0
fi

printf "\n${BOLD}Удаляю Alfred Dev${NC}\n\n"

# Try the canonical Claude Code way first.
if command -v claude &>/dev/null; then
    info "Удаляю плагин через Claude CLI..."
    claude plugin uninstall "${PLUGIN_KEY}" --scope user >/dev/null 2>&1 || true
    claude plugin marketplace remove "${PLUGIN_NAME}" --scope user >/dev/null 2>&1 || true
    ok "Claude CLI попытался снять регистрацию плагина и marketplace"
else
    info "Команда 'claude' недоступна; выполняю ручную страховочную очистку"
fi

# Remove the plugin cache.
# Delete the whole cached marketplace directory (cache/alfred-dev/)
# so that new installs (cache/alfred-dev/alfred-dev/<version>) and
# old ones (cache/alfred-dev/<version>) are cleaned the same way.
CACHE_MARKETPLACE_DIR="${PLUGINS_DIR}/cache/${PLUGIN_NAME}"
if [ -d "${CACHE_MARKETPLACE_DIR}" ]; then
    rm -rf "${CACHE_MARKETPLACE_DIR}"
    ok "Cache плагина удалён"
else
    info "Cache плагина не найден"
fi

# Remove the marketplace directory
if [ -d "${MARKETPLACE_DIR}" ]; then
    rm -rf "${MARKETPLACE_DIR}"
    ok "Каталог marketplace удалён"
else
    info "Каталог marketplace не найден"
fi

remove_global_alfred_alias

# Without a compatible Python, skip the residual JSON cleanup.
PYTHON_CMD="$(find_compatible_python || true)"
if [[ -z "${PYTHON_CMD}" ]]; then
    info "Python 3.10+ не найден; пропускаю остаточную очистку JSON-файлов"
    printf "\n${GREEN}${BOLD}Alfred Dev удалён${NC}\n"
    printf "  ${DIM}Перезапусти Claude Code, чтобы применить изменения.${NC}\n\n"
    exit 0
fi

# Remove the marketplace from known_marketplaces.json if a trace remains.
if [ -f "${KNOWN_MARKETPLACES}" ]; then
    "${PYTHON_CMD}" - "${KNOWN_MARKETPLACES}" "${PLUGIN_NAME}" <<'PYEOF'
import json, os, sys, tempfile

known_file, marketplace_name = sys.argv[1:3]

try:
    with open(known_file, 'r') as f:
        data = json.load(f)
except json.JSONDecodeError as e:
    print(f"Ошибка: в '{known_file}' некорректный JSON: {e}", file=sys.stderr)
    sys.exit(1)
except OSError as e:
    print(f"Ошибка: не удалось прочитать '{known_file}': {e}", file=sys.stderr)
    sys.exit(1)

if marketplace_name in data:
    del data[marketplace_name]

# Atomic write
try:
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(known_file))
    with os.fdopen(tmp_fd, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, known_file)
except OSError as e:
    print(f"Ошибка: не удалось записать '{known_file}': {e}", file=sys.stderr)
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    sys.exit(1)
PYEOF
    ok "Marketplace удалён из known_marketplaces.json"
fi

# Remove the entry from installed_plugins.json if a trace remains.
if [ -f "${INSTALLED_FILE}" ]; then
    "${PYTHON_CMD}" - "${INSTALLED_FILE}" "${PLUGIN_KEY}" <<'PYEOF'
import json, os, sys, tempfile

installed_file, plugin_key = sys.argv[1:3]

try:
    with open(installed_file, 'r') as f:
        data = json.load(f)
except json.JSONDecodeError as e:
    print(f"Ошибка: в '{installed_file}' некорректный JSON: {e}", file=sys.stderr)
    sys.exit(1)
except OSError as e:
    print(f"Ошибка: не удалось прочитать '{installed_file}': {e}", file=sys.stderr)
    sys.exit(1)

if plugin_key in data.get('plugins', {}):
    del data['plugins'][plugin_key]

# Atomic write
try:
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(installed_file))
    with os.fdopen(tmp_fd, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, installed_file)
except OSError as e:
    print(f"Ошибка: не удалось записать '{installed_file}': {e}", file=sys.stderr)
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    sys.exit(1)
PYEOF
    ok "Запись удалена из installed_plugins.json"
fi

# Disable in settings.json if a trace remains.
if [ -f "${SETTINGS_FILE}" ]; then
    "${PYTHON_CMD}" - "${SETTINGS_FILE}" "${PLUGIN_KEY}" <<'PYEOF'
import json, os, sys, tempfile

settings_file, plugin_key = sys.argv[1:3]

try:
    with open(settings_file, 'r') as f:
        data = json.load(f)
except json.JSONDecodeError as e:
    print(f"Ошибка: в '{settings_file}' некорректный JSON: {e}", file=sys.stderr)
    sys.exit(1)
except OSError as e:
    print(f"Ошибка: не удалось прочитать '{settings_file}': {e}", file=sys.stderr)
    sys.exit(1)

if plugin_key in data.get('enabledPlugins', {}):
    del data['enabledPlugins'][plugin_key]

# Atomic write
try:
    tmp_fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(settings_file))
    with os.fdopen(tmp_fd, 'w') as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, settings_file)
except OSError as e:
    print(f"Ошибка: не удалось записать '{settings_file}': {e}", file=sys.stderr)
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    sys.exit(1)
PYEOF
    ok "Плагин удалён из settings.json"
else
    info "settings.json не найден (отключать нечего)"
fi

printf "\n${GREEN}${BOLD}Alfred Dev удалён${NC}\n"
printf "  ${DIM}Перезапусти Claude Code, чтобы применить изменения.${NC}\n\n"
