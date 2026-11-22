---
description: "Проверяет и применяет обновления плагина Alfred Dev"
disable-model-invocation: true
allowed-tools: Bash, Read
---

# /alfred-dev:update

Ты Alfred. Пользователь хочет проверить, есть ли новая версия плагина. Следуй этим шагам в точности.

## Шаг 1: получить установленную версию и scope

Сначала используй нативный CLI Claude Code, потому что это авторитетный источник
активных установок, scope и installPath:

```bash
claude plugin list --json
```

Найди запись `alfred-dev@alfred-dev`. Если их несколько, приоритет такой:

1. запись `enabled: true`, у которой `projectPath`, если он есть, совпадает с
   текущим проектом;
2. запись `enabled: true` без `projectPath` (установка `user`);
3. любая запись `alfred-dev@alfred-dev` в крайнем случае.

Извлеки:

- `version`
- `scope` (`user`, `local`, `project` или `managed`)
- `installPath`
- `projectPath`, если есть

Если `claude plugin list --json` падает или не возвращает запись, используй этот
fallback через cache для версии и пометь scope как `desconocido`:

```bash
python3 -c "
import json, os, glob, sys

candidates = sorted(
    glob.glob(os.path.expanduser('~/.claude/plugins/cache/alfred-dev/**/.claude-plugin/plugin.json'), recursive=True),
    key=os.path.getmtime,
    reverse=True
)
if not candidates:
    print('desconocida')
    sys.exit(0)
with open(candidates[0]) as f:
    print(json.load(f).get('version', 'desconocida'))
" 2>/dev/null || echo "desconocida"
```

Fallback выбирает самую свежую версию по дате изменения, чтобы
избежать ошибок, когда в cache сосуществуют несколько версий, но не используй его, чтобы
определять scope, если CLI всё же вернул его.

## Шаг 2: запросить последний релиз на GitHub

Выполни через Bash:

```bash
curl -s --max-time 10 "https://api.github.com/repos/grigoriev/alfred-dev/releases/latest"
```

Извлеки из JSON: `tag_name` (версия), `name` (название), `body` (заметки релиза), `published_at` (дата).

Если запрос не удался (нет сети, rate limit, timeout), сообщи об ошибке и предложи повторить позже. Дальше не продолжай. В частности:

- Если JSON содержит `"message": "API rate limit exceeded"`, сообщи пользователю, что он превысил лимит запросов GitHub и может повторить через несколько минут или передать токен через `-H "Authorization: token ..."`.
- Если curl возвращает код ошибки или timeout, покажи ошибку и предложи проверить соединение.
- Если JSON не содержит `tag_name`, это неожиданный ответ. Покажи сырое содержимое и прекрати.

## Шаг 3: сравнить версии

Проверь, что `tag_name` имеет валидный формат semver: он должен соответствовать шаблону `v?X.Y.Z(-ru)?`, где X, Y, Z это числа (например, `v0.3.0`, `0.3.0` или `v0.3.0-ru`). Суффикс `-ru` обозначает релиз русского форка, а не pre-release. Если не соответствует, покажи предупреждение и прекрати: формат релиза не тот, что ожидается.

Нормализуй `tag_name` (без начальной `v` и суффикса `-ru`) и установленную версию в числовые
кортежи `(major, minor, patch)` и сравни их как настоящий semver. **Никогда не**
сравнивай версии как простой текст (`0.10.0` больше, чем `0.9.0`).

Если нужно детерминированное сравнение, выполни через Bash:

```bash
python3 - <<'PY'
def parse(value):
    value = value.strip().lstrip('v').removesuffix('-ru')
    return tuple(int(part) for part in value.split('.'))

installed = "VERSION_INSTALADA"
latest = "TAG_NAME"

print(parse(latest) > parse(installed))
PY
```

Подставь `VERSION_INSTALADA` и `TAG_NAME` реальными значениями из шагов 1 и 2.

### Если есть новая версия

