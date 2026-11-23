#!/usr/bin/env bash
# Compatibility: delegates to secret-guard.py (Write/Edit/Bash/MCP).
set -euo pipefail
SCRIPT_DIR=$(CDPATH="" cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec python3 "${SCRIPT_DIR}/secret-guard.py"
