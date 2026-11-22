---
name: style-direction
description: "Открыть и использовать визуальный companion Designer для выбора направления стиля в проектах с интерфейсом. Ручной skill: поднимает локальный сервер и пишет визуальные артефакты."
disable-model-invocation: true
---

# Руководство по визуальному серверу Designer

Локальный сервер в браузере для показа систем дизайна и визуальных вариантов
на фазе направления стиля. Работает как visual companion: показывает базовый
каталог Designer, позволяет пользователю зафиксировать семейство +
типографику + цветовую гамму, а затем закрыть финальный раунд из трёх колонок.

## Когда использовать визуальный сервер

Всегда, когда Designer генерирует варианты стиля. Сервер это главный инструмент
Designer: он служит и для показа галереи из 10 базовых систем дизайна, и
для нового guided-процесса выбора, и для финального раунда из 3 сопоставимых предложений.

## Запуск сессии

```bash
visual/scripts/start-server.sh --project-dir /путь/к/проекту
```

Ожидаемый JSON-ответ:

```json
{
  "type": "server-started",
  "port": 7432,
  "url": "http://localhost:7432",
  "screen_dir": "/путь/к/проекту/.alfred-dev/visual/<pid-timestamp>/content",
  "state_dir": "/путь/к/проекту/.alfred-dev/visual/<pid-timestamp>/state",
  "state": "ready"
}
```

Сохрани `screen_dir` (каталог, куда писать HTML с вариантами) и `state_dir`
(каталог, откуда читать события кликов и проверять состояние сервера).

Файл `state_dir/server-info` содержит тот же JSON, что был выдан при запуске.
Читай его, чтобы перед каждой операцией убедиться, что сервер ещё активен.

Попроси пользователя открыть URL в браузере.

## Цикл

1. Убедись, что сервер ещё активен, прочитав `STATE_DIR/server-info`.
2. Если это добавляет контекста, сначала сгенерируй галерею каталога командой `python3 visual/scripts/write-style-demo-gallery.py --visual-path "$STATE_DIR"`.
3. Рекомендуемый guided-процесс:
   - `python3 visual/scripts/write-style-selector.py --visual-path "$STATE_DIR"` для выбора базовой системы.
   - прочитай выбор командой `python3 visual/scripts/read-choice.py "$STATE_DIR"`.
   - `python3 visual/scripts/write-style-selector.py --visual-path "$STATE_DIR" --style-id "<style_id>"`, чтобы пользователь выбрал типографику + палитру.
   - снова прочитай выбор командой `python3 visual/scripts/read-choice.py "$STATE_DIR"`.
   - `python3 visual/scripts/write-guided-style-options.py --visual-path "$STATE_DIR"`, чтобы автоматически сгенерировать финальный раунд из 3 вариантов на основе этого выбора.
4. Альтернативный прямой процесс: если три предложения уже решены, сгенерируй `screen_dir/style-options.html` командой `python3 visual/scripts/write-style-options.py --visual-path "$STATE_DIR"`. Если нужно писать вручную, используй класс `.style-grid`.
5. Финальный JSON sidecar должен лежать в `screen_dir/style-options.json`, чтобы потом можно было сформировать итоговый артефакт без повторной интерпретации экрана.
6. Сообщи пользователю: напомни URL, кратко опиши, что показано, попроси выбрать один вариант.
7. В следующем ходе: прочитай финальный выбор командой `python3 visual/scripts/read-choice.py "$STATE_DIR"` или, если предпочитаешь, изучи `STATE_DIR/events` напрямую.
8. Сгенерируй `docs/style-direction.md` командой `python3 visual/scripts/write-style-direction.py --project-dir "$PWD" --visual-path "$STATE_DIR"` или, если нужен ручной контроль, напиши артефакт сам, используя JSON sidecar.
9. Запиши `waiting.html` в `screen_dir`, чтобы очистить браузер до следующего действия.

## Рекомендуемый JSON sidecar

Чтобы итоговый артефакт получился хорошего уровня, старайся, чтобы каждое предложение включало
как минимум:

- `choice`
- `name`
- `concept` или `description`
- `palette`
- `typography`
- `spacing_density` или `layout_density`
- `tone` или `mood`
- `sample_component` или `component_example`
- `visual_principles` или `design_principles`
- `layout_grammar` или `composition_grammar`
- `surface_treatment` или `materiality`
- `shape_language`
- `motion_language`
- `signature_elements` или `visual_motifs`
- `implementation_guardrails` или `guardrails`
- `prompt_seed` или `design_prompt`
- `rationale` или `why`
- `not_this_direction` или `anti_patterns`
- `context_signals`, `audience` или `constraints`

Канонический writer терпимо относится к неполным sidecar и разумным алиасам, но чем
конкретнее предложение, тем менее шаблонным будет итоговое направление.

### Критическое правило guided-процесса

Если пользователь уже зафиксировал **семейство + типографику + палитру**, три финальных варианта
должны по-прежнему принадлежать той же системе. Между `A / B / C` могут меняться
композиция, иерархия или степень выразительности, но не базовая грамматика
выбранной системы.

Когда генерируешь sidecar вручную:

- переиспользуй `prompt_seed` системы как основное зерно
- всегда переноси `visual_principles`, `layout_grammar` и `signature_elements`
- используй `implementation_guardrails`, чтобы вариант не уходил в другое семейство
- не смешивай отсылки к другому тренду только ради того, чтобы «сделать красивее»

