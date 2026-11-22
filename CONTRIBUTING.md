# Руководство по участию

Alfred Dev это плагин Claude Code: 10 агентов, 11 плоских skills, 19 опубликованных команд, хуки и ядро на Python. Это руководство кратко описывает, как внести вклад. Подробности работы описаны в [docs/contributing.md](docs/contributing.md).

## Требования

- Python 3.10 или новее.
- Установленный и настроенный Claude Code.
- git.

Рантайм Python использует стандартную библиотеку. `requirements.txt` объявляет FastMCP (`mcp`) как необязательную зависимость сервера памяти.

## Поверхность 0.7.0

```
alfred-dev/
  .claude-plugin/         # plugin.json (19 команд) и marketplace.json
  agents/                 # 10 агентов (8 базовых + Designer + CTO)
  commands/               # 19 slash-команд /alfred-dev:* + внутренние helpers
  skills/                 # 11 плоских skills (SKILL.md)
  hooks/                  # 10 скриптов жизненного цикла + hooks.json
  core/                   # Движок оркестрации, памяти и отчётов
  mcp/                    # MCP-сервер stdio (постоянная память)
  templates/              # 8 шаблонов артефактов
  tests/                  # Тесты и контракты релиза (pytest)
```

Публичная точка входа: `/alfred-dev:alfred`. Глобального алиаса `/alfred` нет.

## Как проверить

```bash
python3 -m pytest tests/ -q
python3 scripts/release_audit.py
```

Если изменение затрагивает публичную поверхность, проверь также `README.md`, `docs/` и контрактные тесты (`test_public_surface_contract.py`, `test_version_consistency.py`).

## Как добавить компонент

- **Агент:** `agents/<имя>.md` с frontmatter (`name`, `description`, `model: inherit`, `tools`). Claude Code находит агентов в `agents/`. Регистрировать их в `plugin.json` не нужно.
- **Skill:** `skills/<имя>/SKILL.md` с совпадающим `name`. Если у skill есть побочные эффекты, добавь `disable-model-invocation: true`.
- **Опубликованная команда:** `commands/<имя>.md`, затем добавь её в `.claude-plugin/plugin.json`.
- **Хук:** скрипт в `hooks/` и регистрация в `hooks/hooks.json` (`command` + `args`). Тесты в `tests/test_<имя>.py`.

Подробнее: [docs/contributing.md](docs/contributing.md), [docs/release.md](docs/release.md).
