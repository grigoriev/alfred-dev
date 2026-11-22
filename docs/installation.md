# Установка и цепочка загрузки

Alfred Dev больше не устанавливает плагин копированием репозиториев и ручной
правкой внутренних JSON Claude Code. Текущий процесс поручает установку нативной
CLI Claude Code и добавляет только слой проверки и патчей там, где плагину это
действительно нужно: обнаружение Python 3.10+ и правка `hooks.json`
и `.mcp.json`, когда системный `python3` не подходит. Он не перезаписывает
`~/.claude/skills` и не создаёт `~/.claude/commands/alfred.md`. Точка входа:
`/alfred-dev:alfred`.

Это важно, потому что цепочка загрузки по-прежнему существует, но за её
создание отвечает уже не самодельный скрипт плагина, а `claude plugin
marketplace add` и `claude plugin install`. Установщики Alfred Dev только
готовят окружение, просят Claude Code глобально зарегистрировать
GitHub-источник плагина и устанавливают новую версию.

Важно: здесь `marketplace` это имя подкоманды Claude Code, а не
официальный магазин плагинов. Alfred Dev независимый и неофициальный плагин.
Он не использует официальный marketplace Anthropic; он регистрирует собственный
GitHub-источник через нативную CLI Claude Code.
Команда:

```bash
claude plugin marketplace add grigoriev/alfred-dev --scope user
```

говорит Claude Code зарегистрировать **собственный GitHub-источник** в
`known_marketplaces.json` глобально для этого пользователя, чтобы
первая установка и последующие обновления использовали один и тот же источник.
Публичный установщик явно задаёт `--scope user`, чтобы не зависеть от
значения CLI по умолчанию. Перед переустановкой он сначала удаляет любые следы `local` или `project` Alfred Dev в текущем контексте, а затем оставляет активной только глобальную пользовательскую установку.

---

## Пять звеньев цепочки загрузки

Чтобы загрузить плагин, Claude Code по-прежнему нужны те же пять звеньев:

1. глобальная регистрация GitHub-источника;
2. локальная копия источника;
3. рабочий кэш плагина;
4. запись об установке;
5. включение в `settings.json`.

Разница в том, что Alfred Dev **больше не управляет ими по одному**.
Их создают команды Claude Code:

```bash
claude plugin marketplace add grigoriev/alfred-dev --scope user
claude plugin install alfred-dev@alfred-dev --scope user
```

Если одно из этих звеньев сломано, плагин может молча не
загружаться, но контракт текущего установщика такой:

- проверить минимальные локальные требования;
- зарегистрировать или обновить глобальный GitHub-источник Alfred Dev;
- переустановить или обновить плагин через нативную CLI;
- не перезаписывать `~/.claude/skills` и не создавать `~/.claude/skills/alfred/SKILL.md`;
- не создавать `~/.claude/commands/alfred.md`;
- при необходимости пропатчить установку, чтобы использовать совместимый Python;
- напомнить, что `/reload-plugins` применяет изменения в текущей сессии, а
  перезапуск Claude Code служит fallback, если этого требует MCP/кэш или плагин
  не появляется.

### Сводка пяти звеньев

| # | Звено | Расположение | Кто его теперь обновляет |
|---|---------|-----------|--------------------------|
| 1 | Глобальная регистрация источника | `known_marketplaces.json` | `claude plugin marketplace add/remove` |
| 2 | Локальная копия источника | `~/.claude/plugins/marketplaces/alfred-dev/` | `claude plugin marketplace add` |
| 3 | Кэш плагина | `~/.claude/plugins/cache/alfred-dev/alfred-dev/<version>/` | `claude plugin install` |
| 4 | Запись об установке | `installed_plugins.json` | `claude plugin install/uninstall` |
| 5 | Включение | `settings.json > enabledPlugins` | `claude plugin install/uninstall` |

Короткого алиаса нет. Точка входа: `/alfred-dev:alfred`. Установщик не
пишет `~/.claude/skills/alfred/SKILL.md` и `~/.claude/commands/alfred.md`.
Если остался shim от установок 0.6, деинсталлятор может его удалить;
установщик его не создаёт заново.

---

## Диаграмма процесса установки

Реальный текущий процесс такой:

