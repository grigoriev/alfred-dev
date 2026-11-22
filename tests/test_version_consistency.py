#!/usr/bin/env python3
"""Version consistency tests.

Check that all files that declare the plugin version agree with each other
and use a valid semver format. The source of truth is
.claude-plugin/plugin.json; the other files must show the same value.

Covered files:
  - .claude-plugin/plugin.json   (JSON, field "version")
  - .claude-plugin/marketplace.json (does not duplicate plugins[0].version)
  - package.json                 (JSON, field "version")
  - install.sh                   (bash, variable VERSION="...")
  - install.ps1                  (PowerShell, variable $Version = "...")
"""

import json
import os
import re
import unittest

# Project root (one level above tests/)
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")

# Simplified semver pattern: MAJOR.MINOR.PATCH with optional pre-release
_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[a-zA-Z0-9]+(?:\.[a-zA-Z0-9]+)*))?$"
)


def _read_file(relative_path: str) -> str:
    """Read a project file and return its content."""
    path = os.path.normpath(os.path.join(_PROJECT_ROOT, relative_path))
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _get_plugin_json_version() -> str:
    """Extract the version from .claude-plugin/plugin.json (source of truth)."""
    data = json.loads(_read_file(".claude-plugin/plugin.json"))
    return data["version"]


def _marketplace_plugin_entry() -> dict:
    """Extract the first plugin entry from marketplace.json."""
    data = json.loads(_read_file(".claude-plugin/marketplace.json"))
    return data["plugins"][0]


def _get_package_json_version() -> str:
    """Extract the version from package.json."""
    data = json.loads(_read_file("package.json"))
    return data["version"]


def _get_install_sh_version() -> str:
    """Extract the VERSION variable from install.sh."""
    content = _read_file("install.sh")
    match = re.search(r'^VERSION="([^"]+)"', content, re.MULTILINE)
    if not match:
        raise ValueError("VERSION=\"...\" not found in install.sh")
    return match.group(1)


def _get_install_ps1_version() -> str:
    """Extract the $Version variable from install.ps1."""
    content = _read_file("install.ps1")
    match = re.search(r'^\$Version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        raise ValueError('$Version = "..." not found in install.ps1')
    return match.group(1)


class TestVersionConsistency(unittest.TestCase):
    """Check that the version is consistent across all files."""

    @classmethod
    def setUpClass(cls):
        """Load the canonical version once."""
        cls.canonical = _get_plugin_json_version()

    def test_canonical_version_is_semver(self):
        """The canonical version must use a valid semver format."""
        self.assertIsNotNone(
            _SEMVER_RE.match(self.canonical),
            f"Version '{self.canonical}' in plugin.json is not valid semver",
        )

    def test_marketplace_json_omits_duplicate_version(self):
        """marketplace.json must not duplicate the canonical version from plugin.json."""
        self.assertNotIn(
            "version",
            _marketplace_plugin_entry(),
            "Claude Code reads the version from plugin.json; a duplicate in marketplace can hide drift",
        )

    def test_package_json_matches(self):
        """package.json must match plugin.json."""
        self.assertEqual(
            _get_package_json_version(),
            self.canonical,
            "The version in package.json does not match plugin.json",
        )

    def test_install_sh_matches(self):
        """install.sh must match plugin.json."""
        self.assertEqual(
            _get_install_sh_version(),
            self.canonical,
            "The version in install.sh does not match plugin.json",
        )

    def test_install_ps1_matches(self):
        """install.ps1 must match plugin.json."""
        self.assertEqual(
            _get_install_ps1_version(),
            self.canonical,
            "The version in install.ps1 does not match plugin.json",
        )


if __name__ == "__main__":
    unittest.main()
