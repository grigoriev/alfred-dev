---
description: "Внутренний протокол живой документации: какой файл обновляется на каждом gate."
---

# Живая документация проекта

Общий протокол. Его читают `feature`, `fix`, `quick`, `spike`, `audit`, `ship`,
`map-codebase` и `discuss`. Это не slash-команда.

## Шаг 0 -- скелет

Перед первой фазой (или при составлении карты / обсуждении) выполни:

```bash
python3 .claude/alfred-continuity.py sync-project-docs "$PWD"
```

Это создаёт, если их нет:

- `docs/project/README.md` (индекс)
- `docs/project/architecture.md`
- `docs/project/compliance.md`
- `docs/project/threat-model.md`
- `docs/project/dependencies.md`
- `docs/adr/`

Прозу он не заполняет. Скелеты содержат `<!-- alfred-doc:scaffold -->`.

## Что трогать в каждый момент

Обновляй только то, что изменила фаза. Остальное не переписывай.

| Момент | Кто | Файлы |
|--------|-----|-------|
| `discuss` | Alfred | индекс (существует) + `discovery.md` |
| `map-codebase` | helper + Alfred | индекс + скелет архитектуры |
| Продукт утверждён | product-owner | PRD; индекс обновляется |
| Архитектура | architect + security-officer | `architecture.md` (заполнен), ADR при наличии решения, `threat-model.md` (заполнен) |
| Новая зависимость | architect или security-officer | `dependencies.md` |
| Разработка / quick / fix | tech-writer (короткий sync) + senior-dev | индекс; заголовки/docstrings затронутого кода; `current.md` |
| Качество / audit | security-officer | `compliance.md` с подтверждением |
| Закрывающая документация / ship | tech-writer | индекс, CHANGELOG, release notes |
| Пауза | helper | handoff (без изменения architecture/compliance) |

## Перед закрытием gate

```bash
python3 .claude/alfred-continuity.py check-project-docs "$PWD" --command <comando> --phase <fase>
```

Если helper завершается с ненулевым кодом, gate не считается пройденным. Заполни
пробел и проверь снова.

Документ считается заполненным, когда в нём есть `<!-- alfred-doc:filled -->` или
когда он уже существовал с реальным содержимым (без маркера скелета).

## ADR

Если фаза архитектуры (или spike) принимает новое решение:

```bash
python3 .claude/alfred-continuity.py next-adr "$PWD" --title "Короткое название решения"
```

Затем architect заполняет файл с помощью skill `write-adr`.

## Skills

- `sync-project-docs` -- как синхронизировать, не выдумывая прозу
- `write-adr` -- как закрыть ADR
- `evaluate-dependency` -- как отметить зависимость
- `compliance-check` -- как заполнить реестр
- `threat-model` -- как заполнить модель

## Tech Writer

После каждой фазы (не только в конце) запускай короткий sync от `tech-writer`:

1. `sync-project-docs`
2. обновить только затронутые секции
3. `check-project-docs` текущей фазы

В `quick` и `fix` sync минимальный: индекс + заметка в `current.md`. ADR
только если изменение сдвигает границу архитектуры.
