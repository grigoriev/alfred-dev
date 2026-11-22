#!/usr/bin/env python3
"""
Single source of truth for secret detection patterns.

This module centralizes the regexes that detect credentials, tokens and keys
in plain text. The consumers are:

    - ``core/memory.py``: sanitizes content before it is stored in SQLite.
    - ``hooks/secret-guard.sh``: blocks writes of secrets to files.
    - ``hooks/sensitive-read-guard.py``: warns when sensitive files are read.

Before this module, the patterns were duplicated in 3 places with slightly
different variants. A new pattern or a regex fix had to be copied by hand
to all 3 files. Now each change is made here and applies everywhere.

The patterns go from most specific to most generic, so that a broad
pattern does not take a match that a more precise one should capture.
"""

import os
import re
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Secret patterns in text content
# ---------------------------------------------------------------------------
# Each tuple holds (compiled_pattern, marker_label).
# Sanitization uses the label as [REDACTED:<label>].

SECRET_PATTERNS: List[Tuple[re.Pattern, str]] = [
    # AWS keys (fixed AKIA prefix)
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS_KEY"),
    # Anthropic API key (sk-ant- prefix)
    (re.compile(r"sk-ant-[a-zA-Z0-9\-]{20,}"), "ANTHROPIC_KEY"),
    # Keys with a generic sk- prefix (OpenAI, Stripe, etc.)
    (re.compile(r"sk-[a-zA-Z0-9]{20,}"), "SK_KEY"),
    # GitHub personal access token (ghp_ or github_pat_)
    (
        re.compile(r"(ghp_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{20,})"),
        "GITHUB_TOKEN",
    ),
    # Slack Token (xoxb, xoxp, xoxs, xoxa)
    (re.compile(r"xox[bpsa]-[a-zA-Z0-9\-]{10,}"), "SLACK_TOKEN"),
    # Google API key (AIza prefix)
    (re.compile(r"AIza[0-9A-Za-z\-_]{35}"), "GOOGLE_KEY"),
    # SendGrid API Key
    (
        re.compile(r"SG\.[a-zA-Z0-9\-_]{22,}\.[a-zA-Z0-9\-_]{22,}"),
        "SENDGRID_KEY",
    ),
    # PEM/SSH private keys
    (
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
        "PRIVATE_KEY",
    ),
    # Hardcoded JWT tokens (3 base64url segments separated by dots)
    (
        re.compile(
            r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"
        ),
        "JWT",
    ),
    # Connection strings with embedded credentials
    (
        re.compile(
            r"(?:mysql|postgresql|postgres|mongodb(?:\+srv)?|redis|amqp)"
            r"://(?:(?:[^/\s\"':@]+:[^/\s\"'@]+)|(?:[^/\s\"'@]{8,}))@"
        ),
        "CONNECTION_STRING",
    ),
    # Slack Webhook URL
    (
        re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/]+"),
        "SLACK_WEBHOOK",
    ),
    # Discord Webhook URL
    (
        re.compile(
            r"https://discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+"
        ),
        "DISCORD_WEBHOOK",
    ),
    # Direct credential assignments in source code
    (
        re.compile(
            r"(?i)(?:password|passwd|api_key|apikey|api_secret|secret_key"
            r"|auth_token|access_token|private_key)"
            r"""\s*[:=]\s*["'][^"']{8,}["']"""
        ),
        "HARDCODED_CREDENTIAL",
    ),
]

SECRET_DESCRIPTIONS = {
    "AWS_KEY": "AWS Access Key (шаблон AKIA...)",
    "ANTHROPIC_KEY": "Anthropic API Key",
    "SK_KEY": "API-ключ с префиксом sk- (OpenAI, Stripe или другой)",
    "GITHUB_TOKEN": "GitHub Personal Access Token",
    "SLACK_TOKEN": "Slack Token",
    "GOOGLE_KEY": "Google API Key (шаблон AIza...)",
    "SENDGRID_KEY": "SendGrid API Key",
    "PRIVATE_KEY": "Приватный ключ PEM/SSH",
    "JWT": "Захардкоженный JWT-токен",
    "CONNECTION_STRING": "Connection string с учётными данными",
    "SLACK_WEBHOOK": "Slack Webhook URL",
    "DISCORD_WEBHOOK": "Discord Webhook URL",
    "HARDCODED_CREDENTIAL": "Захардкоженные учётные данные в присваивании",
}

_ALLOWED_ENV_SUFFIXES = {
    "local",
    "development",
    "development.local",
    "test",
    "test.local",
    "production",
    "production.local",
    "staging",
    "staging.local",
}

_DISALLOWED_ENV_TOKENS = {
    "example",
    "sample",
    "template",
    "dist",
}


def describe_secret_label(label: str) -> str:
    """Return a readable description for the secret type."""
    return SECRET_DESCRIPTIONS.get(label, label)


def find_secret_label(text: str) -> Optional[str]:
    """Return the first secret label found in ``text``."""
    for pattern, label in SECRET_PATTERNS:
        if pattern.search(text):
            return label
    return None


def is_secret_storage_path(file_path: str) -> bool:
    """Tell if the path is a legitimate store for local secrets.

    Real project env files are allowed. Their example or template
    variants are not, because they are usually under version control.
    """
    if not file_path:
        return False

    base_name = os.path.basename(file_path).lower()

    if base_name in {".env", "local.env"}:
        return True

    if not base_name.startswith(".env."):
        return False

    suffix = base_name[len(".env."):]
    if not suffix:
        return False

    if suffix in _ALLOWED_ENV_SUFFIXES:
        return True

    parts = [part for part in suffix.split(".") if part]
    return not any(part in _DISALLOWED_ENV_TOKENS for part in parts)


def sanitize_text(text: str) -> str:
    """Replace detected secrets with [REDACTED:<type>] markers.

    Applies all ``SECRET_PATTERNS`` to the text and replaces each
    match with its marker.

    Args:
        text: text to sanitize.

    Returns:
        Text with secrets replaced by markers.
    """
    for pattern, label in SECRET_PATTERNS:
        text = pattern.sub(f"[REDACTED:{label}]", text)
    return text
