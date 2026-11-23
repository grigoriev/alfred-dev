---
description: "Внутренний протокол живой документации: какой файл обновляется на каждом gate."
---

# Living project documentation

Communicate with the user in Russian.

Shared protocol. Read by `feature`, `fix`, `quick`, `spike`, `audit`, `ship`, `map-codebase` and `discuss`. This is not a slash command.

## Step 0 -- skeleton

Before the first phase (or when mapping / discussing), run:

```bash
python3 .claude/alfred-continuity.py sync-project-docs "$PWD"
```

It creates, if missing:

- `docs/project/README.md` (index)
- `docs/project/architecture.md`
- `docs/project/compliance.md`
- `docs/project/threat-model.md`
- `docs/project/dependencies.md`
- `docs/adr/`

It does not write prose. Skeletons contain `<!-- alfred-doc:scaffold -->`.

## What to touch at each moment

Update only what the phase changed. Do not rewrite the rest.

| Moment | Who | Files |
|--------|-----|-------|
| `discuss` | Alfred | index (exists) + `discovery.md` |
| `map-codebase` | helper + Alfred | index + architecture skeleton |
| Product approved | product-owner | PRD; index is updated |
| Architecture | architect + security-officer | `architecture.md` (filled), ADR if a decision exists, `threat-model.md` (filled) |
| New dependency | architect or security-officer | `dependencies.md` |
| Development / quick / fix | tech-writer (short sync) + senior-dev | index; headers/docstrings of affected code; `current.md` |
| Quality / audit | security-officer | `compliance.md` with evidence |
| Closing documentation / ship | tech-writer | index, CHANGELOG, release notes |
| Pause | helper | handoff (no change to architecture/compliance) |

## Before closing a gate

```bash
python3 .claude/alfred-continuity.py check-project-docs "$PWD" --command <команда> --phase <фаза>
```

If the helper exits with a non-zero code, the gate is not passed. Fill the gap and check again.

A document counts as filled when it contains `<!-- alfred-doc:filled -->` or when it already existed with real content (without the skeleton marker).

## ADR

If the architecture phase (or a spike) makes a new decision:

```bash
python3 .claude/alfred-continuity.py next-adr "$PWD" --title "Короткое название решения"
```

Then architect fills the file with the `write-adr` skill.

## Skills

- `sync-project-docs` -- how to sync without inventing prose
- `write-adr` -- how to close an ADR
- `evaluate-dependency` -- how to record a dependency
- `compliance-check` -- how to fill the register
- `threat-model` -- how to fill the model

## Tech Writer

After each phase (not only at the end), run a short sync by `tech-writer`:

1. `sync-project-docs`
2. update only the affected sections
3. `check-project-docs` for the current phase

In `quick` and `fix` the sync is minimal: index + a note in `current.md`. ADR only if the change moves an architecture boundary.