```mermaid
sequenceDiagram
    box rgb(40, 40, 50) Скрипт установки
        participant S as "install.sh / install.ps1"
    end
    box rgb(30, 60, 80) Локальное окружение
        participant U as "Пользователь / shell"
        participant C as "Claude CLI"
    end
    box rgb(50, 40, 60) Локальные файлы
        participant P as "~/.claude/plugins/"
        participant A as "~/.claude/skills/ (не трогается)"
    end

    U->>S: Запустить удалённый установщик
    S->>S: Проверить Claude Code, HOME/USERPROFILE и Python 3.10+
    S->>C: claude plugin uninstall alfred-dev@alfred-dev --scope local
    S->>C: claude plugin uninstall alfred-dev@alfred-dev --scope project
    S->>C: claude plugin marketplace remove alfred-dev --scope user (если есть)
    S->>C: claude plugin marketplace add grigoriev/alfred-dev --scope user
    C-->>P: Зарегистрировать глобальный источник в known_marketplaces.json
    S->>C: claude plugin install alfred-dev@alfred-dev --scope user
    C-->>P: Обновить cache + installed_plugins + enabledPlugins
    S->>A: Не перезаписывает ~/.claude/skills и не создаёт алиас /alfred
    S->>P: Пропатчить hooks.json / .mcp.json, если python3 не подходит
    S-->>U: Выполни /reload-plugins; перезапусти, если этого требует MCP/кэш
```

---

## Скрипт установки для macOS и Linux

**Файл:** `install.sh`

**Использование:**

```bash
curl -fsSL https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/install.sh | bash
```

Если репозиторий уже клонирован или скачан локально, можно запустить тот же
установщик прямо из этой копии:

```bash
bash ./install.sh
```

Скрипт идемпотентен: если предыдущая установка уже есть, он её обновляет,
а не требует ручного удаления.

### Что он проверяет

Прежде чем трогать установку, скрипт проверяет:

1. что есть корректный `HOME`;
2. что есть `~/.claude/`;
3. что команда `claude` доступна;
4. что есть Python **3.10 или новее**.

Поиск Python не ограничивается `python3`: он также пробует варианты вроде
`python3.13`, `python3.12`, `python3.11` или `python3.10`, а на macOS проверяет
обычные пути Homebrew (`/opt/homebrew/bin`, `/usr/local/bin`), если
интерпретатор из PATH слишком старый.

### Что он делает на самом деле

После проверки окружения:

1. удаляет унаследованные установки через
   `claude plugin uninstall alfred-dev@alfred-dev --scope local` и
   `claude plugin uninstall alfred-dev@alfred-dev --scope project`;
2. удаляет унаследованные источники через
   `claude plugin marketplace remove alfred-dev --scope local` и
   `claude plugin marketplace remove alfred-dev --scope project`;
3. удаляет предыдущий экземпляр плагина `user`, если он ещё зарегистрирован;
4. удаляет предыдущую регистрацию `user` Alfred Dev, если она есть;
5. выполняет `claude plugin marketplace add grigoriev/alfred-dev --scope user`;
6. подтверждает, что Claude Code зарегистрировал GitHub-источник в `known_marketplaces.json`;
7. выполняет `claude plugin install alfred-dev@alfred-dev --scope user`;
8. не перезаписывает `~/.claude/skills` и не создаёт ни `~/.claude/skills/alfred/SKILL.md`, ни
   `~/.claude/commands/alfred.md`;
9. если `python3` по умолчанию не подходит, но есть другой совместимый
   Python, патчит установку, чтобы hooks и MCP использовали этот путь.

Публичный установщик приводит установку к **глобальной пользовательской**
(`--scope user`). Если он находит унаследованные следы Alfred Dev в `local` или
`project`, он сначала удаляет их, а затем переустанавливает по глобальному пути. Даже
при аудите локальной копии worktree источник нужно регистрировать через
`claude plugin marketplace add "$PWD" --scope user`, а установку
выполнять через `claude plugin install alfred-dev@alfred-dev --scope user`; `--scope local` не поддерживается как путь установки. Эти прямые
команды тоже не создают `~/.claude/skills/alfred/SKILL.md` и
`~/.claude/commands/alfred.md`. Если
`/alfred-dev:update` находит унаследованную
установку `local` или `project`, он предупреждает и превращает её в глобальную
пользовательскую установку, а не сохраняет этот scope.
Иначе говоря, поддерживаемая обычная установка всегда
глобальная пользовательская.

