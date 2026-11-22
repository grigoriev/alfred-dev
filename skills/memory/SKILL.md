---
name: memory
description: This skill should be used when the user asks to record a design decision, search past project decisions, inspect the Alfred memory timeline, or work with the alfred-memory MCP server. Use it to call the namespaced MCP tools instead of inventing history.
---

# Постоянная память Alfred

Записывать и запрашивать решения проекта через MCP-сервер `alfred-memory`. Не выдумывать историю. Если инструмент недоступен, сказать об этом и не имитировать результаты.

## Реальные имена tools

Claude Code экспонирует tools плагина с MCP-префиксом. Использовать эти имена, а не короткие:

- `mcp__plugin_alfred-dev_alfred-memory__memory_search`
- `mcp__plugin_alfred-dev_alfred-memory__memory_get_decisions`
- `mcp__plugin_alfred-dev_alfred-memory__memory_get_iteration`
- `mcp__plugin_alfred-dev_alfred-memory__memory_get_timeline`
- `mcp__plugin_alfred-dev_alfred-memory__memory_stats`
- `mcp__plugin_alfred-dev_alfred-memory__memory_log_decision`
- `mcp__plugin_alfred-dev_alfred-memory__memory_update_decision`
- `mcp__plugin_alfred-dev_alfred-memory__memory_link_decisions`
- `mcp__plugin_alfred-dev_alfred-memory__memory_health`

Если runtime показывает другой префикс, использовать тот, что есть в списке tools, всегда от сервера `alfred-memory`.

## Что записывается, а что нет

Да: архитектурные и проектные решения, результаты gates, handoffs, UAT и коммиты, сделанные в сессии Alfred.

Нет: старая история Git, каждый Read/Glob/Grep, операционные советы и пустой kanban.

Вызывать `memory_log_decision` только при реальном выборе в дизайне, безопасности или поставке. Не регистрировать каждый edit. Если решение касается архитектуры или compliance, то человек читает живой Markdown (`docs/adr/`, `docs/project/compliance.md`); память его не заменяет.

Минимальные поля: заголовок, контекст, отброшенные альтернативы, обоснование, теги.

## Запрос

Для «почему мы решили X» или «что мы делали в прошлый раз»: `memory_search` или `memory_get_decisions` с термином и, если применимо, диапазоном или тегами.

Если записей нет, ответить, что записей нет. Не домысливать.

Агента `librarian` не существует. Этот skill и `/alfred-dev:memory-ui` это путь для обращения к истории.

## UI

Графическое представление: `/alfred-dev:memory-ui`. Этот skill не запускает HTTP-сервер. Чтобы закрыть его: `/alfred-dev:memory-ui stop`. При завершении сессии Claude он останавливается сам.
