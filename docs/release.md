# Релиз и аудит (0.7.0)

Эта страница заменяет фиксированные матрицы 0.6.0. Она описывает, как Alfred Dev
публикуется **сейчас**: реальный инвентарь, команды аудита и проверка человеком.
Она не замораживает хеши и счётчики старого релиза. Официальная документация
перепроверена 2026-08-15.

Текущий публичный инвентарь: **10 агентов**, **11 skills**, **18 команд**
с namespace, **10 хуков**. `plugin.json` служит каноничным источником `version`.
`marketplace.json` не дублирует это поле. `displayName: "Alfred Dev"` это
человекочитаемое имя; технический namespace: `alfred-dev`.

Глобального алиаса `/alfred` нет. Точка входа: `/alfred-dev:alfred`. Установщик
не трогает `~/.claude/skills` и не создаёт `~/.claude/commands/alfred.md`.

---

## Поверхность, которую нужно выровнять

Перед публикацией эти поверхности должны говорить одно и то же:

- `.claude-plugin/plugin.json` (18 опубликованных команд)
- `commands/` (плюс внутренние `_composition.md`, `_living_docs.md`, `next.md`, `search.md`)
- `agents/` (10 карточек)
- `skills/*/SKILL.md` (11 плоских)
- `hooks/hooks.json` (10 скриптов)
- `README.md`, `docs/architecture.md`, `docs/commands.md`, `docs/skills.md`
- `package.json` (скрипты аудита)

Процессы загружают `_composition.md` и `_living_docs.md` из установки плагина,
а не из проверяемого проекта.

Claude Code описывает commands/ как поддерживаемые плоские skills и рекомендует
`skills/` для новых плагинов. Alfred сохраняет `commands/` ради публичного UX
`/alfred-dev:*`. Frontmatter команд уже, чем у skills:
`description`, `argument-hint`, `allowed-tools`, `disallowed-tools`, `model`.
`argument-hint` идёт вместе с `$ARGUMENTS`. `model` проверяется по актуальным
алиасам и ID. Правила инструментов используют официальные имена, как inline,
так и списком YAML.

Каждый `SKILL.md` объявляет `name`, совпадающий с каталогом, `description` +
`when_to_use` в пределах лимита листинга 1536 символов и
`disable-model-invocation: true` в skills с побочными эффектами
(style-direction, sonarqube, incident-response, pr-workflow).

---

## Команды аудита

| Gate | Команда | Что проверяет |
|------|---------|---------------|
| Локальный набор тестов | `python3 -m pytest tests/ -q` | Ядро, хуки, MCP, установщики, контракты |
| Базовый аудит | `npm run release:audit` | Инвентарь 0.7.0, манифесты, frontmatter, упаковка |
| Полный аудит | `npm run release:audit:full` | База + непрерывность + MCP + внешние контракты без побочных эффектов |
| Preflight Claude | `npm run release:audit:manual:preflight` | Auth и CLI (`auth_preflight.status=ok`) |
| Ручное подтверждение | `npm run release:audit:manual:evidence` | Матрица worktree (`scripts/manual_smoke.py`) |
| Подтверждение установки | `npm run release:audit:manual:evidence:installed` | Та же матрица против кэша user |
| Проверка человеком | `npm run release:audit:manual:review` | Шаблон одобрен, датирован, с заметками |
| Prepublish | `npm run release:audit:prepublish` | Full + preflight + reviews; подтверждения не перегенерирует |

Ручная матрица покрывает **18 публичных маршрутов**, **40 публичных опций** и
**4 runtime-контракта** для `/update`. ID опций проверяются по опубликованным
командам. У каждого `argument-hint` есть покрытая опция. Скрипты
подтверждений запускают `--auth-preflight`. Превью очищаются через
`core/secrets.py`. Подтверждения и шаблоны записываются с правами `0600` и
игнорируются git и npm (`docs/manual-smoke*.json`,
`docs/manual-smoke*.md`).

Gate проверки требует `evidence_file`, `evidence_sha256` и
`plugin_surface.sha256` этого запуска (а не хеш, замороженный в этом документе).
Он отклоняет старые подтверждения (`--require-current-auth-preflight`), секреты,
шаблонные заметки (`notes_low_quality`) и повторяющиеся (`notes_repeated`). Он не
создаёт шаблон из загрязнённого подтверждения. Сам по себе не одобряет релиз:
нужен `approved=true` от человека.

Что не покрывает локальный контракт (остаётся проверкой человеком или
реальным окружением): GitHub Sync через `gh`, SonarQube/Docker, CTO против Greptile
CLI. Внешний preflight (`npm run release:audit:external:preflight`,
`scripts/external_live_smoke.py`) не создаёт issues, не запускает контейнеры и
не запускает `greptile review`.

---

## Claims, которые локальный аудит покрывает

- quality gates проверяемы по локальному контракту
- Публикуемый пакет без реальных секретов (`core/secrets.py`)
- Модели и цвета агентов с актуальными значениями Claude Code
- Инструменты агентов с официальными именами; нет `AskUserQuestion` в субагентах
- `_composition.md` входит в пакет, но не публикуется
- Определение стека: Node/TypeScript, Python, Rust, Go, Ruby, Elixir, Java/Kotlin, PHP, C#/.NET и Swift
- Условный Designer
- Европейский compliance GDPR (RGPD)/NIS2/CRA
- AskUserQuestion с `questions[]` и `multiSelect`
- Хуки: `decision`, `hookSpecificOutput.hookEventName`,
  `hookSpecificOutput.additionalContext` и `systemMessage`. `matcher` не
  объявляется в событиях, где Claude Code его игнорирует.

---

## Runbook для человека (критерии и блокировки)

Проверяющий не утверждает, что запускал тесты, развёртывания, SonarQube, GitHub Sync,
Docker или Greptile, если нет подтверждения. Он просит решения человека. Он не одобряет
сам себе UAT, развёртывания, безопасность и аудиты. Он не фильтрует секреты вручную:
gate использует `core/secrets.py`.

Типичные блокировки: `blocked_auth`, `first_party_oauth_token_rejected`, пустые
заметки, поверхность плагина различается между worktree и установкой, матрица
не согласована с `command_coverage` / `option_coverage` / `runtime_coverage`.

Если auth падает: `claude auth logout`, `claude auth login`, `claude doctor`.
Диагностика: `npm run release:audit:manual:auth:diagnose`
(`scripts/claude_auth_recovery.py`).
