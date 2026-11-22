#!/usr/bin/env python3
"""
PreToolUse hook for Read: informational warning on sensitive file reads.

Intercepts file reads and writes a warning to stderr if the requested file
matches a sensitive file pattern (private keys, environment variables,
credentials, etc.).

Unlike secret-guard.sh, this hook does NOT block the operation. It tells
the agent that it is reading sensitive content, so the agent takes care
not to leak that content into replies, commits or generated artifacts.

Security policy: informational (always exit 0). If the input cannot be
parsed, the operation is allowed with no warning.
"""

import json
import os
import sys


def _is_env_file(base_name, _ext):
    return base_name == ".env" or base_name.startswith(".env.")


def _is_private_key(_base_name, ext):
    return ext in (".pem", ".key", ".p12", ".pfx")


def _is_ssh_private_key(base_name, _ext):
    return base_name in ("id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")


def _is_service_credentials_file(base_name, ext):
    lowered = base_name.lower()

    if lowered in {
        "credentials.json",
        "service-account.json",
        "gcloud-credentials.json",
        ".npmrc",
        ".pypirc",
        "terraform.tfstate",
    }:
        return True

    if ext != ".json":
        return False

    return (
        lowered.startswith("service-account")
        or lowered.startswith("firebase-adminsdk")
        or lowered.endswith("-service-account.json")
    )


def _is_htpasswd(base_name, _ext):
    return base_name == ".htpasswd"


def _is_java_keystore(_base_name, ext):
    return ext in (".jks", ".keystore")


# --- Sensitive file patterns -----------------------------------------------
# Each tuple holds (condition_function, description).
# Conditions check the file base name or the full path, as needed.

_SENSITIVE_PATTERNS = [
    # Environment variables
    (_is_env_file, "Файл переменных окружения"),
    # Private keys
    (_is_private_key, "Приватный ключ или сертификат"),
    # SSH keys
    (_is_ssh_private_key, "Приватный SSH-ключ"),
    # Service credentials
    (_is_service_credentials_file, "Учётные данные сервиса"),
    # htpasswd
    (_is_htpasswd, "Файл паролей Apache"),
    # Note: AWS credentials are detected by path in _PATH_PATTERNS,
    # not by base name, because "credentials" and "config" are too generic.
    # Keystore
    (_is_java_keystore, "Хранилище ключей Java"),
]

# Patterns checked against the full path (not only the base name)
_PATH_PATTERNS = [
    (".aws/credentials", "Учётные данные AWS"),
    (".aws/config", "Конфигурация AWS, возможно с учётными данными"),
    ("/.docker/config.json", "Учётные данные Docker"),
    ("/.kube/config", "Конфигурация Kubernetes"),
    ("/.terraform/terraform.tfstate", "Состояние Terraform, возможно с секретами"),
    (".ssh/", "Каталог SSH (возможны приватные ключи)"),
    (".gnupg/", "Каталог GPG (возможны приватные ключи)"),
]


def main():
    """Hook entry point.

    Reads the PreToolUse JSON from stdin, extracts the file path from
    ``tool_input.file_path`` and checks it against the sensitive file
    patterns. On a match, writes an informational warning.
    """
    try:
        data = json.load(sys.stdin)
    except (ValueError, json.JSONDecodeError):
        sys.exit(0)

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "") or tool_input.get("path", "")

    if not file_path:
        sys.exit(0)

    normalized_path = file_path.replace("\\", "/")

    # Get the base name and extension for the checks
    base_name = os.path.basename(normalized_path)
    _, ext = os.path.splitext(base_name)

    # Check base name patterns
    warning = None
    for check_fn, description in _SENSITIVE_PATTERNS:
        try:
            if check_fn(base_name, ext):
                warning = description
                break
        except Exception as exc:
            print(
                f"[Alfred Dev] Ошибка при проверке шаблона чувствительного файла "
                f"'{description}': {exc}",
                file=sys.stderr,
            )
            continue

    # Check full path patterns
    if warning is None:
        for pattern, description in _PATH_PATTERNS:
            if pattern in normalized_path:
                warning = description
                break

    if warning is not None:
        print(
            f"\n[Alfred Dev] ВНИМАНИЕ: чтение чувствительного файла\n\n"
            f"  Файл: {file_path}\n"
            f"  Тип:  {warning}\n\n"
            f"  Не допусти утечки содержимого этого файла\n"
            f"  в ответы, коммиты, логи или созданные артефакты.\n",
            file=sys.stderr,
        )

    # Always allow the read (informational, not blocking)
    sys.exit(0)


if __name__ == "__main__":
    main()
