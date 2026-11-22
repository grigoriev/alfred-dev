#!/usr/bin/env python3
"""Tests for the canonical generation of style-options.html."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

from core.designer_style_options import (
    build_style_options_payload,
    render_style_options_html,
    write_style_options_html,
)


WRITE_STYLE_OPTIONS_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "visual",
    "scripts",
    "write-style-options.py",
)


class TestDesignerStyleOptions(unittest.TestCase):
    def setUp(self):
        self.project_dir = tempfile.mkdtemp(prefix="alfred-designer-options-")
        self.session_dir = os.path.join(self.project_dir, ".alfred-dev", "visual", "session-1")
        self.state_dir = os.path.join(self.session_dir, "state")
        self.content_dir = os.path.join(self.session_dir, "content")
        os.makedirs(self.state_dir, exist_ok=True)
        os.makedirs(self.content_dir, exist_ok=True)
        self.proposals_path = os.path.join(self.content_dir, "style-options.json")

    def tearDown(self):
        shutil.rmtree(self.project_dir, ignore_errors=True)

    def _write_proposals(self):
        proposals = {
            "proposals": [
                {
                    "choice": "A",
                    "name": "Space dark",
                    "concept": "Dramatic direction with a tech focus.",
                    "palette": {"primario": "#1a1a2e", "acento": "#e94560"},
                    "typography": {"headings": "Space Grotesk", "body": "Inter"},
                    "tone": "Intense and precise",
                    "spacing_density": "Medium, with compact blocks.",
                    "sample_component": "Dashboard hero with status cards.",
                },
                {
                    "choice": "B",
                    "name": "Warm editorial",
                    "description": "Editorial hierarchy and a premium tone.",
                    "palette": {"primario": "#f5f0e8", "texto": "#2c2c2c"},
                    "mood": "Warm and curated",
                    "layout_density": "Airy",
                    "component_example": "Editorial hero with a restrained CTA.",
                },
            ]
        }
        with open(self.proposals_path, "w", encoding="utf-8") as fh:
            json.dump(proposals, fh, ensure_ascii=False, indent=2)

    def test_render_style_options_html_outputs_fragment_cards(self):
        html = render_style_options_html(
            [
                {
                    "choice": "A",
                    "name": "Space dark",
                    "concept": "Dramatic direction.",
                    "palette": [{"role": "primario", "value": "#1a1a2e"}],
                    "typography": {"headings": "Space Grotesk"},
                    "tone": "Intense",
                    "spacing_density": "Medium",
                    "sample_component": "Dashboard hero",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                }
            ]
        )
        self.assertIn('<div class="style-grid">', html)
        self.assertIn('data-choice="A"', html)
        self.assertIn('data-label="Space dark"', html)
        self.assertIn("Space dark", html)
        self.assertNotIn("<!DOCTYPE", html)
        self.assertNotIn("style-viewer.css", html)
        self.assertNotIn("style-viewer.js", html)

    def test_build_style_options_payload_normalizes_sidecar_aliases(self):
        self._write_proposals()

        payload = build_style_options_payload(self.state_dir)
        self.assertEqual(payload["choices"], ["A", "B"])
        self.assertIn("Editorial hierarchy and a premium tone.", payload["html"])
        self.assertIn("Warm and curated", payload["html"])
        self.assertIn("Editorial hero with a restrained CTA.", payload["html"])

    def test_build_style_options_payload_accepts_palette_lists_and_typography_strings(self):
        with open(self.proposals_path, "w", encoding="utf-8") as fh:
            json.dump(
                {
                    "proposals": [
                        {
                            "choice": "A",
                            "name": "Enterprise clarity",
                            "concept": "Professional dashboard with a cool, neutral tone.",
                            "palette": ["#0F172A", "#1E3A5F", "#3B82F6", "#E2E8F0", "#FFFFFF"],
                            "typography": "Inter / DM Sans — geometric sans-serif, high legibility",
                            "tone": "corporate, restrained, reliable",
                            "spacing_density": "dense",
                            "sample_component": "Dark sidebar",
                        }
                    ]
                },
                fh,
                ensure_ascii=False,
                indent=2,
            )

        payload = build_style_options_payload(self.state_dir)
        self.assertIn("#0F172A", payload["html"])
        self.assertIn("#3B82F6", payload["html"])
        self.assertIn("Заголовки: Inter", payload["html"])
        self.assertIn("Основной текст: DM Sans", payload["html"])
        self.assertIn("Заметки: geometric sans-serif, high legibility", payload["html"])

    def test_render_style_options_html_uses_flavor_specific_cards(self):
        html = render_style_options_html(
            [
                {
                    "choice": "A",
                    "name": "Editorial calido",
                    "concept": "Jerarquia editorial y tono premium.",
                    "palette": [{"role": "primario", "value": "#f5f0e8"}],
                    "typography": {"headings": "Fraunces"},
                    "tone": "Calido y curado",
                    "spacing_density": "Aireada",
                    "sample_component": "Hero editorial",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
                {
                    "choice": "B",
                    "name": "Panel operativo",
                    "concept": "Dashboard de control y metricas.",
                    "palette": [{"role": "primario", "value": "#dfeef3"}],
                    "typography": {"headings": "IBM Plex Sans"},
                    "tone": "Preciso",
                    "spacing_density": "Media",
                    "sample_component": "Panel de resumen",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
                {
                    "choice": "C",
                    "name": "Oscuro espacial",
                    "concept": "Direccion futurista de alto contraste.",
                    "palette": [{"role": "primario", "value": "#1a1a2e"}],
                    "typography": {"headings": "Space Grotesk"},
                    "tone": "Intenso",
                    "spacing_density": "Media",
                    "sample_component": "Hero de impacto",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
            ]
        )
        self.assertIn("style-option--editorial", html)
        self.assertIn("style-option--operational", html)
        self.assertIn("style-option--expressive", html)
        self.assertIn("preview-dashboard", html)
        self.assertIn("preview-badge", html)
        self.assertIn("--option-accent:", html)

    def test_render_style_options_html_diversifies_similar_dashboard_proposals(self):
        html = render_style_options_html(
            [
                {
                    "choice": "A",
                    "name": "Enterprise clarity",
                    "concept": "Dashboard profesional de tono frío y neutral, orientado a directivos y analistas.",
                    "palette": [{"role": "surface", "value": "#0F172A"}, {"role": "accent", "value": "#3B82F6"}],
                    "typography": {"headings": "Inter", "body": "DM Sans"},
                    "tone": "corporativo, sobrio, confiable",
                    "spacing_density": "denso",
                    "sample_component": "Barra lateral oscura",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
                {
                    "choice": "B",
                    "name": "Data-dark pro",
                    "concept": "Modo oscuro total al estilo de Grafana o Datadog para monitorización en tiempo real.",
                    "palette": [{"role": "surface", "value": "#111827"}, {"role": "accent", "value": "#10B981"}],
                    "typography": {"headings": "JetBrains Mono", "body": "Geist"},
                    "tone": "técnico, preciso, urgente cuando hay alertas",
                    "spacing_density": "muy denso",
                    "sample_component": "Estados sin sombras",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": ["monitorización 24/7"],
                },
                {
                    "choice": "C",
                    "name": "Modern SaaS clean",
                    "concept": "La estética del SaaS moderno: fondo blanco, whitespace y acentos índigo.",
                    "palette": [{"role": "surface", "value": "#FFFFFF"}, {"role": "accent", "value": "#6366F1"}],
                    "typography": {"headings": "Geist", "body": "Satoshi"},
                    "tone": "moderno, limpio, amigable pero serio",
                    "spacing_density": "cómodo y aireado",
                    "sample_component": "Cards con shadow sutil",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": ["demos y screenshots de marketing"],
                },
            ]
        )
        self.assertIn("style-option--operational", html)
        self.assertIn("style-option--technical", html)
        self.assertIn("style-option--minimal", html)
        self.assertIn("preview-technical-chart", html)
        self.assertIn("preview-product-shell", html)

    def test_render_style_options_html_respects_explicit_preview_flavor(self):
        html = render_style_options_html(
            [
                {
                    "choice": "A",
                    "name": "Expressive signature",
                    "concept": "Lead version of the system.",
                    "style_family": "neo-brutalism",
                    "style_family_label": "Anti-design / Neo-brutalism",
                    "palette": [{"role": "surface", "value": "#fff0b3"}, {"role": "accent", "value": "#111111"}],
                    "typography": {
                        "headings": "Archivo Black",
                        "body": "IBM Plex Mono",
                        "pairing_label": "Brutal Core",
                        "css_url": "https://fonts.googleapis.com/css2?family=Archivo+Black:wght@400;500;700&family=IBM+Plex+Mono:wght@400;500;700&display=swap",
                    },
                    "tone": "Direct",
                    "spacing_density": "Medium",
                    "sample_component": "Brutalist hero",
                    "preview_flavor": "expressive",
                    "variant_label": "Expressive signature",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
                {
                    "choice": "B",
                    "name": "Operational product",
                    "concept": "Most usable version of the system.",
                    "style_family": "neo-brutalism",
                    "style_family_label": "Anti-design / Neo-brutalism",
                    "palette": [{"role": "surface", "value": "#fff0b3"}, {"role": "accent", "value": "#111111"}],
                    "typography": {
                        "headings": "Archivo Black",
                        "body": "Space Grotesk",
                        "pairing_label": "Brutal readable",
                        "css_url": "https://fonts.googleapis.com/css2?family=Archivo+Black:wght@400;500;700&family=Space+Grotesk:wght@400;500;700&display=swap",
                    },
                    "tone": "Clear",
                    "spacing_density": "Medium",
                    "sample_component": "Operational summary",
                    "preview_flavor": "operational",
                    "variant_label": "Operational product",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
            ]
        )
        self.assertIn("style-option--expressive", html)
        self.assertIn("style-option--operational", html)
        self.assertIn("Expressive signature", html)
        self.assertIn("Operational product", html)
        self.assertIn("Pairing: Brutal Core", html)
        self.assertIn("data-label=\"Expressive signature\"", html)
        self.assertIn("style-family--neo-brutalism", html)
        self.assertIn('data-style-family="neo-brutalism"', html)
        self.assertIn("fonts.googleapis.com/css2?family=Archivo+Black", html)
        self.assertIn("--option-heading-font:", html)
        self.assertIn("--option-body-font:", html)
        self.assertIn("--option-accent: #111111", html)
        self.assertIn('preview-brutal preview-brutal--expressive', html)
        self.assertIn('preview-brutal preview-brutal--operational', html)
        self.assertIn("<h4>Expressive signature</h4>", html)
        self.assertIn("<p>Brutalist hero</p>", html)

    def test_render_style_options_html_uses_family_specific_preview_grammars(self):
        html = render_style_options_html(
            [
                {
                    "choice": "A",
                    "name": "Anti-design / Neo-brutalism - Expressive signature",
                    "concept": "Hard borders and offset boxes.",
                    "style_family": "neo-brutalism",
                    "style_family_label": "Anti-design / Neo-brutalism",
                    "palette": [{"role": "surface", "value": "#fff0b3"}, {"role": "accent", "value": "#111111"}],
                    "typography": {"headings": "Archivo Black", "body": "IBM Plex Mono"},
                    "tone": "Direct, ironic and unpolished",
                    "spacing_density": "Medium",
                    "sample_component": "Brutalist hero",
                    "preview_flavor": "expressive",
                    "variant_label": "Expressive signature",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
                {
                    "choice": "B",
                    "name": "Nature distilled / Organic - Base balance",
                    "concept": "Soft curves and editorial warmth.",
                    "style_family": "nature-distilled",
                    "style_family_label": "Nature distilled / Organic",
                    "palette": [{"role": "surface", "value": "#fbf7f1"}, {"role": "accent", "value": "#8c6a42"}],
                    "typography": {"headings": "Cormorant Garamond", "body": "Manrope"},
                    "tone": "Curated, calm and organic",
                    "spacing_density": "Airy",
                    "sample_component": "Organic hero",
                    "preview_flavor": "balanced",
                    "variant_label": "Base balance",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
                {
                    "choice": "C",
                    "name": "Glassmorphism 2.0 - Clean product",
                    "concept": "Translucent panels and soft depth.",
                    "style_family": "glassmorphism-2",
                    "style_family_label": "Glassmorphism 2.0",
                    "palette": [{"role": "surface", "value": "#f4f6ff"}, {"role": "accent", "value": "#7c8cff"}],
                    "typography": {"headings": "Plus Jakarta Sans", "body": "Inter"},
                    "tone": "Soft and technological",
                    "spacing_density": "Airy",
                    "sample_component": "Panel glass",
                    "preview_flavor": "minimal",
                    "variant_label": "Clean product",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
            ]
        )
        self.assertIn("preview-brutal", html)
        self.assertIn("preview-organic", html)
        self.assertIn("style-glass-card", html)
        self.assertIn("preview-brutal-card--hero", html)
        self.assertIn("preview-organic-media", html)
        self.assertIn("style-glass-orb-large", html)

    def test_render_style_options_html_distinguishes_retro_dopamine_kinetic_and_journey(self):
        html = render_style_options_html(
            [
                {
                    "choice": "A",
                    "name": "Maximalism & Neo-retro - Expressive signature",
                    "concept": "Layers and editorial collage.",
                    "style_family": "maximalism-neo-retro",
                    "style_family_label": "Maximalism & Neo-retro",
                    "palette": [{"role": "surface", "value": "#f7cf44"}, {"role": "accent", "value": "#ff4268"}],
                    "typography": {"headings": "Bricolage Grotesque", "body": "Newsreader"},
                    "tone": "Cultural and visible",
                    "spacing_density": "Medium high",
                    "sample_component": "Stacked hero",
                    "preview_flavor": "expressive",
                    "variant_label": "Expressive signature",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
                {
                    "choice": "B",
                    "name": "Dopamine colors - Base balance",
                    "concept": "Fast color and an emotional response.",
                    "style_family": "dopamine-colors",
                    "style_family_label": "Dopamine colors",
                    "palette": [{"role": "surface", "value": "#fff46c"}, {"role": "accent", "value": "#ff275e"}],
                    "typography": {"headings": "Archivo Black", "body": "DM Sans"},
                    "tone": "Energetic",
                    "spacing_density": "Medium",
                    "sample_component": "Impact hero",
                    "preview_flavor": "balanced",
                    "variant_label": "Base balance",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
                {
                    "choice": "C",
                    "name": "Narrative scroll & Gamification - Base balance",
                    "concept": "Story in stages and checkpoints.",
                    "style_family": "narrative-scroll-gamification",
                    "style_family_label": "Narrative scroll & Gamification",
                    "palette": [{"role": "surface", "value": "#eef2ff"}, {"role": "accent", "value": "#2f6fed"}],
                    "typography": {"headings": "Space Grotesk", "body": "Inter"},
                    "tone": "Sequential",
                    "spacing_density": "Medium",
                    "sample_component": "Step rail",
                    "preview_flavor": "balanced",
                    "variant_label": "Base balance",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
            ]
        )
        self.assertIn("preview-retro", html)
        self.assertIn("preview-dopamine", html)
        self.assertIn("preview-journey", html)
        self.assertIn("preview-retro-poster", html)
        self.assertIn("preview-dopamine-bubble", html)
        self.assertIn("preview-journey-topline", html)

    def test_render_style_options_html_uses_full_card_renderer_for_kinetic_family(self):
        html = render_style_options_html(
            [
                {
                    "choice": "A",
                    "name": "Kinetic typography - Editorial narrative",
                    "concept": "Lead headline and typographic rhythm.",
                    "style_family": "kinetic-typography",
                    "style_family_label": "Kinetic typography",
                    "palette_mode_label": "Solid",
                    "palette": [{"role": "surface", "value": "#f8efe6"}, {"role": "accent", "value": "#ff4b2b"}],
                    "typography": {"headings": "Syne", "body": "IBM Plex Sans", "pairing_label": "Kinetic Editorial"},
                    "tone": "Direct and performative",
                    "spacing_density": "Medium",
                    "sample_component": "Typographic hero with a band",
                    "preview_flavor": "editorial",
                    "variant_label": "Editorial narrative",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                }
            ]
        )
        self.assertIn("style-option--kinetic-card", html)
        self.assertIn("style-kinetic-card", html)
        self.assertIn("style-kinetic-headline", html)
        self.assertIn("style-kinetic-specs", html)
        self.assertNotIn('<div class="style-meta">', html)

    def test_render_style_options_html_uses_full_card_renderers_for_lucid_glass_and_depth(self):
        html = render_style_options_html(
            [
                {
                    "choice": "A",
                    "name": "AI Hyperminimalism - Clean product",
                    "concept": "Visual silence and precision.",
                    "style_family": "ai-hyperminimalism",
                    "style_family_label": "AI Hyperminimalism",
                    "palette_mode_label": "Recommended",
                    "palette": [{"role": "surface", "value": "#f7f9fc"}, {"role": "accent", "value": "#7c8cff"}],
                    "typography": {"headings": "Manrope", "body": "Inter", "pairing_label": "Hyperminimal Core"},
                    "tone": "Precise and elegant",
                    "spacing_density": "Airy",
                    "sample_component": "Clean hero",
                    "preview_flavor": "minimal",
                    "variant_label": "Clean product",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
                {
                    "choice": "B",
                    "name": "Glassmorphism 2.0 - Clean product",
                    "concept": "Translucent layers and soft depth.",
                    "style_family": "glassmorphism-2",
                    "style_family_label": "Glassmorphism 2.0",
                    "palette_mode_label": "Recommended",
                    "palette": [{"role": "surface", "value": "#edf4ff"}, {"role": "accent", "value": "#c36bff"}],
                    "typography": {"headings": "Sora", "body": "Manrope", "pairing_label": "Liquid Premium"},
                    "tone": "Polished and soft",
                    "spacing_density": "Balanced",
                    "sample_component": "Panel glass",
                    "preview_flavor": "minimal",
                    "variant_label": "Clean product",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
                {
                    "choice": "C",
                    "name": "Interactive 3D & WebGL - Base balance",
                    "concept": "Lead object and side panel.",
                    "style_family": "interactive-3d-webgl",
                    "style_family_label": "Interactive 3D & WebGL",
                    "palette_mode_label": "Recommended",
                    "palette": [{"role": "surface", "value": "#eef2ff"}, {"role": "accent", "value": "#4f46e5"}],
                    "typography": {"headings": "Sora", "body": "Inter", "pairing_label": "Immersive Sans"},
                    "tone": "Immersive",
                    "spacing_density": "Balanced",
                    "sample_component": "Heroic scene",
                    "preview_flavor": "balanced",
                    "variant_label": "Base balance",
                    "rationale": "",
                    "not_this_direction": [],
                    "tokens": [],
                    "context_signals": [],
                },
            ]
        )
        self.assertIn("style-option--lucid-card", html)
        self.assertIn("style-option--glass-card", html)
        self.assertIn("style-option--depth-card", html)
        self.assertIn("style-lucid-card", html)
        self.assertIn("style-glass-card", html)
        self.assertIn("style-depth-card", html)
        self.assertIn("style-lucid-headline", html)
        self.assertIn("style-glass-orb-large", html)
        self.assertIn("style-depth-object-large", html)
        self.assertNotIn('<div class="style-meta">', html)

    def test_write_style_options_html_writes_fragment_to_content_dir(self):
        self._write_proposals()

        result = write_style_options_html(self.state_dir)
        self.assertEqual(result["status"], "ok")
        html_path = os.path.join(self.content_dir, "style-options.html")
        self.assertEqual(result["html_path"], html_path)
        self.assertTrue(os.path.isfile(html_path))
        with open(html_path, "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("Выбери визуальное направление", content)
        self.assertIn("data-choice=\"B\"", content)

    def test_write_style_options_script_returns_pending_without_sidecar(self):
        result = subprocess.run(
            ["python3", WRITE_STYLE_OPTIONS_SCRIPT, "--visual-path", self.state_dir],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "pending")

    def test_write_style_options_script_writes_html(self):
        self._write_proposals()

        result = subprocess.run(
            [
                "python3",
                WRITE_STYLE_OPTIONS_SCRIPT,
                "--visual-path",
                self.state_dir,
                "--title",
                "Choose a direction",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        with open(payload["html_path"], "r", encoding="utf-8") as fh:
            content = fh.read()
        self.assertIn("Choose a direction", content)


if __name__ == "__main__":
    unittest.main()
