---
description: "Запускает SonIA Sync: отражает локальную доску в GitHub Issues через gh CLI"
argument-hint: "[необязательный owner/repo]"
disable-model-invocation: true
allowed-tools: Bash(python3 .claude/alfred-continuity.py *), Bash(gh *), Read, Write
---

# /alfred-dev:sync-github

Ты Alfred. Твоя задача здесь: выполнить **SonIA Sync**, то есть опубликовать
операционное состояние SonIA в GitHub Issues, не потеряв локальный источник
истины проекта.

Необязательный репозиторий: $ARGUMENTS

## Цель

Синхронизировать задачи локального kanban с GitHub и обновить:

- `.claude/alfred-github-sync.json`
- `docs/project/github-sync.md`

## Протокол

Немедленно выполни детерминированный helper:

```bash
python3 .claude/alfred-continuity.py sync-github "$PWD" --raw "$ARGUMENTS"
```

Если helper возвращает валидный вывод:

- используй его как итоговый ответ и закончи;
- считай, что он уже записал `.claude/alfred-github-sync.json` и `docs/project/github-sync.md`;
- допускай, что он также мог убрать ранее синхронизированные issues Alfred, если их больше нет в локальной SonIA;
- оставляй видимыми `focus`, `source`, `command`, `directive` и `reason`, если helper их показывает;
- в `claude -p` или headless-аудите держи завершение короче 12 строк;
- не добавляй блоки `Insight`, таблицы, педагогические объяснения или дополнительное чтение;
- не продолжай исследование, не повторяй sync вручную и не добавляй второе повествование поверх сводки helper-а.

Только если helper падает или `gh` не готов, переходи в ручной режим. В ручном:

1. проверь `gh --version` и `gh auth status`;
2. определи репозиторий по `origin` или используй `$ARGUMENTS`, если там `owner/repo`;
3. прочитай `docs/project/kanban/backlog.md`, `in-progress.md`, `done.md`, `blocked.md`;
4. используй GitHub Issues как совместное зеркало SonIA Sync, а не как основной источник истины.

## Правила

- НЕ используй `AskUserQuestion` по умолчанию.
- Если нет `gh` или аутентификации, сообщи об этом ясно и не имитируй sync.
- Не удаляй issues, не относящиеся к Alfred.
- Если задачи Alfred больше нет на локальной доске, удалённое зеркало должно убрать или закрыть её, не трогая чужие issues.
- Сохраняй локальную истину в `docs/project/` и `.claude/`.
