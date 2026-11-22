#!/usr/bin/env python3
"""Tests for the lightweight memory config parser."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.memory_config import (
    DEFAULT_MEMORY_CONFIG,
    is_memory_enabled,
    load_memory_config,
)


class TestMemoryConfig(unittest.TestCase):
    """Check defaults and parsing of the memory block."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._claude_dir = os.path.join(self._tmpdir, ".claude")
        os.makedirs(self._claude_dir, exist_ok=True)
        self._config_path = os.path.join(
            self._claude_dir, "alfred-dev.local.md"
        )

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_defaults_if_config_missing(self):
        """Without a file, return safe defaults."""
        config = load_memory_config(self._tmpdir)
        self.assertFalse(config["enabled"])
        self.assertTrue(config["sync_to_native"])
        self.assertEqual(config["sync_commits_limit"], 10)
        self.assertEqual(config["retention_days"], 365)

    def test_reads_memory_block_from_frontmatter(self):
        """Parse bools and ints from the memory block."""
        with open(self._config_path, "w", encoding="utf-8") as handle:
            handle.write(
                "---\n"
                "optional_agents:\n"
                "  librarian: true\n"
                "memory:\n"
                "  enabled: true\n"
                "  sync_to_native: false\n"
                "  sync_commits_limit: 25\n"
                "  capture_decisions: false\n"
                "  capture_commits: true\n"
                "  retention_days: 14\n"
                "---\n"
            )

        config = load_memory_config(self._tmpdir)
        self.assertTrue(config["enabled"])
        self.assertFalse(config["sync_to_native"])
        self.assertEqual(config["sync_commits_limit"], 25)
        self.assertFalse(config["capture_decisions"])
        self.assertTrue(config["capture_commits"])
        self.assertEqual(config["retention_days"], 14)
        self.assertTrue(is_memory_enabled(self._tmpdir))

    def test_ignores_memory_block_outside_frontmatter(self):
        """Do not enable memory from the Markdown body."""
        with open(self._config_path, "w", encoding="utf-8") as handle:
            handle.write("# Notes\n\nmemory:\n  enabled: true\n")

        config = load_memory_config(self._tmpdir)
        self.assertEqual(config, DEFAULT_MEMORY_CONFIG)
        self.assertFalse(is_memory_enabled(self._tmpdir))

    def test_ignores_unclosed_frontmatter(self):
        """Do not partly apply an unclosed frontmatter."""
        with open(self._config_path, "w", encoding="utf-8") as handle:
            handle.write("---\nmemory:\n  enabled: true\n")

        config = load_memory_config(self._tmpdir)
        self.assertEqual(config, DEFAULT_MEMORY_CONFIG)
        self.assertFalse(is_memory_enabled(self._tmpdir))

    def test_invalid_values_fall_back_to_defaults(self):
        """Semantically invalid values fall back to the default."""
        with open(self._config_path, "w", encoding="utf-8") as handle:
            handle.write(
                "---\n"
                "memory:\n"
                "  enabled: maybe\n"
                "  sync_to_native: 1\n"
                "  sync_commits_limit: 0\n"
                "  capture_decisions: perhaps\n"
                "  capture_commits: nope\n"
                "  retention_days: -5\n"
                "---\n"
            )

        config = load_memory_config(self._tmpdir)
        self.assertEqual(config, DEFAULT_MEMORY_CONFIG)
