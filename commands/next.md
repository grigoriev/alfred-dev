---
description: "Определяет следующий операционный шаг и выполняет его, если он однозначен"
---

# /alfred-dev:next

Communicate with the user in Russian.

You are Alfred. Your task: answer one question, **what to do now**.

## Protocol

The single default step: this command must rely on the deterministic helper first. Run this Bash immediately and use its JSON as the canonical source of the decision:

```bash
python3 .claude/alfred-continuity.py next "$PWD" --json
```

The helper output already defines:

- `source` and `source_label`;
- `focus`;
- `command`;
- `directive`;
- `reason`.

If the helper returns an unambiguous recommendation (`resume`, `verify`, `map-codebase` or clear saved continuity), use it as the operational base. Do not re-evaluate repository priorities from scratch.

Only if the helper fails or is unavailable, switch to the manual mode below.

## Priority order

ALWAYS read in this order:

1. `.claude/alfred-dev-state.json`
2. `.claude/alfred-handoff.json`
3. `.claude/alfred-uat.json`
4. `docs/project/discovery.md`
5. `docs/project/current.md`
6. `docs/project/codebase-map.md`
7. `docs/project/handoff.md`
8. `docs/project/uat.md`

Then decide:

1. **If there is an active session** and `current_phase` is not `completed`:
   - act as `/alfred-dev:resume`
   - briefly describe the flow, current phase, pending gate and first concrete step
   - DO NOT try to pass the pending gate and do not use `AskUserQuestion` inside this helper

2. **If there is no active session but there is an open handoff**:
   - act as `/alfred-dev:resume`
   - use the handoff as the main context
   - DO NOT use `AskUserQuestion` here

3. **If the last completed flow has no approved UAT yet**:
   - if `.claude/alfred-uat.json` does not exist or has `status: "pending"` for the last result, act as `/alfred-dev:uat`
   - if `.claude/alfred-uat.json` has `status: "rejected"`, show that there are open fixes and suggest `/alfred-dev:alfred`, based on `docs/project/uat.md`

4. **If the project already has code but no brownfield map** (`docs/project/codebase-map.md` or `docs/project/current.md`):
   - act as `/alfred-dev:map-codebase`
   - do not just suggest it: run it

5. **If `docs/project/discovery.md` exists with a visible recommended command**:
   - prioritize this prior refinement
   - if it recommends `feature`, `quick`, `fix` or `spike`, present it as the natural next step
   - mention that the source is `discovery`

6. **If there is no current work and the project is already mapped**:
   - briefly state which next flow makes sense (`feature`, `fix`, `spike`, `audit` or `discuss`)
   - if the user already left clear context in the conversation, use it
   - if there really are two to four plausible routes, use **one real selectable menu** through `AskUserQuestion`; do not end with three options in non-selectable text
   - this menu must show only really plausible routes with a short description of each consequence

## Rules

- Never say «не знаю, что делать» without reading these files.
- If the next action is unambiguous, do not open an interview: continue.
- If you must ask because of real ambiguity, use one navigable `AskUserQuestion`. Do not list options in prose and leave the user guessing what to answer.
- Your answer must show:
  - the source used (`state`, `handoff`, `uat` or `map`)
  - if applicable, also `discovery`
  - the recommended or executed command
  - the concrete reason
