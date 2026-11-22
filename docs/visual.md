# Визуальный runtime Designer

`visual/` относится к плагину из ветки `main`. Это не публичный сайт
Alfred Dev; сайт живёт в ветке `Alfred-Astro`. Этот каталог содержит
локальный визуальный companion, который Designer использует в фазе `visual_style`
процесса `/alfred-dev:feature`, только если у проекта есть фронтенд.

Цель визуального runtime: вынести решение о визуальном направлении из
терминала на локальный экран. Designer создаёт HTML-предложения,
пользователь выбирает одно в браузере, сервер записывает клик, а затем
плагин пишет `docs/style-direction.md` как стабильный артефакт для architect и
senior-dev.

## Операционный процесс

1. Designer запускает `visual/scripts/start-server.sh --project-dir "$PWD"`.
2. Скрипт создаёт приватную сессию в `.alfred-dev/visual/<pid>-<timestamp>/`
   с двумя подкаталогами: `content/` и `state/`.
3. `visual/scripts/server.cjs` отдаёт самый свежий HTML из `content/` по
   локальному URL `http://127.0.0.1:<порт>`.
4. Генераторы на Python пишут экраны в `content/` и JSON-sidecars в
   `state/`.
5. Браузер записывает выбор через WebSocket или, если это не удалось, через `POST
   /events`.
6. `visual/scripts/read-choice.py` читает последний валидный выбор из
   `state/events`.
7. `visual/scripts/write-style-direction.py` создаёт `docs/style-direction.md`.
8. `visual/scripts/stop-server.sh <session_dir>` останавливает сервер и удаляет
   временные сессии в `/tmp`.

## Скрипты

| Скрипт | Назначение |
|---|---|
| `start-server.sh` | Запускает визуальный сервер в foreground или background и возвращает JSON с `url`, `session_dir`, `screen_dir` и `state_dir`. |
| `stop-server.sh` | Останавливает только ожидаемый визуальный процесс и не убивает чужие PID, если остался устаревший PID-файл. |
| `server.cjs` | HTTP + WebSocket сервер без внешних зависимостей. Отдаёт экраны, перезагружает страницу при изменении HTML и записывает события. |
| `helper.js` | Клиент, внедрённый в страницу: подключает WebSocket, ловит клики и использует HTTP fallback. |
| `frame-template.html` | Общая HTML-рамка для фрагментов, созданных Designer. |
| `write-style-demo-gallery.py` | Создаёт галерею базовых дизайн-систем, чтобы согласовать критерии. |
| `write-style-selector.py` | Создаёт управляемый экран выбора визуального семейства и второй экран с типографикой и палитрой. |
| `write-guided-style-options.py` | Создаёт три финальных варианта на основе управляемого выбора. |
| `write-style-options.py` | Создаёт экран с тремя предложениями из ручного sidecar. |
| `read-choice.py` | Читает последний валидный выбор, включая управляемые выборы. |
| `write-style-direction.py` | Пишет финальный артефакт `docs/style-direction.md`. |

## Контракт событий

Сервер сохраняет одно событие на строку в `state/events`. Каноничная форма:

```json
{
  "source": "user-event",
  "type": "click",
  "choice": "A",
  "label": "Тёплый редакционный",
  "element": ".style-option",
  "ts": "2026-06-20T15:00:00.000Z",
  "timestamp": "2026-06-20T15:00:00.000Z"
}
```

`choice` должен быть непустой строкой. `label` и `element` нормализуются с
ограничением размера, чтобы локальная страница не могла записать огромные или
некорректные события.

## Безопасность и ограничения

Сервер рассчитан на локальное и кратковременное использование, а не на роль публичного сервиса:

- по умолчанию слушает `127.0.0.1`;
- создаёт сессии с приватными правами через `umask 077`;
- ограничивает `POST /events` размером 64 KiB;
- проверяет `Sec-WebSocket-Version`, `Sec-WebSocket-Key`, `Upgrade` и `Connection`;
- принимает WebSocket только с ожидаемых loopback origins;
- отдаёт файлы из `content/` через `realpath`, чтобы блокировать path traversal и
  symlinks за пределы сессии;
- выставляет `Cache-Control: no-store`, `X-Content-Type-Options: nosniff` и
  `X-Frame-Options: DENY`;
- выключает сервер после 30 минут бездействия;
- останавливает процесс, если исчез процесс-владелец.

## Тесты

Основные контракты лежат в:

- `tests/test_visual_server.py`: жизненный цикл HTTP/WS, события, reload,
  path traversal и hardening.
- `tests/test_visual_scripts.py`: shell-обёртки, PID-файлы, права и безопасное
  завершение.
- `tests/test_visual_helper.py`: внедрённый клиент, очередь WebSocket и HTTP
  fallback.
- `tests/test_designer_style_*.py`: генераторы галереи, выбора, предложений,
  вариантов и артефакта `docs/style-direction.md`.

Перед публикацией релиза `scripts/release_audit.py` также проверяет, что
`npm pack --dry-run --json` включает `visual/scripts/`; если эти скрипты не попадают
в пакет, Designer сломан, даже если работает из worktree.
