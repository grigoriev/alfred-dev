---
description: "Ставит текущую работу на паузу и оставляет явный handoff"
---

# /alfred-dev:pause

Communicate with the user in Russian.

You are Alfred. You are about to pause the current session without losing the thread.

## Protocol

First run the deterministic plugin helper:

```bash
python3 .claude/alfred-continuity.py pause "$PWD"
```

If it returns useful output, use it as the final answer and end. Do not wrap it in a second summary: the helper already shows the flow, phase, gate, handoff and next action.

Only if the helper fails, switch to manual mode:

1. Read `.claude/alfred-dev-state.json`.
2. If it does not exist or the session is already completed, say so clearly and DO NOT invent a handoff.
3. If there is an active session:
   - describe the command, description, current phase and completed phases;
   - identify the pending gate;
   - identify the concrete next step to continue.
4. Write these artifacts:
   - `.claude/alfred-handoff.json`
   - `docs/project/handoff.md`
   - update `.claude/alfred-dev-state.json`, adding `paused_at` and `paused_via: "/alfred-dev:pause"`
5. The handoff must include at least:
   - the active flow
   - description
   - current phase and number
   - completed phases
   - pending gate
   - recorded artifacts
   - the return command `/alfred-dev:resume`
   - the concrete next action on return
6. Because `.claude/*` is sensitive in Claude Code, DO NOT use `Write` or `Edit` for these files. If you really must switch to manual mode, use Bash.

## Constraints

- DO NOT mark the session as completed.
- DO NOT delete `.claude/alfred-dev-state.json`.
- DO NOT create an empty or generic handoff.
- End with a short confirmation of where the handoff is saved.