Покажи пользователю:
- Текущую установленную версию
- Доступную новую версию
- Заметки релиза, отформатированные в markdown

Затем используй **один `AskUserQuestion`** с настоящим выбираемым меню. Не
оставляй решение в свободном тексте. Два варианта должны быть:
- **"Обновить сейчас"** -- выполняет команду установки (шаг 4)
- **"Не сейчас"** -- отмена

### Если версия актуальна

Сообщи, что обновлений нет, и покажи текущую версию. Конец.

## Шаг 4: выполнить обновление

Если пользователь соглашается, всегда используй глобальный пользовательский путь, если только scope
не `managed`. Alfred Dev не сохраняет установки `local` и `project` при
обновлении из этой команды: он нормализует их в `--scope user`, чтобы
`/alfred-dev:*` работал в любом проекте пользователя. Он не пересоздаёт
глобальный алиас `/alfred` и не затрагивает `~/.claude/skills`.

### Scope user, local, project или desconocido

Для установок user, local, project или с неизвестным scope
используй поддерживаемый установщик Alfred Dev. Этот путь заново регистрирует
источник GitHub с `--scope user`, переустанавливает через нативный CLI Claude
Code, очищает/обновляет локальный checkout marketplace, чтобы избежать
устаревших cache, и не затрагивает `~/.claude/skills`. Он заново применяет совместимый
патч Python в `hooks.json` и `.mcp.json`, когда это нужно.

Если обнаруженный scope был `local` или `project`, скажи об этом перед выполнением: обновление
превратит эту установку в глобальную пользовательскую.
Не используй `claude plugin update --scope local` и `claude plugin update --scope project`.

Сначала определи платформу, затем выполни соответствующий установщик.

### Определение платформы

Выполни через Bash:

```bash
uname -s 2>/dev/null || echo "Windows"
```

- Если возвращает `Darwin` или `Linux`: это macOS или Linux, используй bash-установщик.
- Если падает или возвращает `Windows` / `MINGW` / `MSYS` / `CYGWIN`: это Windows, используй установщик PowerShell.

### macOS / Linux

```bash
curl -fsSL https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/install.sh | bash
```

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/install.ps1 | iex
```

### Scope managed

Если обнаруженный scope `managed`, не пытайся его обновлять. Объясни, что
managed-установками управляет политика администратора и что
пользователь должен запросить обновление у того, кто управляет Claude Code в его команде.

После завершения любого обновления сообщи пользователю, что нужно
выполнить **`/reload-plugins`** в Claude Code, чтобы загрузить новую версию в
текущую сессию. Если Claude Code предупреждает о MCP/cache, если решено не использовать
`/reload-plugins --force` или если инвентарь не меняется, нужно перезапустить
Claude Code.

## Примечания

- Установщики идемпотентны: они перезаписывают предыдущую установку без конфликтов.
- Не нужно сначала удалять в scope `user`.
- Не заменяй этот путь прямым `claude plugin update`, кроме ручного
  восстановления: установщик существует, чтобы избежать устаревших локальных marketplace.
- В scope `local` или `project` не сохраняй scope: преобразуй в глобальную
  пользовательскую установку установщиком. Не создавай `~/.claude/commands/alfred.md`
  и персональный skill `/alfred`. Точка входа это `/alfred-dev:alfred`.
- Если скрипт установки падает, покажи пользователю полную ошибку.
- В Windows также работает через WSL или Git Bash с bash-установщиком.

## Каноничное завершение команды

- Если новой версии нет, закрывай на этом: не предлагай дополнительных шагов или фиктивного решения.
- Если новая версия есть, используй одно настоящее выбираемое меню с двумя вариантами, определёнными выше, и не заменяй его свободным текстом.
- Если обновление выполнено успешно, завершение должно быть коротким и применимым: применённая версия, выполнить `/reload-plugins` и перезапускать только если MCP/cache этого требует или инвентарь не меняется.
