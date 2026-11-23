---
name: sync-project-docs
description: "Use to sync living project documentation after a phase: update docs/project, the index, architecture.md, compliance.md, threat-model. Triggers: обновить docs/project, синхронизировать документацию, индекс, живая документация."
---

# Living documentation sync

Communicate with the user in Russian.

## Summary

After a phase, update only what changed. The helper creates scaffolds
and checks the gate. You write the content.

## Process

1. Scaffold and index:

   ```bash
   python3 .claude/alfred-continuity.py sync-project-docs "$PWD"
   ```

2. Read `docs/project/README.md` and the protocol `commands/_living_docs.md`.

3. Update only this phase's files. If there was no new API, do not
   touch the API guide. If there was no decision, do not invent an ADR.

4. When a scaffold gets real content, leave `<!-- alfred-doc:filled -->`
   and remove `<!-- alfred-doc:scaffold -->`.

5. Check the gate:

   ```bash
   python3 .claude/alfred-continuity.py check-project-docs "$PWD" --command <команда> --phase <фаза>
   ```

6. If the helper fails, do not declare the phase closed.

## In quick and fix

Minimal sync: index + `docs/project/current.md`. ADR only if the change moves
a boundary (auth, data storage, integration).

## Success criteria

- The index reflects the real state (`scaffold` or `filled`).
- No invented text about code you did not touch.
- `check-project-docs` exits with code 0 before the gate closes.

## Do NOT

- Do not rewrite all of `docs/` in every phase.
- Do not copy the chat into Markdown.
- Do not set `filled` while `_(заполнить)_` remains.
