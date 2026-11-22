#!/usr/bin/env python3
"""
Tests for hooks/sensitive-read-guard.py.

Verify that the hook detects sensitive files correctly (private keys,
environment variables, service credentials, SSH/GPG directories) and
allows normal files without a warning.

The hook is informational (always exit 0), so the tests check stderr
to see whether it emitted a warning.
"""

import importlib.util
import io
import json
import os
import sys
import unittest


def _load_module():
    """Load the sensitive-read-guard.py module by path (the name has a hyphen)."""
    module_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "hooks",
        "sensitive-read-guard.py",
    )
    spec = importlib.util.spec_from_file_location("sensitive_read_guard", module_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_guard = _load_module()


class TestSensitivePatterns(unittest.TestCase):
    """Verify that _SENSITIVE_PATTERNS detects the expected files."""

    def _check(self, base_name: str, expected_match: bool):
        """Check if a file name matches any pattern."""
        _, ext = os.path.splitext(base_name)
        matched = False
        for check_fn, _desc in _guard._SENSITIVE_PATTERNS:
            try:
                if check_fn(base_name, ext):
                    matched = True
                    break
            except Exception:
                continue
        self.assertEqual(
            matched,
            expected_match,
            f"{base_name}: expected {'match' if expected_match else 'no match'}",
        )

    # --- .env files ---
    def test_dotenv_base(self):
        self._check(".env", True)

    def test_dotenv_local(self):
        self._check(".env.local", True)

    def test_dotenv_production(self):
        self._check(".env.production", True)

    def test_env_without_dot(self):
        """A file named 'env' without a dot is not sensitive."""
        self._check("env", False)

    # --- Private keys ---
    def test_pem_file(self):
        self._check("server.pem", True)

    def test_key_file(self):
        self._check("private.key", True)

    def test_p12_file(self):
        self._check("cert.p12", True)

    def test_pfx_file(self):
        self._check("cert.pfx", True)

    # --- SSH keys ---
    def test_id_rsa(self):
        self._check("id_rsa", True)

    def test_id_ed25519(self):
        self._check("id_ed25519", True)

    def test_id_ecdsa(self):
        self._check("id_ecdsa", True)

    def test_id_dsa(self):
        self._check("id_dsa", True)

    def test_id_rsa_pub_not_sensitive(self):
        """Public keys are not sensitive."""
        self._check("id_rsa.pub", False)

    # --- Service credentials ---
    def test_credentials_json(self):
        self._check("credentials.json", True)

    def test_service_account_json(self):
        self._check("service-account.json", True)

    def test_service_account_variant_json(self):
        self._check("service-account.prod.json", True)

    def test_firebase_adminsdk_json(self):
        self._check("firebase-adminsdk-prod.json", True)

    def test_npmrc(self):
        self._check(".npmrc", True)

    def test_pypirc(self):
        self._check(".pypirc", True)

    def test_terraform_state(self):
        self._check("terraform.tfstate", True)

    def test_htpasswd(self):
        self._check(".htpasswd", True)

    # --- Java keystore ---
    def test_jks(self):
        self._check("keystore.jks", True)

    def test_keystore(self):
        self._check("app.keystore", True)

    # --- Normal files (not sensitive) ---
    def test_readme(self):
        self._check("README.md", False)

    def test_python_file(self):
        self._check("main.py", False)

    def test_json_config(self):
        self._check("config.json", False)

    def test_package_json(self):
        self._check("package.json", False)

    def test_txt_file(self):
        self._check("notes.txt", False)


class TestPathPatterns(unittest.TestCase):
    """Verify that _PATH_PATTERNS detects sensitive paths."""

    def _check_path(self, file_path: str, expected_match: bool):
        """Check if a full path matches any pattern."""
        matched = False
        for pattern, _desc in _guard._PATH_PATTERNS:
            if pattern in file_path:
                matched = True
                break
        self.assertEqual(
            matched,
            expected_match,
            f"{file_path}: expected {'match' if expected_match else 'no match'}",
        )

    def test_aws_credentials(self):
        self._check_path("/home/user/.aws/credentials", True)

    def test_aws_config(self):
        self._check_path("/home/user/.aws/config", True)

    def test_ssh_dir(self):
        self._check_path("/home/user/.ssh/id_rsa", True)

    def test_gnupg_dir(self):
        self._check_path("/home/user/.gnupg/private-keys-v1.d/key.key", True)

    def test_docker_config_path(self):
        self._check_path("/home/user/.docker/config.json", True)

    def test_kube_config_path(self):
        self._check_path("/home/user/.kube/config", True)

    def test_terraform_state_path(self):
        self._check_path("/home/user/.terraform/terraform.tfstate", True)

    def test_windows_docker_config_path(self):
        self._check_path("C:/Users/test/.docker/config.json", True)

    def test_normal_path(self):
        self._check_path("/home/user/projects/app/main.py", False)

    def test_aws_not_in_path(self):
        self._check_path("/home/user/projects/aws-sdk/index.js", False)


class TestMainFunction(unittest.TestCase):
    """Verify the full flow of the hook main()."""

    def _run_hook(self, hook_input: dict) -> str:
        """Run main() with the given input and capture stderr."""
        old_stdin = sys.stdin
        old_stderr = sys.stderr
        captured_stderr = io.StringIO()

        try:
            sys.stdin = io.StringIO(json.dumps(hook_input))
            sys.stderr = captured_stderr
            _guard.main()
        except SystemExit:
            pass
        finally:
            sys.stdin = old_stdin
            sys.stderr = old_stderr

        return captured_stderr.getvalue()

    def test_sensitive_file_emits_warning(self):
        """Reading a .env file must write a warning to stderr."""
        output = self._run_hook({
            "tool_input": {"file_path": "/project/.env"}
        })
        self.assertIn("ВНИМАНИЕ", output)
        self.assertIn("переменных окружения", output.lower())

    def test_normal_file_no_warning(self):
        """Reading a normal file must not emit a warning."""
        output = self._run_hook({
            "tool_input": {"file_path": "/project/src/main.py"}
        })
        self.assertEqual(output, "")

    def test_ssh_key_emits_warning(self):
        """Reading an SSH key must emit a warning."""
        output = self._run_hook({
            "tool_input": {"file_path": "/home/user/.ssh/id_rsa"}
        })
        self.assertIn("ВНИМАНИЕ", output)

    def test_empty_path_no_warning(self):
        """An empty path must not emit a warning."""
        output = self._run_hook({
            "tool_input": {"file_path": ""}
        })
        self.assertEqual(output, "")

    def test_invalid_json_no_crash(self):
        """Invalid JSON must not cause a crash."""
        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("this is not json")
            _guard.main()
        except SystemExit as e:
            self.assertEqual(e.code, 0)
        finally:
            sys.stdin = old_stdin

    def test_path_key_fallback(self):
        """The hook must try both file_path and path."""
        output = self._run_hook({
            "tool_input": {"path": "/project/.env.local"}
        })
        self.assertIn("ВНИМАНИЕ", output)

    def test_pem_file_warning(self):
        """Reading a .pem file must emit a warning."""
        output = self._run_hook({
            "tool_input": {"file_path": "/certs/server.pem"}
        })
        self.assertIn("ВНИМАНИЕ", output)
        self.assertIn("Приватный ключ", output)

    def test_docker_config_warning(self):
        """Docker configuration must warn as a sensitive credential."""
        output = self._run_hook({
            "tool_input": {"file_path": "/home/user/.docker/config.json"}
        })
        self.assertIn("ВНИМАНИЕ", output)
        self.assertIn("Docker", output)

    def test_service_account_variant_warning(self):
        """Variants of service-account.json must also warn."""
        output = self._run_hook({
            "tool_input": {"file_path": "/secrets/service-account.prod.json"}
        })
        self.assertIn("ВНИМАНИЕ", output)
        self.assertIn("Учётные данные сервиса", output)

    def test_kube_config_warning(self):
        """kubeconfig configuration must warn."""
        output = self._run_hook({
            "tool_input": {"file_path": "/home/user/.kube/config"}
        })
        self.assertIn("ВНИМАНИЕ", output)
        self.assertIn("Kubernetes", output)


if __name__ == "__main__":
    unittest.main()
