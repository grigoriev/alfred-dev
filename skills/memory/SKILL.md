---
name: memory
description: "This skill should be used when the user asks to record a design decision, search past project decisions, inspect the Alfred memory timeline, or work with the alfred-memory MCP server. Use it to call the namespaced MCP tools instead of inventing history. Triggers: запиши решение, почему мы решили, что мы делали в прошлый раз, память, история решений."
---

# Alfred persistent memory

Communicate with the user in Russian.

Record and query project decisions through the `alfred-memory` MCP server. Do not invent history. If a tool is unavailable, say so and do not simulate results.

## Real tool names

Claude Code exposes plugin tools with an MCP prefix. Use these names, not the short ones:

- `mcp__plugin_alfred-dev_alfred-memory__memory_search`
- `mcp__plugin_alfred-dev_alfred-memory__memory_get_decisions`
- `mcp__plugin_alfred-dev_alfred-memory__memory_get_iteration`
- `mcp__plugin_alfred-dev_alfred-memory__memory_get_timeline`
- `mcp__plugin_alfred-dev_alfred-memory__memory_stats`
- `mcp__plugin_alfred-dev_alfred-memory__memory_log_decision`
- `mcp__plugin_alfred-dev_alfred-memory__memory_update_decision`
- `mcp__plugin_alfred-dev_alfred-memory__memory_link_decisions`
- `mcp__plugin_alfred-dev_alfred-memory__memory_health`

If the runtime shows a different prefix, use the one in the tool list, always from the `alfred-memory` server.

## What is recorded and what is not

Yes: architecture and design decisions, gate results, handoffs, UAT and commits made in an Alfred session.

No: old Git history, every Read/Glob/Grep, operational tips and an empty kanban.

Call `memory_log_decision` only for a real choice in design, security or delivery. Do not log every edit. If a decision concerns architecture or compliance, the human reads the living Markdown (`docs/adr/`, `docs/project/compliance.md`); memory does not replace it.

Minimum fields: title, context, rejected alternatives, rationale, tags.

## Query

For «почему мы решили X» or «что мы делали в прошлый раз»: `memory_search` or `memory_get_decisions` with the term and, if applicable, a range or tags.

If there are no records, say there are no records. Do not speculate.

The `librarian` agent does not exist. This skill and `/alfred-dev:memory-ui` are the way to access history.

## UI

Graphical view: `/alfred-dev:memory-ui`. This skill does not start the HTTP server. To close it: `/alfred-dev:memory-ui stop`. It stops by itself when the Claude session ends.
