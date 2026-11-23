#!/usr/bin/env python3
"""Tests for the canonical generation of docs/style-direction.md."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from core.designer_style_direction import (
    discover_proposals_file,
    render_style_direction_markdown,
    write_style_direction_artifact,
)


WRITE_STYLE_DIRECTION_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "visual",
    "scripts",
    "write-style-direction.py",
)


class TestDesignerStyleDirection(unittest.TestCase):
    def setUp(self):
        self.project_dir = tempfile.mkdtemp(prefix="alfred-designer-style-")
        self.session_dir = os.path.join(self.project_dir, ".alfred-dev", "visual", "session-1")
        self.state_dir = os.path.join(self.session_dir, "state")
        self.content_dir = os.path.join(self.session_dir, "content")
        os.makedirs(self.state_dir, exist_ok=True)
        os.makedirs(self.content_dir, exist_ok=True)
        self.events_path = os.path.join(self.state_dir, "events")
        self.proposals_path = os.path.join(self.content_dir, "style-options.json")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def _write_fixture_files(self):
        with open(self.events_path, "w", encoding="utf-8") as fh:
            fh.write(
                '{"type":"click","choice":"B","label":"Warm editorial","ts":"2026-04-07T10:00:02Z"}\n'
            )

        proposals = {
            "proposals": [
                {
                    "choice": "A",
                    "name": "Space dark",
                    "concept": "High visual density with a tech focus.",
                },
                {
                    "choice": "B",
                    "name": "Warm editorial",
                    "concept": "An interface with editorial hierarchy and a premium tone.",
                    "palette": {
                        "primary": "#f5f0e8",
                        "secondary": "#c8a96e",
                        "text": "#2c2c2c",
                    },
                    "typography": {
                        "headings": "Fraunces",
                        "body": "Source Sans 3",
                        "scale": "16 / 20 / 28 / 40",
                    },
                    "spacing_density": "Airy, with breathing blocks and an editorial rhythm.",
                    "tone": "Warm editorial",
                    "sample_component": "Summary card with a serif headline, short metrics and a restrained CTA.",
                    "visual_principles": [
                        "Editorial calm with a visible hierarchy.",
                        "Lots of air and a curated reading rhythm.",
                    ],
                    "layout_grammar": "Lead headline + support block + restrained CTA.",
                    "surface_treatment": "Cream fields with soft contrast and minimal elevation.",
                    "shape_language": "Calm cards and discreet pills.",
                    "motion_language": "Soft, restrained transitions.",
                    "signature_elements": ["Serif headline", "Editorial block", "Restrained CTA"],
                    "implementation_guardrails": [
                        "Do not turn the direction into a dense technical dashboard."
                    ],
                    "prompt_seed": "Keep a warm, curated editorial direction.",
                    "rationale": "Fits a product that must convey judgment and trust.",
                    "not_this_direction": [
                        "Not a dense or hyper-technical dashboard UI.",
                        "Not a generic startup look.",
                    ],
                    "tokens": {
                        "color.bg.canvas": "#f5f0e8",
                        "color.text.primary": "#2c2c2c",
                    },
                    "context_signals": [
                        "Non-technical professional audience.",
                        "Need to convey calm and credibility.",
                    ],
                },
            ]
        }
        with open(self.proposals_path, "w", encoding="utf-8") as fh:
            json.dump(proposals, fh, ensure_ascii=False, indent=2)

    def test_discover_proposals_file_prefers_content_style_options_json(self):
        self._write_fixture_files()
        self.assertEqual(discover_proposals_file(self.state_dir), self.proposals_path)

    def test_write_style_direction_artifact_renders_selected_proposal(self):
        self._write_fixture_files()

        result = write_style_direction_artifact(self.project_dir, self.state_dir)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["choice"], "B")

        artifact_path = os.path.join(self.project_dir, "docs", "style-direction.md")
        with open(artifact_path, "r", encoding="utf-8") as fh:
            content = fh.read()

        self.assertIn(
            "Designer рекомендует `B` — Warm editorial как базовую дизайн-систему для этой фазы.",
            content,
        )
        self.assertIn("## Почему выигрывает этот вариант", content)
        self.assertIn("Fraunces", content)
        self.assertIn("Not a dense or hyper-technical dashboard UI.", content)
        self.assertIn("color.bg.canvas", content)
        self.assertIn("## Выполнимые принципы системы", content)
        self.assertIn("### Грамматика композиции", content)
        self.assertIn("### Guardrails реализации", content)
        self.assertIn("## Зерно направления", content)
        self.assertIn("Исходные предложения: `content/style-options.json`", content)

    def test_render_style_direction_markdown_has_required_sections(self):
        record = {
            "generated_at": "2026-04-07T10:00:02Z",
            "choice": "C",
            "selected_label": "Vibrant minimalism",
            "selected_at": "2026-04-07T10:00:02Z",
            "proposals_file": "/tmp/style-options.json",
            "proposal": {
                "choice": "C",
                "name": "Vibrant minimalism",
                "concept": "Clean system with an energetic accent.",
                "palette": [{"role": "primary", "value": "#0d7377"}],
                "typography": {"headings": "Sora", "body": "Inter"},
                "spacing_density": "Airy",
                "tone": "Modern and light",
                "sample_component": "Card dashboard focused on highlights.",
                "visual_principles": ["Instant clarity", "Energetic contrast"],
                "layout_grammar": "Clean hero with light supporting cards.",
                "surface_treatment": "Clean backgrounds with a single vibrant accent.",
                "shape_language": "Soft cards and restrained geometry.",
                "motion_language": "Short, clean micro-transitions.",
                "signature_elements": ["Vibrant accent", "Lots of air"],
                "implementation_guardrails": ["Do not overload the screen with too many layers."],
                "prompt_seed": "Keep a minimal, highly focused direction.",
                "rationale": "Suits a clear, visual product.",
                "not_this_direction": ["Not restrained corporate."],
                "tokens": [{"name": "color.brand.primary", "value": "#0d7377"}],
                "context_signals": ["Product focused on visual discovery."],
            },
        }
        content = render_style_direction_markdown(record)
        self.assertIn("## Выбранная дизайн-система", content)
        self.assertIn("## Почему выигрывает этот вариант", content)
        self.assertIn("## Чем эта система НЕ является", content)
        self.assertIn("## Предлагаемые начальные токены", content)
        self.assertIn("## Выполнимые принципы системы", content)
        self.assertIn("## Зерно направления", content)
        self.assertIn("Product focused on visual discovery.", content)

    def test_render_style_direction_markdown_uses_basename_when_project_context_missing(self):
        record = {
            "generated_at": "2026-04-07T10:00:02Z",
            "choice": "A",
            "selected_label": "Space dark",
            "selected_at": "",
            "proposals_file": "/tmp/nested/style-options.json",
            "proposal": {
                "choice": "A",
                "name": "Space dark",
                "concept": "",
                "palette": [],
                "typography": {},
                "spacing_density": "",
                "tone": "",
                "sample_component": "",
                "rationale": "",
                "not_this_direction": [],
                "tokens": [],
                "context_signals": [],
            },
        }

        content = render_style_direction_markdown(record)
        self.assertIn("Исходные предложения: `style-options.json`", content)
        self.assertNotIn("../../", content)

    def test_render_style_direction_markdown_shows_variant_and_pairing_metadata(self):
        record = {
            "generated_at": "2026-04-07T10:00:02Z",
            "choice": "B",
            "selected_label": "Operational product",
            "selected_at": "2026-04-07T10:00:02Z",
            "proposals_file": "/tmp/style-options.json",
            "proposal": {
                "choice": "B",
                "name": "Anti-design / Neo-brutalism - Operational product",
                "concept": "Brutalist direction grounded in a real product.",
                "style_family": "neo-brutalism",
                "style_family_label": "Anti-design / Neo-brutalism",
                "palette_mode": "solid",
                "palette_mode_label": "Solid",
                "variant_label": "Operational product",
                "palette": [{"role": "surface", "value": "#fff0b3"}],
                "typography": {
                    "pairing_id": "brutal-readable",
                    "pairing_label": "Brutal readable",
                    "headings": "Archivo Black",
                    "body": "Space Grotesk",
                },
                "spacing_density": "Medium",
                "tone": "Direct and clear",
                "sample_component": "Operational summary with hard blocks.",
                "rationale": "Suits continuous product use.",
                "not_this_direction": ["Not the most editorial variant."],
                "tokens": [],
                "context_signals": [],
            },
        }

        content = render_style_direction_markdown(record)
        self.assertIn("Финальный вариант: **Operational product**", content)
        self.assertIn("Режим палитры: **Solid**", content)
        self.assertIn("Pairing: Brutal readable", content)
        self.assertIn("Id pairing: `brutal-readable`", content)

    def test_sparse_proposal_gets_semantic_defaults(self):
        with open(self.events_path, "w", encoding="utf-8") as fh:
            fh.write(
                '{"type":"click","choice":"A","label":"Warm editorial","ts":"2026-04-07T10:00:02Z"}\n'
            )
        with open(self.proposals_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "proposals": [
                        {
                            "choice": "A",
                            "name": "Warm editorial",
                            "palette": {"primary": "#f5f0e8"},
                            "typography": {"headings": "Fraunces"},
                        }
                    ]
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )

        result = write_style_direction_artifact(self.project_dir, self.state_dir)
        self.assertEqual(result["status"], "ok")

        artifact_path = os.path.join(self.project_dir, "docs", "style-direction.md")
        with open(artifact_path, "r", encoding="utf-8") as fh:
            content = fh.read()

        self.assertIn("Редакционный язык с ясной иерархией", content)
        self.assertIn("Подходит, когда продукту нужно передать вкус", content)
        self.assertIn("Редакционный hero с главным заголовком", content)
        self.assertIn("## Выполнимые принципы системы", content)
        self.assertIn("## Зерно направления", content)
        self.assertIn("Это не плотный dashboard UI", content)
        self.assertIn("Нужно передать вкус, спокойствие и ощущение заботы.", content)

    def test_sidecar_alias_fields_are_normalized(self):
        with open(self.events_path, "w", encoding="utf-8") as fh:
            fh.write(
                '{"type":"click","choice":"C","label":"Vibrant minimalism","ts":"2026-04-07T10:00:02Z"}\n'
            )
        with open(self.proposals_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "proposals": [
                        {
                            "choice": "C",
                            "title": "Vibrant minimalism",
                            "description": "Clean system with an energetic accent.",
                            "mood": "Light and crisp",
                            "layout_density": "Very airy",
                            "component_example": "Hero with a short claim and a dominant CTA.",
                            "why": "Helps reduce visual noise from the first screen.",
                            "anti_patterns": ["Not an ornamental interface."],
                            "audience": "Product team with little reading time",
                        }
                    ]
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )

        result = write_style_direction_artifact(self.project_dir, self.state_dir)
        self.assertEqual(result["status"], "ok")

        artifact_path = os.path.join(self.project_dir, "docs", "style-direction.md")
        with open(artifact_path, "r", encoding="utf-8") as fh:
            content = fh.read()

        self.assertIn("Clean system with an energetic accent.", content)
        self.assertIn("Light and crisp", content)
        self.assertIn("Very airy", content)
        self.assertIn("Hero with a short claim and a dominant CTA.", content)
        self.assertIn("Helps reduce visual noise from the first screen.", content)
        self.assertIn("Not an ornamental interface.", content)
        self.assertIn("Product team with little reading time", content)

    def test_write_style_direction_script_returns_pending_without_choice(self):
        with open(self.proposals_path, "w", encoding="utf-8") as fh:
            json.dump({"A": {"name": "Space dark"}}, fh)

        result = subprocess.run(
            [
                "python3",
                WRITE_STYLE_DIRECTION_SCRIPT,
                "--project-dir",
                self.project_dir,
                "--visual-path",
                self.state_dir,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pending")

    def test_write_style_direction_script_writes_artifact(self):
        self._write_fixture_files()

        result = subprocess.run(
            [
                "python3",
                WRITE_STYLE_DIRECTION_SCRIPT,
                "--project-dir",
                self.project_dir,
                "--visual-path",
                self.state_dir,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertTrue(os.path.isfile(payload["artifact_path"]))


if __name__ == "__main__":
    unittest.main()