Если в `~/.claude/plugins/cache/alfred-dev/` одновременно лежат несколько версий плагина,
установщик детерминированно патчит активную установку: сначала
точный путь `cache/alfred-dev/alfred-dev/<version>`, а если такой структуры
нет, то самую свежую версию, чей `plugin.json` объявляет ту же
версию, которую установщик только что развернул.

### Патч совместимого Python

Установщик не пересобирает и не переделывает плагин. Он обновляет только две точки
установленного runtime, когда `python3` не указывает на подходящую версию:

- `hooks/hooks.json`: заменяет `command` у Python-хуков на абсолютный путь
  совместимого интерпретатора и сохраняет `args` с
  `${CLAUDE_PLUGIN_ROOT}`;
- `.mcp.json`: заменяет `command` сервера
  `alfred-memory`.

Этот патч особенно важен на macOS, где `/usr/bin/python3` может
оставаться 3.9, даже если у пользователя через Homebrew или pyenv установлен 3.12+.

### Заметка для локальной разработки плагина

Alfred Dev объявляет свой сервер памяти в `.mcp.json`, потому что Claude Code
находит MCP плагина в корне плагина. Если запустить
`claude mcp list` внутри самого репозитория Alfred Dev, Claude
Code также читает тот же `.mcp.json` как MCP-конфигурацию
проекта и может показать вторую запись `alfred-memory` в состоянии
`Pending approval`.

Одобрять эту проектную запись для проверки плагина не нужно. Канонический
сигнал: запись с префиксом плагина:

```bash
claude mcp get plugin:alfred-dev:alfred-memory
```

Она должна показывать `Status: ✔ Connected`. В глобальной пользовательской установке
`--scope user` команда `claude mcp list` из другого каталога показывает список без
проектного дубликата. Во время аудита worktree тоже регистрируй
локальный источник с `--scope user`; так `/alfred-dev:*` остаётся
доступным вне репозитория.

---

## Скрипт установки для Windows

**Файл:** `install.ps1`

