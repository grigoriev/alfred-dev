---
name: style-direction
description: "Open and use the Designer visual companion to choose a style direction in projects with a UI. Manual skill: starts a local server and writes visual artifacts. Triggers: направление стиля, визуальный стиль, дизайн-система, палитра, типографика."
disable-model-invocation: true
---

# Designer visual server guide

Communicate with the user in Russian.

A local browser server that shows design systems and visual options
in the style direction phase. It works as a visual companion: it shows the base
Designer catalog, lets the user lock family +
typography + color scheme, and then closes the final three-column round.

## When to use the visual server

Always, when Designer generates style options. The server is Designer's main tool:
it shows the gallery of 10 base design systems, runs
the guided selection process, and shows the final round of 3 comparable proposals.

## Start a session

```bash
visual/scripts/start-server.sh --project-dir /путь/к/проекту
```

Expected JSON response:

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

Save `screen_dir` (where to write the options HTML) and `state_dir`
(where to read click events and check server state).

`state_dir/server-info` contains the same JSON as the start output.
Read it before each operation to confirm the server is still active.

Ask the user to open the URL in a browser.

## Loop

1. Confirm the server is still active: read `STATE_DIR/server-info`.
2. If it adds context, first generate the catalog gallery with `python3 visual/scripts/write-style-demo-gallery.py --visual-path "$STATE_DIR"`.
3. Recommended guided process:
   - `python3 visual/scripts/write-style-selector.py --visual-path "$STATE_DIR"` to choose the base system.
   - read the choice with `python3 visual/scripts/read-choice.py "$STATE_DIR"`.
   - `python3 visual/scripts/write-style-selector.py --visual-path "$STATE_DIR" --style-id "<style_id>"` so the user picks typography + palette.
   - read the choice again with `python3 visual/scripts/read-choice.py "$STATE_DIR"`.
   - `python3 visual/scripts/write-guided-style-options.py --visual-path "$STATE_DIR"` to generate the final round of 3 options from that choice.
4. Alternative direct process: if the three proposals are already decided, generate `screen_dir/style-options.html` with `python3 visual/scripts/write-style-options.py --visual-path "$STATE_DIR"`. If you write it by hand, use the `.style-grid` class.
5. The final JSON sidecar must be at `screen_dir/style-options.json`, so the final artifact can be built later without re-interpreting the screen.
6. Tell the user: repeat the URL, briefly describe what is shown, ask them to pick one option.
7. Next turn: read the final choice with `python3 visual/scripts/read-choice.py "$STATE_DIR"` or, if you prefer, inspect `STATE_DIR/events` directly.
8. Generate `docs/style-direction.md` with `python3 visual/scripts/write-style-direction.py --project-dir "$PWD" --visual-path "$STATE_DIR"` or, if you need manual control, write the artifact yourself from the JSON sidecar.
9. Write `waiting.html` to `screen_dir` to clear the browser until the next action.

## Recommended JSON sidecar

For a good final artifact, each proposal should include at least:

- `choice`
- `name`
- `concept` or `description`
- `palette`
- `typography`
- `spacing_density` or `layout_density`
- `tone` or `mood`
- `sample_component` or `component_example`
- `visual_principles` or `design_principles`
- `layout_grammar` or `composition_grammar`
- `surface_treatment` or `materiality`
- `shape_language`
- `motion_language`
- `signature_elements` or `visual_motifs`
- `implementation_guardrails` or `guardrails`
- `prompt_seed` or `design_prompt`
- `rationale` or `why`
- `not_this_direction` or `anti_patterns`
- `context_signals`, `audience` or `constraints`

The canonical writer tolerates incomplete sidecars and reasonable aliases, but the more
specific the proposal, the less generic the final direction.

### Critical guided-process rule

If the user already locked **family + typography + palette**, the three final options
must still belong to the same system. Between `A / B / C` you can change
composition, hierarchy or expressiveness, but not the base grammar
of the chosen system.

When you generate the sidecar by hand:

- reuse the system `prompt_seed` as the main seed
- always carry over `visual_principles`, `layout_grammar` and `signature_elements`
- use `implementation_guardrails` so the option does not drift to another family
- do not mix in references to another trend only to "make it prettier"

## Canonical options writer

Recommended helper:

```bash
python3 visual/scripts/write-style-options.py --visual-path "$STATE_DIR"
```

This script:

- finds `style-options.json` automatically
- normalizes common sidecar aliases
- writes an HTML fragment compatible with the real server
- does not depend on external assets missing from the repository

To customize the heading text, it accepts `--title` and `--subtitle`.

## Guided selection of system + typography + palette

Designer works in three steps:

1. **Base system** - `python3 visual/scripts/write-style-selector.py --visual-path "$STATE_DIR"`
2. **Typography + palette** - `python3 visual/scripts/write-style-selector.py --visual-path "$STATE_DIR" --style-id "<style_id>"`
3. **Three final options** - `python3 visual/scripts/write-guided-style-options.py --visual-path "$STATE_DIR"`

`read-choice.py` stays the canonical reader between steps. If the choice
belongs to the guided process, it also returns `parsed_choice` with `stage`,
`style_id`, `font_pairing_id` and `palette_mode`.

## Options HTML structure

The server wraps HTML fragments in its own frame and loads `helper.js`,
so do not write a full document or add extra assets. Recommended
format:

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

Each `.style-option` MUST have `data-choice` with a unique identifier
(letter, number or slug). This attribute is written to the events
on click.

## Event format

`STATE_DIR/events` contains one JSON line per event, in chronological order.
Current canonical form:

```jsonl
{"source":"user-event","type":"click","choice":"A","label":"Тёмный космос","element":".style-option","ts":"2026-03-31T10:14:02Z","timestamp":"2026-03-31T10:14:02Z"}
{"source":"user-event","type":"click","choice":"A","label":"Тёмный космос","element":".style-option","ts":"2026-03-31T10:14:05Z","timestamp":"2026-03-31T10:14:05Z"}
```

The canonical reader `visual/scripts/read-choice.py` also accepts the old legacy format:

```jsonl
{"ts":"2026-03-31T10:14:02Z","type":"click","choice":"A","element":".style-option"}
{"ts":"2026-03-31T10:14:05Z","type":"click","choice":"A","element":".style-option"}
```

The last click with `type: "click"` on `.style-option` is the user's final choice.
Several clicks on the same option count as confirmation. If clicks were on
different options, the latest wins.

## Stop the server

```bash
visual/scripts/stop-server.sh <session_dir>
```

`session_dir` is the session directory returned by `start-server.sh`, or the common
parent of `screen_dir` and `state_dir`. The script stops the process and deletes
the session temporary files.
