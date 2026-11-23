# Security policy

## Reporting a vulnerability

Report a vulnerability privately through GitHub:
https://github.com/grigoriev/alfred-dev/security/advisories/new
(the **Security** tab, **Report a vulnerability**). Do not open a public issue for it.

We answer within a week. The fix goes into the next release, and its release notes name it.

## Supported versions

Only the latest release gets fixes.

## Scope

The plugin code: agents, commands, skills, hooks, the core helpers, the MCP memory server, the
installers and the workflows.

Vulnerabilities in upstream software (Claude Code, the Python `mcp` package, the GitHub,
Greptile and SonarCloud CLIs and services it calls) belong to the upstream project. Tell us as
well if this project is affected, so we can release a fix when the upstream fix is out.