## Канонический writer вариантов

Рекомендуемый helper:

```bash
python3 visual/scripts/write-style-options.py --visual-path "$STATE_DIR"
```

Этот скрипт:

- автоматически находит `style-options.json`
- нормализует распространённые алиасы sidecar
- пишет HTML-фрагмент, совместимый с реальным сервером
- не зависит от внешних ассетов, которых нет в репозитории

Если нужно настроить текст заголовка, он принимает `--title` и `--subtitle`.

## Guided-выбор системы + типографики + палитры

Designer теперь может работать в три естественных шага:

1. **Базовая система** - `python3 visual/scripts/write-style-selector.py --visual-path "$STATE_DIR"`
2. **Типографика + палитра** - `python3 visual/scripts/write-style-selector.py --visual-path "$STATE_DIR" --style-id "<style_id>"`
3. **Три финальных варианта** - `python3 visual/scripts/write-guided-style-options.py --visual-path "$STATE_DIR"`

`read-choice.py` по-прежнему остаётся каноническим читателем между шагами. Если выбор
относится к guided-процессу, он дополнительно вернёт `parsed_choice` с `stage`,
`style_id`, `font_pairing_id` и `palette_mode`.

## HTML-структура вариантов

Сервер сам оборачивает HTML-фрагменты в собственный фрейм и подключает `helper.js`,
поэтому не нужно писать полный документ или подключать дополнительные ассеты. Рекомендуемый
формат:

```html
<section class="style-screen">
  <div class="style-screen-header">
    <p class="style-screen-kicker">Designer предлагает</p>
    <h1>Выбери визуальное направление</h1>
    <p class="style-screen-subtitle">Выбери предложение, которое лучше всего подходит продукту.</p>
  </div>
  <div class="style-grid">

    <div class="style-option" data-choice="A">
      <div class="style-preview" style="background:#1a1a2e;">
        <span class="style-letter">A</span>
      </div>
      <div class="style-meta">
        <h2>Тёмный космос</h2>
        <p>Высокий контраст, sans-serif типографика, технологичное ощущение.</p>
        <div class="palette">
          <span class="swatch" style="background:#1a1a2e;" title="#1a1a2e"></span>
          <span class="swatch" style="background:#e94560;" title="#e94560"></span>
          <span class="swatch" style="background:#ffffff;" title="#ffffff"></span>
        </div>
      </div>
    </div>

    <div class="style-option" data-choice="B">
      <div class="style-preview" style="background:#f5f0e8;">
        <span class="style-letter">B</span>
      </div>
      <div class="style-meta">
        <h2>Тёплый editorial</h2>
        <p>Кремовые тона, классическая антиква, дух люксового журнала.</p>
        <div class="palette">
          <span class="swatch" style="background:#f5f0e8;" title="#f5f0e8"></span>
          <span class="swatch" style="background:#c8a96e;" title="#c8a96e"></span>
          <span class="swatch" style="background:#2c2c2c;" title="#2c2c2c"></span>
        </div>
      </div>
    </div>

    <div class="style-option" data-choice="C">
      <div class="style-preview" style="background:#0d7377;">
        <span class="style-letter">C</span>
      </div>
      <div class="style-meta">
        <h2>Яркий минимализм</h2>
        <p>Насыщенный сине-зелёный, много негативного пространства, узкий шрифт.</p>
        <div class="palette">
          <span class="swatch" style="background:#0d7377;" title="#0d7377"></span>
          <span class="swatch" style="background:#14ffec;" title="#14ffec"></span>
          <span class="swatch" style="background:#f8f8f8;" title="#f8f8f8"></span>
        </div>
      </div>
    </div>

  </div>
</section>
```

Каждый `.style-option` ОБЯЗАТЕЛЬНО должен содержать `data-choice` с уникальным идентификатором
(буква, число или slug). Именно этот атрибут записывается в события
при клике.

## Формат событий

Файл `STATE_DIR/events` содержит по одной JSON-строке на событие, в хронологическом порядке.
Актуальная каноническая форма:

```jsonl
{"source":"user-event","type":"click","choice":"A","label":"Oscuro espacial","element":".style-option","ts":"2026-03-31T10:14:02Z","timestamp":"2026-03-31T10:14:02Z"}
{"source":"user-event","type":"click","choice":"A","label":"Oscuro espacial","element":".style-option","ts":"2026-03-31T10:14:05Z","timestamp":"2026-03-31T10:14:05Z"}
```

Канонический читатель `visual/scripts/read-choice.py` также принимает прежний legacy-формат:

```jsonl
{"ts":"2026-03-31T10:14:02Z","type":"click","choice":"A","element":".style-option"}
{"ts":"2026-03-31T10:14:05Z","type":"click","choice":"A","element":".style-option"}
```

Последний клик с `type: "click"` по `.style-option` считается окончательным выбором
пользователя. Несколько кликов по одному и тому же варианту трактуются как
подтверждение. Если клики были по разным вариантам, побеждает самый поздний.

## Остановка сервера

```bash
visual/scripts/stop-server.sh <session_dir>
```

`session_dir` это каталог сессии, возвращённый `start-server.sh`, либо общий
родитель `screen_dir` и `state_dir`. Скрипт останавливает процесс и удаляет
временные файлы сессии.
