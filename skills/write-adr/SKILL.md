---
name: write-adr
description: "Use to write or close an Architecture Decision Record: ADR, docs/adr, a decision on stack, data storage, authentication or architecture boundaries. Triggers: ADR, записать решение, решение по стеку, хранению данных, аутентификации, границам архитектуры."
---

# Writing an ADR

Communicate with the user in Russian.

## Summary

Documents a significant architecture decision in `docs/adr/`. An ADR is not a
diary. Write one only for a real choice (stack, data storage,
auth, boundaries, integration).

## Process

1. Create the scaffold with the helper. Do not pick the number by hand:

   ```bash
   python3 .claude/alfred-continuity.py next-adr "$PWD" --title "Короткий заголовок"
   ```

2. Read `templates/adr.md` if it exists, and the file you just created.

3. Fill it with facts from the repository:

   - context and constraints
   - at least two real options, with pros and cons
   - the decision and why
   - consequences and accepted debt

4. Initial status: `proposed`, until the user or the architecture gate
   accepts it. Then `accepted`. If the decision changes later, create a new ADR
   that references the old one; do not rewrite the old one.

5. Replace `<!-- alfred-doc:scaffold -->` with `<!-- alfred-doc:filled -->`.

6. Run `sync-project-docs` to update the index.

7. If the decision concerns design, also record it with `memory_log_decision`.
   Memory does not replace the ADR.

## Success criteria

- The file is at `docs/adr/ADR-NNN-....md`.
- At least two options are evaluated.
- The decision and its consequences are readable without the chat.
- Marker: `filled`.

## Do NOT

- Do not open an ADR for a rename or a local edit in `quick`.
- Do not leave `_(заполнить)_` in an ADR you declare closed.
- Do not copy a generic ADR that does not mention the repository.
