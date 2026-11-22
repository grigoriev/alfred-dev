#!/usr/bin/env python3
"""Human-readable diagnosis to recover `claude -p` before the release."""

from __future__ import annotations

import argparse
import importlib.util
import json
import platform
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.7.0"
AUTH_REFERENCES = (
    "https://code.claude.com/docs/en/authentication",
    "https://code.claude.com/docs/en/errors",
    "https://code.claude.com/docs/en/troubleshoot-install",
)
AUTH_PRECEDENCE = (
    "CLAUDE_CODE_USE_BEDROCK/CLAUDE_CODE_USE_VERTEX/CLAUDE_CODE_USE_FOUNDRY",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "apiKeyHelper",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "subscription OAuth from login",
)


def _manual_smoke_module():
    spec = importlib.util.spec_from_file_location(
        "manual_smoke_for_auth_recovery",
        ROOT / "scripts" / "manual_smoke.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load scripts/manual_smoke.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _active_credential_env(auth_status: dict) -> list[str]:
    credential_env = auth_status.get("credential_env")
    if not isinstance(credential_env, dict):
        return []
    return sorted(str(key) for key, is_set in credential_env.items() if is_set)


def _platform_name(system_name: str | None = None) -> str:
    return system_name or platform.system() or "unknown"


def _macos_keychain_commands(system_name: str) -> list[str]:
    if system_name != "Darwin":
        return []
    return ["security unlock-keychain ~/Library/Keychains/login.keychain-db"]


def _script_oauth_fallback_commands() -> list[str]:
    return [
        "claude setup-token",
        "export CLAUDE_CODE_OAUTH_TOKEN=...  # paste only in your shell; do not write it to the repo",
        "npm run release:audit:manual:preflight",
    ]


def build_recovery_payload(preflight: dict, system_name: str | None = None) -> dict:
    auth_status = preflight.get("auth_status")
    if not isinstance(auth_status, dict):
        auth_status = {}
    diagnosis = preflight.get("diagnosis")
    if not isinstance(diagnosis, dict):
        diagnosis = {}

    status = str(preflight.get("status") or "unknown")
    diagnosis_code = str(diagnosis.get("code") or "unknown")
    active_env = _active_credential_env(auth_status)
    system = _platform_name(system_name)

    recovery_commands: list[str] = []
    diagnostic_commands: list[str] = [
        "claude auth status --json",
        "claude doctor",
        "npm run release:audit:manual:preflight:diagnose",
    ]
    fallback_commands: list[str] = []
    notes: list[str] = []
    if status == "ok":
        notes.append("Claude CLI already completes a minimal headless call.")
    elif active_env:
        notes.append(
            "Credential/provider variables are active. They can take precedence over the subscription login."
        )
        notes.append("Run the preflight in a clean terminal or unset those variables for this session.")
        recovery_commands.extend(
            [
                "npm run release:audit:manual:preflight",
                "npm run release:audit:prepublish:prepare",
            ]
        )
    elif diagnosis_code == "first_party_oauth_token_rejected":
        notes.append(
            "Claude reports an active login, but claude -p gets 401 before it uses tokens."
        )
        notes.append(
            "--bare is not a valid test for this case: it does not read subscription OAuth or CLAUDE_CODE_OAUTH_TOKEN."
        )
        if system == "Darwin":
            notes.append(
                "On macOS, Claude stores credentials in Keychain. If Keychain is locked or out of sync, claude -p can keep returning 401."
            )
        notes.append(
            "If claude doctor prints no output or hangs, do not use it as a gate. Refresh the login or use setup-token."
        )
        recovery_commands.extend(
            [
                "claude doctor",
                *_macos_keychain_commands(system),
                "claude auth logout",
                "claude auth login",
                "npm run release:audit:manual:preflight",
                "npm run release:audit:prepublish:prepare",
            ]
        )
        fallback_commands.extend(_script_oauth_fallback_commands())
    elif diagnosis_code == "not_logged_in":
        recovery_commands.extend(
            [
                "claude auth login",
                "npm run release:audit:manual:preflight",
                "npm run release:audit:prepublish:prepare",
            ]
        )
    else:
        recovery_commands.extend(
            [
                "claude auth status --json",
                "claude doctor",
                "npm run release:audit:manual:preflight:diagnose",
            ]
        )

    after_recovery_commands = [
        "npm run release:audit:manual:evidence",
        "npm run release:audit:manual:evidence:installed",
        "npm run release:audit:manual:review:init",
        "npm run release:audit:manual:review:installed:init",
        "npm run release:audit:manual:review",
        "npm run release:audit:manual:review:installed",
    ]

    return {
        "version": VERSION,
        "status": status,
        "reason": preflight.get("reason"),
        "diagnosis_code": diagnosis_code,
        "diagnosis_summary": diagnosis.get("summary"),
        "api_error_status": preflight.get("api_error_status"),
        "returncode": preflight.get("returncode"),
        "platform": system,
        "claude_version": auth_status.get("claude_version"),
        "loggedIn": auth_status.get("loggedIn"),
        "authMethod": auth_status.get("authMethod"),
        "apiProvider": auth_status.get("apiProvider"),
        "subscriptionType": auth_status.get("subscriptionType"),
        "active_credential_env": active_env,
        "credential_precedence": list(AUTH_PRECEDENCE),
        "notes": notes,
        "diagnostic_commands": diagnostic_commands,
        "debug_commands": [
            "claude -p --safe-mode --no-session-persistence --max-budget-usd 0.01 --output-format json --debug-file /tmp/alfred-claude-debug.log 'reply only OK'",
            "python3 - <<'PY'\nfrom pathlib import Path\nprint(Path('/tmp/alfred-claude-debug.log').read_text(errors='replace')[-4000:])\nPY  # review and sanitize before sharing",
        ],
        "recovery_commands": recovery_commands,
        "fallback_commands": fallback_commands,
        "after_recovery_commands": after_recovery_commands,
        "official_references": list(AUTH_REFERENCES),
        "publish_ready": False,
    }


def format_guidance(payload: dict) -> str:
    lines = [
        "Claude auth recovery 0.7.0",
        "",
        f"Status: {payload.get('status')}",
        f"Diagnosis: {payload.get('diagnosis_code')}",
        f"Reason: {payload.get('reason') or '-'}",
        f"Platform: {payload.get('platform') or '-'}",
        f"Claude CLI: {payload.get('claude_version') or '-'}",
        (
            "Auth: "
            f"loggedIn={payload.get('loggedIn')} "
            f"method={payload.get('authMethod') or '-'} "
            f"provider={payload.get('apiProvider') or '-'} "
            f"subscription={payload.get('subscriptionType') or '-'}"
        ),
        "Credential env: "
        + (", ".join(payload.get("active_credential_env") or []) or "none"),
        "",
    ]
    for note in payload.get("notes") or []:
        lines.append(f"- {note}")
    if payload.get("notes"):
        lines.append("")

    commands = payload.get("recovery_commands") or []
    if commands:
        lines.append("Recovery commands:")
        lines.extend(f"  {command}" for command in commands)
        lines.append("")

    fallback_commands = payload.get("fallback_commands") or []
    if fallback_commands:
        lines.append("Fallback for scripted/manual evidence if browser OAuth keeps failing:")
        lines.extend(f"  {command}" for command in fallback_commands)
        lines.append("")

    debug_commands = payload.get("debug_commands") or []
    if debug_commands:
        lines.append("Optional debug for support, sanitize before sharing:")
        lines.extend(f"  {command}" for command in debug_commands)
        lines.append("")

    lines.append("After auth is green, regenerate and review evidence:")
    lines.extend(f"  {command}" for command in payload.get("after_recovery_commands") or [])
    lines.append("")
    lines.append("Official references:")
    lines.extend(f"  {reference}" for reference in payload.get("official_references") or [])
    lines.append("")
    lines.append("Do not publish until manual review gates pass with current evidence.")
    return "\n".join(lines)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print only JSON.")
    parser.add_argument("--output", help="Write a JSON report with 0600 permissions.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero if the preflight is not ok.")
    parser.add_argument("--timeout", type=int, default=45, help="Preflight timeout in seconds.")
    args = parser.parse_args(argv)

    manual_smoke = _manual_smoke_module()
    preflight = manual_smoke._auth_preflight(timeout=args.timeout)
    payload = build_recovery_payload(preflight)

    if args.output:
        _write_json(Path(args.output).expanduser(), payload)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(format_guidance(payload))

    if not args.strict or payload.get("status") == "ok":
        return 0
    return 2 if payload.get("status") == "blocked_auth" else 1


if __name__ == "__main__":
    raise SystemExit(main())