**Использование (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/install.ps1 | iex
```

Подход тот же, что в Bash: реальную установку выполняет CLI Claude Code,
а скрипт добавляет надёжное обнаружение Python и патч runtime.

### Отличия от bash-скрипта

| Аспект | Bash (`install.sh`) | PowerShell (`install.ps1`) |
|---------|---------------------|---------------------------|
| Базовый путь | `$HOME/.claude` | `$env:USERPROFILE\\.claude` |
| Поиск Python | `python3`, `python3.13`... + пути Homebrew | `py -3.13`, `py -3.12`, `py -3.11`, `py -3.10`, `python3`, `python` |
| Проверка Claude | `command -v claude` | `Get-Command claude` |
| Вспомогательная запись | `sed` + прямая запись | `ConvertFrom-Json` / `ConvertTo-Json` + `Write-TextFileAtomic` |
| Патч runtime | текстовая замена в JSON | структурированное изменение JSON |

На Windows Python 3.10+ тоже обязателен, потому что hooks, core и MCP
и там работают на Python. Установщик сначала пробует launcher
`py`, затем `python3` или `python` и обновляет `hooks.json` и `.mcp.json`,
чтобы использовать точный путь найденного интерпретатора.

---

## Удаление

Скрипты удаления (`uninstall.sh` для macOS/Linux, `uninstall.ps1`
для Windows) следуют тому же подходу, что и установка: сначала они пытаются
использовать нативную CLI Claude Code, а затем убирают физические остатки или записи,
если что-то осталось.

**macOS / Linux:**

```bash
curl -fsSL https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/uninstall.sh | bash
```

Из локальной копии репозитория:

```bash
bash ./uninstall.sh
```

**Windows (PowerShell):**

```powershell
irm https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/uninstall.ps1 | iex
```

### Что удаляется

Текущий процесс удаления:

1. `claude plugin uninstall alfred-dev@alfred-dev --scope user`, если CLI доступна;
2. `claude plugin marketplace remove alfred-dev --scope user`, если CLI доступна;
3. удаление остатков в `cache/alfred-dev/` и `marketplaces/alfred-dev/`;
4. очистка оставшихся записей в `known_marketplaces.json`,
   `installed_plugins.json` и `settings.json`, если они ещё есть.

Процесс удаления трогает только компоненты плагина в `~/.claude/plugins/` и `~/.claude/settings.json`. Таблица ниже описывает каждую операцию в порядке выполнения:

| Порядок | Операция | Описание |
|-------|-----------|-------------|
| 1 | Удалить cache | Удаляет `~/.claude/plugins/cache/alfred-dev/` со всеми версиями |
| 2 | Удалить каталог marketplace | Удаляет `~/.claude/plugins/marketplaces/alfred-dev/` |
| 3 | Очистить `known_marketplaces.json` | Удаляет запись `alfred-dev` из карты известных marketplaces |
| 4 | Очистить `installed_plugins.json` | Удаляет запись `alfred-dev@alfred-dev` из реестра плагинов |
| 5 | Очистить `settings.json` | Удаляет ключ `alfred-dev@alfred-dev` из `enabledPlugins` |

Ручная очистка JSON остаётся страховкой для старых
установок, промежуточных состояний или остатков, которые CLI не удалила.

### Что не удаляется

Скрипты удаления не трогают локальные файлы конфигурации проекта. Это сделано намеренно: если пользователь позже переустановит плагин, конфигурация проекта сохранится. Остаются такие файлы:

- `.claude/alfred-dev.local.md` -- локальная конфигурация проекта
- `.claude/alfred-dev-state.json` -- постоянное состояние плагина

Для полной очистки эти файлы нужно удалить вручную в каждом проекте, где использовался Alfred Dev.

После удаления выполни `/reload-plugins` в открытых сессиях,
чтобы выгрузить поверхность плагина. Если Claude Code предупреждает про MCP/кэш или
всё ещё показывает команды Alfred, закрой и снова открой Claude Code.

---

## Обновление

Обновлением управляет команда `/alfred-dev:update`. Она
проверяет, есть ли на GitHub более новая версия, и если есть, показывает
одно меню выбора, чтобы решить, применять её или нет. Прежде чем что-то применять,
она читает `claude plugin list --json`, чтобы узнать, установлен ли Alfred Dev как
`user`, `local`, `project` или `managed`.

### Как работает процесс

Процесс обновления состоит из четырёх шагов, которые команда выполняет интерактивно:

**Шаг 1 -- Получить установленную версию и scope.** Команда запрашивает
`claude plugin list --json` и извлекает `version`, `scope`, `installPath` и, если
есть, `projectPath` из записи `alfred-dev@alfred-dev`. Если CLI не
возвращает запись, в качестве fallback берётся самый свежий `plugin.json` в
`~/.claude/plugins/cache/alfred-dev/`, а scope помечается как неизвестный.

**Шаг 2 -- Запросить последний release на GitHub.** Команда отправляет запрос к API GitHub по адресу `https://api.github.com/repos/grigoriev/alfred-dev/releases/latest` и извлекает `tag_name` (версия), `name` (название release), `body` (заметки об изменениях) и дату публикации.

**Шаг 3 -- Сравнить версии.** `tag_name` (без префикса `v`) и установленную версию нужно сравнивать как настоящий semver, никогда как простой текст. `0.10.0` больше, чем `0.9.0`, хотя лексикографически кажется наоборот. Если release новее, команда показывает заметки и предлагает одно меню с двумя вариантами: обновить сейчас или отменить. Если версии совпадают, она сообщает, что плагин актуален, и завершается.

**Шаг 4 -- Выполнить обновление.** Если пользователь соглашается, команда использует
глобальный пользовательский путь, кроме установок `managed`:

- Для scope `user`, `local`, `project` или неизвестного она определяет платформу
  (`uname -s`) и запускает соответствующий установщик. Этот путь переустанавливает
  плагин через нативную CLI Claude Code с `--scope user`, сначала удаляет
  любые следы `local` или `project` Alfred Dev в текущем контексте,
  удаляет устаревший локальный checkout marketplace, если он есть, выполняет
  `claude plugin marketplace update alfred-dev`, если CLI это позволяет, и
  сохраняет патч совместимого Python для hooks и MCP. Она не создаёт заново
  `~/.claude/skills/alfred/SKILL.md` и алиас `/alfred`. Если остался shim
  0.6 в `~/.claude/commands/alfred.md`, деинсталлятор может его удалить. Если
  найденный scope был `local` или `project`,
  команда заранее это объясняет: обновление приводит установку к глобальной
  пользовательской.

- **macOS / Linux:** `curl -fsSL https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/install.sh | bash`
- **Windows:** `irm https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/install.ps1 | iex`

- Для scope `managed` она не пытается обновлять: сообщает, что установкой
  управляет политика администратора.

Установщики идемпотентны: они заново регистрируют marketplace,
обновляют локальный checkout marketplace, переустанавливают плагин через
нативную CLI Claude Code и сохраняют включение. Удалять плагин перед
обновлением в scope `user` не нужно.

После обновления пользователь должен выполнить `/reload-plugins`, чтобы загрузить
новую версию в текущей сессии. Если Claude Code предупреждает про MCP/кэш или
инвентарь не меняется, нужно перезапустить Claude Code.

---

## Решение проблем

Текущий Claude Code даёт полезную диагностику для плагинов, хотя некоторые
сбои установки всё ещё выглядят как «плагин не появляется», если смотреть только на
список команд. Прежде чем трогать внутренние файлы, сначала используй
официальную диагностику:

```bash
claude plugin list
claude plugin details alfred-dev@alfred-dev
claude plugin validate . --strict
claude --debug
```

Внутри интерактивной сессии `/plugin` показывает установленные плагины и
ставит вперёд те, у которых есть ошибки загрузки. `/plugin validate` проверяет manifest,
frontmatter skills/агентов/команд и `hooks/hooks.json`; `/reload-plugins`
перезагружает активную поверхность после установки, включения или отключения плагинов.
Если эта диагностика не объясняет проблему, проверь пять
звеньев цепочки загрузки.

### Claude Code не видит плагин

Это самая частая проблема, и почти всегда её причина: проваленная валидация,
сессия без перезагрузки плагинов или отсутствие одного из пяти звеньев. Самый
надёжный способ диагностики: сначала посмотреть `claude plugin list`,
`claude plugin details alfred-dev@alfred-dev` и `/plugin` внутри Claude Code.
Если инвентарь так и не объясняет сбой, проверь каждое звено по порядку:

```bash
# 1. Проверить, что marketplace зарегистрирован
python3 -c "import json; print(json.dumps(json.load(open('$HOME/.claude/plugins/known_marketplaces.json')), indent=2))"

# 2. Проверить, что каталог marketplace существует и содержит каталог плагинов
ls -la ~/.claude/plugins/marketplaces/alfred-dev/.claude-plugin/

# 3. Проверить, что кэш существует и содержит plugin.json
ls -la ~/.claude/plugins/cache/alfred-dev/alfred-dev/*/.claude-plugin/

# 4. Проверить запись об установке
python3 -c "import json; d=json.load(open('$HOME/.claude/plugins/installed_plugins.json')); print(json.dumps(d.get('plugins',{}).get('alfred-dev@alfred-dev','НЕ НАЙДЕНО'), indent=2))"

# 5. Проверить включение
python3 -c "import json; d=json.load(open('$HOME/.claude/settings.json')); print(d.get('enabledPlugins',{}).get('alfred-dev@alfred-dev','НЕ ВКЛЮЧЁН'))"
```

Если одна из этих команд возвращает неожиданный результат, это и есть сломанное
звено. Самое прямое решение обычно: переустановить плагин, снова запустив
скрипт установки. Если `claude plugin validate . --strict` падает в
checkout плагина, сначала исправь manifest, frontmatter или `hooks.json`,
на которые указывает CLI.

### Ошибка «marketplace не зарегистрирован»

Если в `known_marketplaces.json` нет записи `alfred-dev`, Claude Code не знает, где искать плагин. Так бывает, если файл был сброшен или другой инструмент его перезаписал. Решение: снова запустить установщик, он идемпотентно регистрирует marketplace.

### Обновление пишет "Successfully installed", но версия осталась старой

Обычно это значит, что `~/.claude/plugins/marketplaces/alfred-dev` был
устаревшим локальным клоном. Claude Code может успешно установить плагин из этого клона,
но если клон остался на старом release, полученный кэш тоже будет
старым. Начиная с `0.6.1` поддерживаемые установщики удаляют этот локальный checkout,
заново регистрируют GitHub-источник и выполняют `claude plugin marketplace
update alfred-dev` перед установкой.

Рекомендуемое восстановление: снова запустить установщик:

```bash
curl -fsSL https://raw.githubusercontent.com/grigoriev/alfred-dev/ru/install.sh | bash
```

Если нужно починить вручную, эквивалентный процесс такой:

```bash
claude plugin marketplace update alfred-dev
claude plugin update alfred-dev@alfred-dev
```

Затем проверь `installed_plugins.json` или `claude plugin list --json` и
выполни `/reload-plugins` или перезапусти Claude Code.

### Плагин не загружается после установки

Если плагин установлен, когда Claude Code уже работал,
сначала выполни `/reload-plugins`. Claude Code перезагружает активные плагины и
показывает обновлённый инвентарь плагинов, skills, агентов, hooks и MCP. Если
при перезагрузке есть предупреждение о стоимости/кэше MCP, используй `/reload-plugins --force`, только если
готов принять эту стоимость в следующем запросе; если не хочешь форсировать или плагин
так и не появился, полностью закрой Claude Code и открой его снова.

### Права на macOS

Если скрипты не запускаются, скорее всего, у них нет права на выполнение. Рекомендуемый способ (`curl | bash`) не требует особых прав для удалённого скрипта, но если файл скачан вручную, нужно убедиться, что у него подходящие права:

```bash
chmod +x install.sh
```

### Внутренний JSON-файл повреждён

Если какой-то внутренний файл Claude Code (`known_marketplaces.json`,
`installed_plugins.json`, `settings.json`) содержит невалидный JSON, может сломаться
и установка, и загрузка плагина. Текущий установщик не
восстанавливает эти файлы сам: обычно ты увидишь ошибку, пришедшую
из самой CLI Claude Code, или неполное состояние после `claude plugin
marketplace add` / `claude plugin install`.

Если подозреваешь повреждение этих файлов, восстановление по-прежнему ручное.
Например:

```bash
# Восстановить known_marketplaces.json
echo '{}' > ~/.claude/plugins/known_marketplaces.json

# Восстановить installed_plugins.json
echo '{"version":2,"plugins":{}}' > ~/.claude/plugins/installed_plugins.json
```

После восстановления файла можно снова запустить установщик, чтобы
CLI Claude Code заново создала записи плагина.

### Краткая сводка диагностики

| Симптом | Вероятная причина | Решение |
|---------|---------------|----------|
| Плагин не виден в Claude Code | Проваленная валидация, сессия без перезагрузки или нет какого-то звена | `claude plugin list/details`, `/plugin`, `/reload-plugins`, затем проверить 5 звеньев |
| `/alfred-dev:alfred` нет в меню | Плагин не включён, сессия без перезагрузки или marketplace stale | `claude plugin details alfred-dev@alfred-dev`, `/reload-plugins --force`; переустановить через `install.sh`, если кэш устарел |
| «marketplace не зарегистрирован» | В `known_marketplaces.json` нет записи | Переустановить через `install.sh` |
| Update пишет OK, но версия старая | Устаревший локальный checkout marketplace | Переустановить через `install.sh`; вручную: `claude plugin marketplace update alfred-dev` и `claude plugin update alfred-dev@alfred-dev` |
| Плагин установлен, но не появляется | Сессия без перезагрузки плагинов | Выполнить `/reload-plugins`; перезапустить, если этого требует MCP/кэш |
| Ошибка manifest/frontmatter/hooks | Несовместимая схема или синтаксис | `claude plugin validate . --strict` или `/plugin validate` |
| Скрипт не запускается на macOS | Нет права на выполнение | `chmod +x install.sh` |
| Ошибка невалидного JSON | Файл повреждён из-за прерывания | Восстановить файл и переустановить |
| Сетевой сбой при обновлении | Нет соединения или rate limit GitHub | Повторить позже |
