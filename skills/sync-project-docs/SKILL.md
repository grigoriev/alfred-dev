---
name: sync-project-docs
description: "Использовать для синхронизации живой документации проекта после фазы. Также: обновить docs/project, индекс, architecture.md, compliance.md, threat-model."
---

# Синхронизация живой документации

## Резюме

После фазы обновляй только то, что изменилось. Helper создаёт скелеты
и проверяет gate. Содержимое пишешь ты.

## Процесс

1. Скелет и индекс:

   ```bash
   python3 .claude/alfred-continuity.py sync-project-docs "$PWD"
   ```

2. Прочитай `docs/project/README.md` и протокол `commands/_docs_vivas.md`.

3. Обновляй только файлы этой фазы. Если нового API не было, не
   трогай руководство по API. Если решения не было, не выдумывай ADR.

4. Когда в скелете появилось реальное содержимое, оставь `<!-- alfred-doc:filled -->`
   и убери `<!-- alfred-doc:scaffold -->`.

5. Проверь gate:

   ```bash
   python3 .claude/alfred-continuity.py check-project-docs "$PWD" --command <команда> --phase <фаза>
   ```

6. Если helper падает, не объявляй фазу закрытой.

## В quick и fix

Минимальная синхронизация: индекс + `docs/project/current.md`. ADR только если изменение сдвигает
границу (auth, хранение данных, интеграция).

## Критерии успеха

- Индекс отражает реальное состояние (`scaffold` или `filled`).
- Нет выдуманного текста о коде, которого не касались.
- `check-project-docs` завершается с кодом 0 до закрытия gate.

## Чего НЕ делать

- Не переписывай весь `docs/` в каждой фазе.
- Не копируй чат в Markdown.
- Не ставь `filled`, пока остаются `_(pendiente)_`.
