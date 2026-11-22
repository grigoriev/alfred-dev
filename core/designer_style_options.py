#!/usr/bin/env python3
"""Canonical generation of style-options.html for Designer."""

from __future__ import annotations

import html
import os
import re
from typing import Any, Dict, List, Optional

from core.designer_style_direction import (
    discover_proposals_file,
    load_style_proposals,
    resolve_visual_session_dir,
)


STYLE_OPTIONS_HTML_FILENAME = "style-options.html"
VALID_OPTION_FLAVORS = ("editorial", "technical", "operational", "minimal", "expressive", "balanced")
GENERIC_FONT_FAMILIES = {
    "serif",
    "sans-serif",
    "monospace",
    "cursive",
    "fantasy",
    "system-ui",
    "ui-sans-serif",
    "ui-serif",
    "ui-monospace",
}


def _escape(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _class_token(value: Any) -> str:
    token = re.sub(r"[^a-z0-9]+", "-", _clean_text(value).lower()).strip("-")
    return token or "unknown"


def _truncate_text(value: Any, max_chars: int) -> str:
    text = _clean_text(value)
    if len(text) <= max_chars:
        return text
    clipped = text[: max_chars + 1].rsplit(" ", 1)[0].strip()
    clipped = clipped or text[:max_chars].strip()
    return f"{clipped}…"


def _sentence(value: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    return text if text[-1] in ".!?" else f"{text}."


def _semantic_source_text(proposal: Dict[str, Any]) -> str:
    return " ".join(
        part
        for part in [
            proposal.get("name", ""),
            proposal.get("concept", ""),
            proposal.get("tone", ""),
            proposal.get("rationale", ""),
            " ".join(item.get("role", "") for item in (proposal.get("palette") or [])),
            " ".join(proposal.get("context_signals", [])),
        ]
        if part
    ).lower()


def _matches_any(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _palette_surface_luminance(proposal: Dict[str, Any]) -> float:
    palette = _extract_palette_values(proposal)
    if not palette:
        return 1.0
    return _relative_luminance(palette[0])


def _candidate_option_flavors(proposal: Dict[str, Any]) -> List[str]:
    text = _semantic_source_text(proposal)
    luminance = _palette_surface_luminance(proposal)
    candidates: List[str] = []

    def add(flavor: str, condition: bool) -> None:
        if condition and flavor not in candidates:
            candidates.append(flavor)

    add(
        "technical",
        _matches_any(
            text,
            ["grafana", "datadog", "monitor", "real-time", "24/7", "alert", "observability", "мониторинг", "реальном времени", "семантич", "алерт"],
        )
    )
    add("editorial", _matches_any(text, ["editorial", "premium", "serif", "magazine", "luxury", "редакцион", "журнал", "премиал", "роскош"]))
    add(
        "minimal",
        _matches_any(text, ["minimal", "clean", "linear", "notion", "attio", "whitespace", "минимал", "чист", "воздушн", "ясност"])
        or (
            luminance > 0.92
            and _matches_any(text, ["saas", "modern", "white", "light", "современ", "бел", "лёгк", "легк"])
        ),
    )
    add("operational", _matches_any(text, ["dashboard", "metric", "analytic", "control", "panel", "enterprise", "tableau", "power bi", "дашборд", "операцион", "метрик", "аналитик", "контрол", "панел"]))
    add("expressive", _matches_any(text, ["vibrant", "futur", "expressive", "bold", "impact", "memorable", "ярк", "пространств", "футур", "выразительн", "смел", "запомина"]))
    add("balanced", True)

    for flavor in ("operational", "minimal", "editorial", "technical", "expressive", "balanced"):
        if flavor not in candidates:
            candidates.append(flavor)
    return candidates


def _assign_option_flavors(proposals: List[Dict[str, Any]]) -> Dict[str, str]:
    assigned: Dict[str, str] = {}
    used: set[str] = set()

    for proposal in proposals:
        choice = str(proposal.get("choice", "")).strip()
        if not choice:
            continue
        explicit = str(proposal.get("preview_flavor", "")).strip()
        if explicit in VALID_OPTION_FLAVORS:
            assigned[choice] = explicit
            used.add(explicit)
            continue
        candidates = _candidate_option_flavors(proposal)
        selected = next((flavor for flavor in candidates if flavor not in used), candidates[0])
        assigned[choice] = selected
        used.add(selected)

    return assigned


def _extract_palette_values(proposal: Dict[str, Any]) -> List[str]:
    return [
        value
        for value in (item.get("value", "") for item in (proposal.get("palette") or []))
        if isinstance(value, str) and value.strip().startswith("#")
    ]


def _palette_role_map(proposal: Dict[str, Any]) -> Dict[str, str]:
    roles: Dict[str, str] = {}
    palette = proposal.get("palette") or []
    if isinstance(palette, list):
        for item in palette:
            if not isinstance(item, dict):
                continue
            role = _clean_text(item.get("role") or item.get("name")).lower()
            value = _clean_text(item.get("value") or item.get("color"))
            if role and value and role not in roles:
                roles[role] = value

    if roles:
        return roles

    values = _extract_palette_values(proposal)
    default_roles = ("surface", "surface_alt", "accent", "accent_alt", "ink", "muted")
    return {
        role: value
        for role, value in zip(default_roles, values)
        if value
    }


def _hex_to_rgba(color: str, alpha: float) -> str:
    raw = color.strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return f"rgba(184, 92, 56, {alpha})"
    try:
        red = int(raw[0:2], 16)
        green = int(raw[2:4], 16)
        blue = int(raw[4:6], 16)
    except ValueError:
        return f"rgba(184, 92, 56, {alpha})"
    return f"rgba({red}, {green}, {blue}, {alpha})"


def _relative_luminance(color: str) -> float:
    raw = color.strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return 1.0
    try:
        channels = [int(raw[idx:idx + 2], 16) / 255 for idx in range(0, 6, 2)]
    except ValueError:
        return 1.0

    def linearize(value: float) -> float:
        if value <= 0.03928:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = [linearize(channel) for channel in channels]
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _option_theme(proposal: Dict[str, Any], flavor: str) -> Dict[str, str]:
    defaults = {
        "editorial": {"accent": "#b85c38", "accent_alt": "#6f4633", "surface": "#f6ede3"},
        "technical": {"accent": "#10b981", "accent_alt": "#0f766e", "surface": "#0f172a"},
        "operational": {"accent": "#2d6f7f", "accent_alt": "#1f4c56", "surface": "#eef5f7"},
        "minimal": {"accent": "#5f6c73", "accent_alt": "#364247", "surface": "#f1f3f2"},
        "expressive": {"accent": "#7b3256", "accent_alt": "#351d41", "surface": "#f4e7ef"},
        "balanced": {"accent": "#6c5a4d", "accent_alt": "#3d322c", "surface": "#f3eee8"},
    }[flavor]
    roles = _palette_role_map(proposal)
    surface = roles.get("surface") or defaults["surface"]
    surface_alt = roles.get("surface_alt") or roles.get("accent_alt") or defaults["accent_alt"]
    accent = roles.get("accent") or defaults["accent"]
    accent_alt = roles.get("accent_alt") or surface_alt or defaults["accent_alt"]
    ink = roles.get("ink") or ("#fffaf5" if _relative_luminance(surface) < 0.28 else "#201714")
    muted = roles.get("muted") or _hex_to_rgba(ink, 0.72 if ink.startswith("#fff") else 0.68)
    is_dark_surface = _relative_luminance(surface) < 0.28
    return {
        "accent": accent,
        "accent_soft": _hex_to_rgba(accent, 0.18),
        "accent_glow": _hex_to_rgba(accent, 0.3),
        "accent_alt": accent_alt,
        "accent_alt_soft": _hex_to_rgba(accent_alt, 0.18),
        "surface": surface,
        "surface_alt": surface_alt,
        "surface_soft": _hex_to_rgba(surface, 0.86 if not is_dark_surface else 0.24),
        "surface_alt_soft": _hex_to_rgba(surface_alt, 0.2 if not is_dark_surface else 0.32),
        "ink": ink,
        "muted": muted,
        "border": _hex_to_rgba(ink, 0.12 if not is_dark_surface else 0.24),
        "border_strong": _hex_to_rgba(ink, 0.22 if not is_dark_surface else 0.4),
        "grid": _hex_to_rgba(ink, 0.08 if not is_dark_surface else 0.18),
    }


def _font_stack(font_name: Any, fallback_var: str) -> str:
    text = _clean_text(font_name)
    if not text:
        return fallback_var
    parts = [part.strip() for part in text.split(",") if part.strip()]
    if not parts:
        return fallback_var

    quoted_parts: List[str] = []
    for part in parts:
        lowered = part.lower()
        if lowered in GENERIC_FONT_FAMILIES or part.startswith(("var(", '"', "'")):
            quoted_parts.append(part)
        else:
            quoted_parts.append(f'"{part}"')
    quoted_parts.append(fallback_var)
    return ", ".join(quoted_parts)


def _typography_theme(proposal: Dict[str, Any]) -> Dict[str, str]:
    typography = proposal.get("typography") or {}
    return {
        "heading_font": _font_stack(typography.get("headings"), "var(--font-display)"),
        "body_font": _font_stack(typography.get("body"), "var(--font-sans)"),
    }


def _option_style_attr(theme: Dict[str, str]) -> str:
    style = "; ".join(
        [
            f"--option-accent: {theme['accent']}",
            f"--option-accent-soft: {theme['accent_soft']}",
            f"--option-accent-glow: {theme['accent_glow']}",
            f"--option-accent-alt: {theme['accent_alt']}",
            f"--option-accent-alt-soft: {theme['accent_alt_soft']}",
            f"--option-surface: {theme['surface']}",
            f"--option-surface-alt: {theme['surface_alt']}",
            f"--option-surface-soft: {theme['surface_soft']}",
            f"--option-surface-alt-soft: {theme['surface_alt_soft']}",
            f"--option-ink: {theme['ink']}",
            f"--option-muted: {theme['muted']}",
            f"--option-border: {theme['border']}",
            f"--option-border-strong: {theme['border_strong']}",
            f"--option-grid: {theme['grid']}",
        ]
    )
    return _escape(style)


def _option_typography_attr(proposal: Dict[str, Any]) -> str:
    typography_theme = _typography_theme(proposal)
    style = "; ".join(
        [
            f"--option-heading-font: {typography_theme['heading_font']}",
            f"--option-body-font: {typography_theme['body_font']}",
        ]
    )
    return _escape(style)


def _font_imports_markup(proposals: List[Dict[str, Any]]) -> str:
    imports: List[str] = []
    for proposal in proposals:
        typography = proposal.get("typography") or {}
        for key in ("css_url", "custom_url"):
            url = _clean_text(typography.get(key))
            if url.startswith(("http://", "https://")) and url not in imports:
                imports.append(url)
    if not imports:
        return ""
    rules = "".join(f'@import url("{url}");' for url in imports)
    return f'<style class="style-font-imports">{rules}</style>'


def _preview_background(proposal: Dict[str, Any]) -> str:
    palette = proposal.get("palette") or []
    if palette:
        return palette[0].get("value") or "rgba(128, 128, 128, 0.08)"
    return "rgba(128, 128, 128, 0.08)"


def _palette_markup(palette: List[Dict[str, str]]) -> str:
    if not palette:
        return ""

    items = []
    for item in palette[:4]:
        value = _escape(item.get("value", ""))
        role = _escape(item.get("role", ""))
        items.append(
            '<div class="palette-dot">'
            f'<span class="dot" style="background:{value};" title="{role}: {value}"></span>'
            f'<span class="hex">{value}</span>'
            "</div>"
        )
    return '<div class="palette">' + "".join(items) + "</div>"


def _reference_links_markup(reference_urls: List[Dict[str, str]]) -> str:
    if not reference_urls:
        return ""

    links = []
    for item in reference_urls[:3]:
        label = _escape(item.get("label", "Референс"))
        url = _escape(item.get("url", ""))
        if not url:
            continue
        links.append(
            f'<a class="style-link" href="{url}" target="_blank" rel="noreferrer">{label}</a>'
        )
    if not links:
        return ""
    return '<div class="style-links">' + "".join(links) + "</div>"


def _typography_links_markup(typography: Dict[str, str]) -> str:
    links = []
    if typography.get("headings_url"):
        links.append(
            f'<a class="style-link" href="{_escape(typography["headings_url"])}" target="_blank" rel="noreferrer">Headings</a>'
        )
    if typography.get("body_url"):
        links.append(
            f'<a class="style-link" href="{_escape(typography["body_url"])}" target="_blank" rel="noreferrer">Body</a>'
        )
    if typography.get("custom_url"):
        links.append(
            f'<a class="style-link" href="{_escape(typography["custom_url"])}" target="_blank" rel="noreferrer">Custom</a>'
        )
    if not links:
        return ""
    return '<div class="style-links style-links--fonts">' + "".join(links) + "</div>"


def _typography_summary(proposal: Dict[str, Any]) -> str:
    typography = proposal.get("typography") or {}
    parts = []
    if typography.get("pairing_label"):
        parts.append(f"Pairing: {typography['pairing_label']}")
    if typography.get("headings"):
        parts.append(f"Заголовки: {typography['headings']}")
    if typography.get("body"):
        parts.append(f"Основной текст: {typography['body']}")
    if typography.get("scale"):
        parts.append(f"Шкала: {typography['scale']}")
    if typography.get("notes"):
        parts.append(f"Заметки: {typography['notes']}")
    return " · ".join(parts)


def _preview_title_text(proposal: Dict[str, Any]) -> str:
    candidates = [
        proposal.get("preview_title"),
        proposal.get("variant_label"),
        proposal.get("name"),
        proposal.get("concept"),
    ]
    for candidate in candidates:
        text = _clean_text(candidate)
        if text:
            return _truncate_text(text, 42)
    return "Визуальное направление"


def _preview_body_text(proposal: Dict[str, Any], fallback: str) -> str:
    candidates = [
        proposal.get("preview_copy"),
        proposal.get("sample_component"),
        proposal.get("tone"),
        proposal.get("concept"),
        fallback,
    ]
    for candidate in candidates:
        text = _clean_text(candidate)
        if text:
            return _truncate_text(text, 96)
    return ""


def _preview_note_text(proposal: Dict[str, Any]) -> str:
    candidates = [
        proposal.get("preview_note"),
        proposal.get("variant_label"),
        proposal.get("palette_mode_label"),
        proposal.get("palette_mode"),
        proposal.get("tone"),
    ]
    for candidate in candidates:
        text = _clean_text(candidate)
        if text:
            return _truncate_text(text, 36)
    return ""


def _context_summary(proposal: Dict[str, Any]) -> str:
    return (
        proposal.get("concept")
        or proposal.get("rationale")
        or ((proposal.get("context_signals") or [None])[0])
        or ""
    )


def _style_family_id(proposal: Dict[str, Any]) -> str:
    return _class_token(proposal.get("style_family") or proposal.get("style_family_label") or "")


def _variant_badge_text(proposal: Dict[str, Any], fallback: str) -> str:
    candidates = [
        proposal.get("variant_label"),
        proposal.get("preview_note"),
        proposal.get("palette_mode_label"),
        proposal.get("palette_mode"),
        fallback,
    ]
    for candidate in candidates:
        text = _clean_text(candidate)
        if text:
            return _truncate_text(text, 22)
    return fallback


def _preview_editorial(proposal: Dict[str, Any]) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, "Спокойствие, вкус и иерархия"))
    return (
        '<div class="preview-editorial">'
        '<div class="mock-nav"><span></span><span></span><span></span></div>'
        '<p class="preview-kicker">Визуальная редакция</p>'
        '<div class="mock-hero preview-hero preview-hero--editorial">'
        f"<h4>{title}</h4>"
        f"<p>{body}</p>"
        '<span class="mock-button">Читать предложение</span>'
        "</div>"
        '<div class="preview-lines"><span></span><span></span><span></span></div>'
        "</div>"
    )


def _preview_operational(proposal: Dict[str, Any]) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, _context_summary(proposal)))
    return (
        '<div class="preview-dashboard">'
        '<div class="preview-metrics">'
        '<div class="preview-stat"><strong>72%</strong><span>Внедрение</span></div>'
        '<div class="preview-stat"><strong>4.2</strong><span>Фокус</span></div>'
        "</div>"
        '<div class="mock-card preview-card preview-card--wide">'
        f"<h5>{title}</h5>"
        f"<p>{body}</p>"
        "</div>"
        '<div class="preview-bar-group"><span></span><span></span><span></span></div>'
        "</div>"
    )


def _preview_technical(proposal: Dict[str, Any]) -> str:
    return (
        '<div class="preview-technical">'
        '<div class="preview-technical-header">'
        '<span class="preview-status-pill preview-status-pill--ok">Stable</span>'
        '<span class="preview-status-pill preview-status-pill--warn">1 alert</span>'
        "</div>"
        '<div class="preview-technical-chart"></div>'
        '<div class="preview-technical-grid">'
        '<div class="preview-technical-panel"></div>'
        '<div class="preview-technical-panel preview-technical-panel--accent"></div>'
        '<div class="preview-technical-panel"></div>'
        "</div>"
        '<div class="preview-technical-lines"><span></span><span></span><span></span></div>'
        "</div>"
    )


def _preview_minimal(proposal: Dict[str, Any]) -> str:
    title = _escape(_preview_title_text(proposal))
    tone = _escape(_preview_body_text(proposal, "Сдержанно и сфокусированно"))
    return (
        '<div class="preview-minimal">'
        '<div class="preview-product-topline"><span></span><span></span><span></span></div>'
        '<div class="preview-product-shell">'
        '<div class="preview-product-copy">'
        '<p class="preview-product-kicker">Product system</p>'
        f"<h4>{title}</h4>"
        f"<p>{tone}</p>"
        '<div class="preview-product-actions">'
        '<span class="mock-button">Продолжить</span>'
        '<span class="preview-product-ghost">Смотреть демо</span>'
        "</div>"
        "</div>"
        '<div class="preview-product-panel">'
        '<div class="preview-product-stat"><strong>99.9%</strong><span>uptime</span></div>'
        '<div class="preview-product-chart"></div>'
        "</div>"
        "</div>"
        '<div class="preview-product-cards">'
        '<div class="preview-product-card"></div>'
        '<div class="preview-product-card preview-product-card--accent"></div>'
        "</div>"
        '<div class="preview-balance-line"></div>'
        "</div>"
    )


def _preview_expressive(proposal: Dict[str, Any]) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, "Выразительно и запоминающе"))
    return (
        '<div class="preview-expressive">'
        '<div class="preview-badge">Эффект</div>'
        '<div class="mock-hero preview-hero preview-hero--expressive">'
        f"<h4>{title}</h4>"
        f"<p>{body}</p>"
        '<span class="mock-button">Смотреть айдентику</span>'
        "</div>"
        '<div class="preview-stack">'
        '<div class="preview-panel"></div><div class="preview-panel preview-panel--alt"></div>'
        "</div>"
        "</div>"
    )


def _preview_balanced(proposal: Dict[str, Any]) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, "Баланс и ясность"))
    return (
        '<div class="preview-balanced">'
        '<div class="mock-nav"><span></span><span></span><span></span></div>'
        '<div class="mock-hero preview-hero">'
        f"<h4>{title}</h4>"
        f"<p>{body}</p>"
        '<span class="mock-button">Главный CTA</span>'
        "</div>"
        '<div class="mock-card preview-card">'
        f"<h5>{title}</h5>"
        f"<p>{body}</p>"
        "</div>"
        "</div>"
    )


def _preview_brutal_family(proposal: Dict[str, Any], flavor: str) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, _context_summary(proposal)))
    badge = _escape(_variant_badge_text(proposal, "Brutal"))
    palette = _escape(_variant_badge_text({"variant_label": proposal.get("palette_mode_label")}, "Плотная"))
    if flavor == "operational":
        return (
            '<div class="preview-brutal preview-brutal--operational">'
            '<div class="preview-brutal-metrics">'
            '<div class="preview-brutal-metric"><strong>72%</strong><span>внедрение</span></div>'
            '<div class="preview-brutal-metric"><strong>4.2</strong><span>фокус</span></div>'
            "</div>"
            '<div class="preview-brutal-card preview-brutal-card--board">'
            f'<p class="preview-brutal-kicker">{badge}</p>'
            f"<h4>{title}</h4>"
            f"<p>{body}</p>"
            '<div class="preview-brutal-row preview-brutal-row--bars"><span></span><span></span><span></span></div>'
            "</div>"
            "</div>"
        )
    if flavor == "minimal":
        return (
            '<div class="preview-brutal preview-brutal--minimal">'
            '<div class="preview-brutal-topline">'
            f"<span>{palette}</span><span>{badge}</span>"
            "</div>"
            '<div class="preview-brutal-split">'
            '<div class="preview-brutal-card preview-brutal-card--copy">'
            f"<h4>{title}</h4>"
            f"<p>{body}</p>"
            '<span class="mock-button">Продолжить</span>'
            "</div>"
            '<div class="preview-brutal-card preview-brutal-card--stat">'
            '<strong>99.9%</strong>'
            '<span>uptime</span>'
            '<div class="preview-brutal-mini-chart"></div>'
            "</div>"
            "</div>"
            '<div class="preview-brutal-row"><span></span><span></span></div>'
            "</div>"
        )
    return (
        '<div class="preview-brutal preview-brutal--expressive">'
        '<div class="preview-brutal-stickers">'
        f"<span>{badge}</span><span>{palette}</span>"
        "</div>"
        '<div class="preview-brutal-board">'
        '<div class="preview-brutal-shadow"></div>'
        '<div class="preview-brutal-card preview-brutal-card--hero">'
        f"<h4>{title}</h4>"
        f"<p>{body}</p>"
        '<span class="mock-button">Смотреть айдентику</span>'
        "</div>"
        "</div>"
        '<div class="preview-brutal-row"><span></span><span></span><span></span></div>'
        "</div>"
    )


def _preview_organic_family(proposal: Dict[str, Any], flavor: str) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, "Тепло, органично и продуманно"))
    badge = _escape(_variant_badge_text(proposal, "Земляная"))
    if flavor == "minimal":
        return (
            '<div class="preview-organic preview-organic--minimal">'
            '<div class="preview-organic-header">'
            f'<span class="preview-organic-chip">{badge}</span>'
            '<span class="preview-organic-line"></span>'
            "</div>"
            '<div class="preview-organic-shell">'
            '<div class="preview-organic-copy">'
            f"<h4>{title}</h4>"
            f"<p>{body}</p>"
            "</div>"
            '<div class="preview-organic-card preview-organic-card--quiet"></div>'
            "</div>"
            '<div class="preview-organic-pills"><span></span><span></span><span></span></div>'
            "</div>"
        )
    if flavor == "balanced":
        return (
            '<div class="preview-organic preview-organic--balanced">'
            '<div class="preview-organic-media"></div>'
            '<div class="preview-organic-bottom">'
            '<div class="preview-organic-copy">'
            f'<p class="preview-kicker">{badge}</p>'
            f"<h4>{title}</h4>"
            f"<p>{body}</p>"
            "</div>"
            '<div class="preview-organic-card preview-organic-card--stat"><strong>03</strong><span>ритма</span></div>'
            "</div>"
            "</div>"
        )
    return (
        '<div class="preview-organic preview-organic--editorial">'
        '<div class="preview-organic-hero">'
        '<div class="preview-organic-media preview-organic-media--tall"></div>'
        '<div class="preview-organic-copy">'
        f'<p class="preview-kicker">{badge}</p>'
        f"<h4>{title}</h4>"
        f"<p>{body}</p>"
        '<span class="preview-product-ghost">Читать спокойно</span>'
        "</div>"
        "</div>"
        '<div class="preview-organic-pills"><span></span><span></span><span></span></div>'
        "</div>"
    )


def _preview_glass_family(proposal: Dict[str, Any], flavor: str) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, "Мягкие слои и сдержанная глубина"))
    badge = _escape(_variant_badge_text(proposal, "Glass"))
    if flavor == "technical":
        return (
            '<div class="preview-glass preview-glass--technical">'
            '<div class="preview-glass-topline"><span></span><span></span><span></span></div>'
            '<div class="preview-glass-stack">'
            '<div class="preview-glass-panel preview-glass-panel--data">'
            '<div class="preview-glass-chiprow"><span>OK</span><span>Задержка</span></div>'
            '<div class="preview-glass-orb preview-glass-orb--small"></div>'
            "</div>"
            '<div class="preview-glass-panel preview-glass-panel--copy">'
            f"<h4>{title}</h4>"
            f"<p>{body}</p>"
            "</div>"
            "</div>"
            "</div>"
        )
    if flavor == "minimal":
        return (
            '<div class="preview-glass preview-glass--minimal">'
            '<div class="preview-glass-topline"><span></span><span></span><span></span></div>'
            '<div class="preview-glass-panel preview-glass-panel--hero">'
            f'<p class="preview-product-kicker">{badge}</p>'
            f"<h4>{title}</h4>"
            f"<p>{body}</p>"
            '<div class="preview-glass-actions"><span class="mock-button">Открыть</span><span class="preview-product-ghost">Демо</span></div>'
            "</div>"
            '<div class="preview-glass-orb"></div>'
            "</div>"
        )
    return (
        '<div class="preview-glass preview-glass--balanced">'
        '<div class="preview-glass-topline"><span></span><span></span><span></span></div>'
        '<div class="preview-glass-shell">'
        '<div class="preview-glass-panel preview-glass-panel--hero">'
        f'<p class="preview-product-kicker">{badge}</p>'
        f"<h4>{title}</h4>"
        f"<p>{body}</p>"
        "</div>"
        '<div class="preview-glass-panel preview-glass-panel--side">'
        '<div class="preview-glass-orb preview-glass-orb--small"></div>'
        '<div class="preview-glass-line"></div>'
        "</div>"
        "</div>"
        "</div>"
    )


def _preview_hyperminimal_family(proposal: Dict[str, Any], flavor: str) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, "Воздух, точность и чистая технология"))
    badge = _escape(_variant_badge_text(proposal, "Lucid"))
    if flavor == "editorial":
        return (
            '<div class="preview-lucid preview-lucid--editorial">'
            f'<p class="preview-lucid-eyebrow">{badge}</p>'
            f"<h4>{title}</h4>"
            f"<p>{body}</p>"
            '<div class="preview-lucid-bar"></div><div class="preview-lucid-bar preview-lucid-bar--short"></div>'
            "</div>"
        )
    if flavor == "balanced":
        return (
            '<div class="preview-lucid preview-lucid--balanced">'
            '<div class="preview-lucid-shell">'
            '<div class="preview-lucid-card"></div>'
            '<div class="preview-lucid-copy">'
            f'<p class="preview-lucid-eyebrow">{badge}</p>'
            f"<h4>{title}</h4>"
            f"<p>{body}</p>"
            "</div>"
            "</div>"
            '<div class="preview-lucid-bar"></div>'
            "</div>"
        )
    return (
        '<div class="preview-lucid preview-lucid--minimal">'
        f'<p class="preview-lucid-eyebrow">{badge}</p>'
        '<div class="preview-lucid-card preview-lucid-card--large"></div>'
        f"<h4>{title}</h4>"
        '<div class="preview-lucid-bar"></div><div class="preview-lucid-bar preview-lucid-bar--short"></div>'
        "</div>"
    )


def _preview_depth_family(proposal: Dict[str, Any], flavor: str) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, "Объект, сцена и вспомогательная панель"))
    badge = _escape(_variant_badge_text(proposal, "WebGL"))
    if flavor == "technical":
        return (
            '<div class="preview-depth preview-depth--technical">'
            '<div class="preview-depth-stage">'
            '<div class="preview-depth-object preview-depth-object--wire"></div>'
            "</div>"
            '<div class="preview-depth-grid">'
            '<div class="preview-depth-panel preview-depth-panel--copy">'
            f"<h4>{title}</h4><p>{body}</p>"
            "</div>"
            '<div class="preview-depth-panel"></div>'
            "</div>"
            "</div>"
        )
    if flavor == "balanced":
        return (
            '<div class="preview-depth preview-depth--balanced">'
            f'<p class="preview-kicker">{badge}</p>'
            '<div class="preview-depth-shell">'
            '<div class="preview-depth-stage"><div class="preview-depth-object"></div></div>'
            '<div class="preview-depth-panel preview-depth-panel--copy">'
            f"<h4>{title}</h4><p>{body}</p>"
            '<span class="mock-button">Исследовать</span>'
            "</div>"
            "</div>"
            "</div>"
        )
    return (
        '<div class="preview-depth preview-depth--expressive">'
        f'<p class="preview-kicker">{badge}</p>'
        '<div class="preview-depth-stage preview-depth-stage--hero">'
        '<div class="preview-depth-object preview-depth-object--hero"></div>'
        "</div>"
        '<div class="preview-depth-grid"><div class="preview-depth-panel"></div><div class="preview-depth-panel"></div></div>'
        "</div>"
    )


def _preview_kinetic_family(proposal: Dict[str, Any], flavor: str) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, "Заголовок как система"))
    badge = _escape(_variant_badge_text(proposal, "Kinetic"))
    if flavor == "minimal":
        return (
            '<div class="preview-kinetic preview-kinetic--minimal">'
            f'<p class="preview-kicker">{badge}</p>'
            f'<div class="preview-kinetic-word preview-kinetic-word--compact">{title}</div>'
            '<div class="preview-kinetic-band preview-kinetic-band--soft"></div>'
            '<div class="preview-kinetic-rails"><span></span><span></span></div>'
            "</div>"
        )
    if flavor == "expressive":
        return (
            '<div class="preview-kinetic preview-kinetic--expressive">'
            f'<p class="preview-kicker">{badge}</p>'
            '<div class="preview-kinetic-stack">'
            f'<div class="preview-kinetic-word">{title}</div>'
            f'<div class="preview-kinetic-word preview-kinetic-word--echo">{title}</div>'
            "</div>"
            f"<p>{body}</p>"
            '<div class="preview-kinetic-band"></div>'
            '<span class="mock-button">Действовать</span>'
            "</div>"
        )
    return (
        '<div class="preview-kinetic preview-kinetic--editorial">'
        f'<p class="preview-kicker">{badge}</p>'
        f'<div class="preview-kinetic-word preview-kinetic-word--editorial">{title}</div>'
        f"<p>{body}</p>"
        '<div class="preview-kinetic-band preview-kinetic-band--thin"></div>'
        '<div class="preview-kinetic-rails"><span></span><span></span><span></span></div>'
        "</div>"
    )


def _preview_journey_family(proposal: Dict[str, Any], flavor: str) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, "История, ведомая по шагам"))
    badge = _escape(_variant_badge_text(proposal, "Journey"))
    if flavor == "expressive":
        return (
            '<div class="preview-journey preview-journey--expressive">'
            '<div class="preview-journey-rail"><span></span><span></span><span></span></div>'
            '<div class="preview-journey-card">'
            '<div class="preview-journey-topline"><strong>Фаза 02</strong><span>Прогресс +18%</span></div>'
            f'<p class="preview-kicker">{badge}</p><h4>{title}</h4><p>{body}</p>'
            "</div>"
            '<div class="preview-journey-steps"><span></span><span></span><span></span></div>'
            "</div>"
        )
    if flavor == "balanced":
        return (
            '<div class="preview-journey preview-journey--balanced">'
            '<div class="preview-journey-rail preview-journey-rail--soft"><span></span><span></span><span></span></div>'
            '<div class="preview-journey-shell">'
            '<div class="preview-journey-step"><strong>2/4</strong><span>checkpoint</span></div>'
            '<div class="preview-journey-card"><div class="preview-journey-topline"><strong>Базовый маршрут</strong><span>Checkpoint</span></div><h4>' + title + '</h4><p>' + body + '</p></div>'
            "</div></div>"
        )
    return (
        '<div class="preview-journey preview-journey--editorial">'
        f'<p class="preview-kicker">{badge}</p>'
        '<div class="preview-journey-card"><div class="preview-journey-topline"><strong>Intro</strong><span>Гл. 1</span></div><h4>' + title + '</h4><p>' + body + '</p></div>'
        '<div class="preview-journey-steps"><span></span><span></span><span></span></div>'
        "</div>"
    )


def _preview_retro_family(proposal: Dict[str, Any], flavor: str) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, "Слои, энергия и заметный цвет"))
    badge = _escape(_variant_badge_text(proposal, "Retro"))
    if flavor == "balanced":
        return (
            '<div class="preview-retro preview-retro--balanced">'
            '<div class="preview-retro-stickers"><span>' + badge + '</span><span>Журнал</span></div>'
            '<div class="preview-retro-collage"><div class="preview-retro-poster"></div><div class="preview-retro-ticket"></div></div>'
            '<div class="preview-retro-copy"><h4>' + title + '</h4><p>' + body + '</p></div>'
            '<div class="preview-retro-bar"></div>'
            "</div>"
        )
    if flavor == "minimal":
        return (
            '<div class="preview-retro preview-retro--editorial">'
            '<div class="preview-retro-stickers"><span>' + badge + '</span><span>Продуманно</span></div>'
            '<div class="preview-retro-collage"><div class="preview-retro-poster preview-retro-poster--wide"></div><div class="preview-retro-ticket preview-retro-ticket--tilt"></div></div>'
            '<div class="preview-retro-copy"><h4>' + title + '</h4><p>' + body + '</p></div>'
            "</div>"
        )
    return (
        '<div class="preview-retro preview-retro--expressive">'
        '<div class="preview-retro-stickers"><span>' + badge + '</span><span>Эффект</span></div>'
        '<div class="preview-retro-collage"><div class="preview-retro-poster preview-retro-poster--wide"></div><div class="preview-retro-ticket preview-retro-ticket--tilt"></div></div>'
        '<div class="preview-retro-bar preview-retro-bar--thick"></div>'
        '<span class="mock-button">Войти</span>'
        "</div>"
    )


def _preview_dopamine_family(proposal: Dict[str, Any], flavor: str) -> str:
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, "Быстрый цвет, энергия и мгновенный отклик"))
    badge = _escape(_variant_badge_text(proposal, "Dopa"))
    if flavor == "balanced":
        return (
            '<div class="preview-dopamine preview-dopamine--balanced">'
            '<div class="preview-dopamine-badges"><span>' + badge + '</span><span>Цвет</span></div>'
            '<div class="preview-dopamine-shell"><div class="preview-dopamine-bubble"></div><div class="preview-dopamine-bubble preview-dopamine-bubble--small"></div></div>'
            '<div class="preview-dopamine-copy"><h4>' + title + '</h4><p>' + body + '</p></div>'
            '<div class="preview-dopamine-dots"><span></span><span></span><span></span></div>'
            "</div>"
        )
    if flavor == "minimal":
        return (
            '<div class="preview-dopamine preview-dopamine--minimal">'
            '<div class="preview-dopamine-badges"><span>' + badge + '</span></div>'
            '<div class="preview-dopamine-copy"><h4>' + title + '</h4><p>' + body + '</p></div>'
            '<div class="preview-dopamine-strip"></div>'
            '<div class="preview-dopamine-dots"><span></span><span></span><span></span></div>'
            "</div>"
        )
    return (
        '<div class="preview-dopamine preview-dopamine--expressive">'
        '<div class="preview-dopamine-badges"><span>' + badge + '</span><span>Эффект</span></div>'
        '<div class="preview-dopamine-shell"><div class="preview-dopamine-bubble preview-dopamine-bubble--large"></div><div class="preview-dopamine-pill"></div></div>'
        '<span class="mock-button">Войти</span>'
        "</div>"
    )


def _preview_markup(proposal: Dict[str, Any], flavor: str) -> str:
    note = _escape(_preview_note_text(proposal))
    family_token = _style_family_id(proposal)
    family_renderers = {
        "neo-brutalism": _preview_brutal_family,
        "nature-distilled": _preview_organic_family,
        "glassmorphism-2": _preview_glass_family,
        "ai-hyperminimalism": _preview_hyperminimal_family,
        "interactive-3d-webgl": _preview_depth_family,
        "kinetic-typography": _preview_kinetic_family,
        "narrative-scroll-gamification": _preview_journey_family,
        "maximalism-neo-retro": _preview_retro_family,
        "dopamine-colors": _preview_dopamine_family,
    }
    if family_token in family_renderers:
        preview_layout = family_renderers[family_token](proposal, flavor)
    else:
        preview_layout = {
            "editorial": _preview_editorial,
            "technical": _preview_technical,
            "operational": _preview_operational,
            "minimal": _preview_minimal,
            "expressive": _preview_expressive,
            "balanced": _preview_balanced,
        }[flavor](proposal)
    note_markup = f'<div class="preview-tone-note">{note}</div>' if note else ""
    return (
        f'<div class="style-preview style-preview--{flavor} style-preview--family-{family_token}" '
        f'data-style-family="{_escape(family_token)}" '
        f'style="background:{_escape(_preview_background(proposal))};">'
        f"{note_markup}"
        f"{preview_layout}"
        "</div>"
    )


def _option_shell_open_tag(
    proposal: Dict[str, Any],
    flavor: str,
    theme: Dict[str, str],
    family_token: str,
    choice: str,
    name: str,
    extra_classes: str = "",
) -> str:
    classes = f"style-option style-option--{flavor} style-family--{family_token}"
    if extra_classes:
        classes = f"{classes} {extra_classes}".strip()
    return (
        f'<div class="{classes}" '
        f'data-choice="{choice}" data-label="{name}" data-style-family="{_escape(family_token)}" '
        f'style="{_option_style_attr(theme)}; {_option_typography_attr(proposal)}">'
    )


def _render_generic_option_card(
    proposal: Dict[str, Any],
    flavor: str,
    theme: Dict[str, str],
    family_token: str,
    choice: str,
    name: str,
) -> str:
    choice = _escape(proposal.get("choice", ""))
    name = _escape(proposal.get("name", choice))
    concept = _escape(_sentence(proposal.get("concept") or ""))
    typography = _escape(_typography_summary(proposal))
    tone = _escape(_sentence(proposal.get("tone") or ""))
    density = _escape(_sentence(proposal.get("spacing_density") or ""))
    sample_component = _escape(_sentence(proposal.get("sample_component") or ""))
    style_family = _escape(proposal.get("style_family_label") or proposal.get("style_family") or "")
    palette_mode = _escape(proposal.get("palette_mode_label") or proposal.get("palette_mode") or "")
    variant_label = _escape(proposal.get("variant_label") or "")
    typography_data = proposal.get("typography") or {}

    meta_lines = []
    if style_family or palette_mode:
        badges = []
        if style_family:
            badges.append(f'<span class="style-badge">{style_family}</span>')
        if palette_mode:
            badges.append(f'<span class="style-badge style-badge--soft">{palette_mode}</span>')
        meta_lines.append('<div class="style-badges">' + "".join(badges) + "</div>")
    if variant_label:
        meta_lines.append(f'<p class="style-description"><strong>Вариант:</strong> {variant_label}</p>')
    if concept:
        meta_lines.append(f'<p class="style-description">{concept}</p>')
    palette_markup = _palette_markup(proposal.get("palette") or [])
    if palette_markup:
        meta_lines.append(palette_markup)
    if typography:
        meta_lines.append(f'<p class="style-typo"><strong>Типографика:</strong> {typography}</p>')
    if tone:
        meta_lines.append(f'<p class="style-tone"><strong>Тон:</strong> {tone}</p>')
    if density:
        meta_lines.append(f'<p class="style-tone"><strong>Плотность:</strong> {density}</p>')
    if sample_component:
        meta_lines.append(f'<p class="style-sample"><strong>Компонент:</strong> {sample_component}</p>')
    reference_links = _reference_links_markup(proposal.get("reference_urls") or [])
    if reference_links:
        meta_lines.append(reference_links)
    typography_links = _typography_links_markup(typography_data)
    if typography_links:
        meta_lines.append(typography_links)

    return (
        _option_shell_open_tag(proposal, flavor, theme, family_token, choice, name)
        + f'<span class="style-letter">{choice}</span>'
        + f"{_preview_markup(proposal, flavor)}"
        + '<div class="style-meta">'
        + f'<h2 class="style-name">{name}</h2>'
        + "".join(meta_lines)
        + "</div></div>"
    )


def _render_kinetic_option_card(
    proposal: Dict[str, Any],
    flavor: str,
    theme: Dict[str, str],
    family_token: str,
) -> str:
    choice = _escape(proposal.get("choice", ""))
    name = _escape(proposal.get("name", choice))
    style_family = _escape(proposal.get("style_family_label") or proposal.get("style_family") or "")
    palette_mode = _escape(proposal.get("palette_mode_label") or proposal.get("palette_mode") or "")
    variant_label = _escape(proposal.get("variant_label") or _preview_title_text(proposal))
    title = _escape(_preview_title_text(proposal))
    body = _escape(_preview_body_text(proposal, _context_summary(proposal)))
    concept = _escape(_sentence(proposal.get("concept") or ""))
    typography = _escape(_typography_summary(proposal))
    tone = _escape(_sentence(proposal.get("tone") or ""))
    density = _escape(_sentence(proposal.get("spacing_density") or ""))
    sample_component = _escape(_sentence(proposal.get("sample_component") or ""))
    palette_markup = _palette_markup(proposal.get("palette") or [])
    family_badge = _escape(style_family or "Кинетическая типографика")
    mode_badge = _escape(palette_mode or "Базовая")
    kinetic_copy = concept or body
    kinetic_specs = []
    if typography:
        kinetic_specs.append(
            '<div class="style-kinetic-spec"><span class="style-kinetic-spec-label">Типографика</span>'
            f"<p>{typography}</p></div>"
        )
    if tone:
        kinetic_specs.append(
            '<div class="style-kinetic-spec"><span class="style-kinetic-spec-label">Тон</span>'
            f"<p>{tone}</p></div>"
        )
    if density:
        kinetic_specs.append(
            '<div class="style-kinetic-spec"><span class="style-kinetic-spec-label">Плотность</span>'
            f"<p>{density}</p></div>"
        )
    if sample_component:
        kinetic_specs.append(
            '<div class="style-kinetic-spec style-kinetic-spec--wide"><span class="style-kinetic-spec-label">Компонент</span>'
            f"<p>{sample_component}</p></div>"
        )
    if not kinetic_specs:
        kinetic_specs.append(
            '<div class="style-kinetic-spec style-kinetic-spec--wide"><span class="style-kinetic-spec-label">Направление</span>'
            f"<p>{body}</p></div>"
        )

    hero_markup = {
        "expressive": (
            '<div class="style-kinetic-hero style-kinetic-hero--expressive">'
            f'<p class="style-kinetic-kicker">{family_badge}</p>'
            f'<h2 class="style-kinetic-headline">{title}</h2>'
            f'<div class="style-kinetic-echo">{title}</div>'
            f'<p class="style-kinetic-copy">{kinetic_copy}</p>'
            '<div class="style-kinetic-band"></div>'
            '<span class="style-kinetic-cta">Действовать</span>'
            "</div>"
        ),
        "minimal": (
            '<div class="style-kinetic-hero style-kinetic-hero--minimal">'
            f'<p class="style-kinetic-kicker">{family_badge}</p>'
            f'<h2 class="style-kinetic-headline">{title}</h2>'
            '<div class="style-kinetic-band style-kinetic-band--thin"></div>'
            f'<p class="style-kinetic-copy">{kinetic_copy}</p>'
            '<div class="style-kinetic-rails"><span></span><span></span></div>'
            "</div>"
        ),
        "editorial": (
            '<div class="style-kinetic-hero style-kinetic-hero--editorial">'
            f'<p class="style-kinetic-kicker">{family_badge}</p>'
            f'<h2 class="style-kinetic-headline">{title}</h2>'
            f'<p class="style-kinetic-copy">{kinetic_copy}</p>'
            '<div class="style-kinetic-band style-kinetic-band--thin"></div>'
            '<div class="style-kinetic-rails"><span></span><span></span><span></span></div>'
            "</div>"
        ),
    }[flavor]

    return (
        _option_shell_open_tag(
            proposal,
            flavor,
            theme,
            family_token,
            choice,
            name,
            extra_classes="style-option--family-card style-option--kinetic-card",
        )
        + f'<span class="style-letter">{choice}</span>'
        + f'<div class="style-kinetic-card style-kinetic-card--{flavor}">'
        + '<div class="style-kinetic-topline">'
        + f"<span>{family_badge}</span><span>{mode_badge}</span><span>{variant_label}</span>"
        + "</div>"
        + f"{hero_markup}"
        + '<div class="style-kinetic-meta">'
        + f'<h3 class="style-kinetic-name">{name}</h3>'
        + (f'<div class="style-kinetic-palette">{palette_markup}</div>' if palette_markup else "")
        + '<div class="style-kinetic-specs">'
        + "".join(kinetic_specs)
        + "</div></div></div></div>"
    )


def _render_hyperminimal_option_card(
    proposal: Dict[str, Any],
    flavor: str,
    theme: Dict[str, str],
    family_token: str,
) -> str:
    choice = _escape(proposal.get("choice", ""))
    name = _escape(proposal.get("name", choice))
    title = _escape(_preview_title_text(proposal))
    concept = _escape(_sentence(proposal.get("concept") or ""))
    tone = _escape(_sentence(proposal.get("tone") or ""))
    density = _escape(_sentence(proposal.get("spacing_density") or ""))
    typography = _escape(_typography_summary(proposal))
    badge = _escape(proposal.get("variant_label") or "Чистый продукт")
    palette_mode = _escape(proposal.get("palette_mode_label") or proposal.get("palette_mode") or "Базовая")
    palette_markup = _palette_markup(proposal.get("palette") or [])

    spec_lines = []
    if typography:
        spec_lines.append(
            '<div class="style-lucid-spec"><span>Типографика</span>'
            f"<p>{typography}</p></div>"
        )
    if tone:
        spec_lines.append(
            '<div class="style-lucid-spec"><span>Тон</span>'
            f"<p>{tone}</p></div>"
        )
    if density:
        spec_lines.append(
            '<div class="style-lucid-spec"><span>Плотность</span>'
            f"<p>{density}</p></div>"
        )
    if not spec_lines and concept:
        spec_lines.append(
            '<div class="style-lucid-spec style-lucid-spec--wide"><span>Направление</span>'
            f"<p>{concept}</p></div>"
        )

    hero_variant = {
        "editorial": "style-lucid-hero--editorial",
        "balanced": "style-lucid-hero--balanced",
        "minimal": "style-lucid-hero--minimal",
    }[flavor]
    metric_markup = {
        "editorial": '<div class="style-lucid-caption">Ведомое чтение</div>',
        "balanced": '<div class="style-lucid-caption">Устойчивая точность</div>',
        "minimal": '<div class="style-lucid-caption">Меньше шума, больше фокуса</div>',
    }[flavor]

    return (
        _option_shell_open_tag(
            proposal,
            flavor,
            theme,
            family_token,
            choice,
            name,
            extra_classes="style-option--family-card style-option--lucid-card",
        )
        + f'<span class="style-letter">{choice}</span>'
        + f'<div class="style-lucid-card style-lucid-card--{flavor}">'
        + '<div class="style-lucid-topline">'
        + f"<span>{_escape(proposal.get('style_family_label') or 'AI-гиперминимализм')}</span>"
        + f"<span>{palette_mode}</span><span>{badge}</span>"
        + "</div>"
        + f'<div class="style-lucid-hero {hero_variant}">'
        + '<div class="style-lucid-frame"></div>'
        + f'<h2 class="style-lucid-headline">{title}</h2>'
        + (f'<p class="style-lucid-copy">{concept}</p>' if concept else "")
        + metric_markup
        + '<div class="style-lucid-bars"><span></span><span></span></div>'
        + "</div>"
        + '<div class="style-lucid-meta">'
        + f'<h3 class="style-lucid-name">{name}</h3>'
        + (f'<div class="style-lucid-palette">{palette_markup}</div>' if palette_markup else "")
        + '<div class="style-lucid-specs">'
        + "".join(spec_lines)
        + "</div></div></div></div>"
    )


def _render_glass_option_card(
    proposal: Dict[str, Any],
    flavor: str,
    theme: Dict[str, str],
    family_token: str,
) -> str:
    choice = _escape(proposal.get("choice", ""))
    name = _escape(proposal.get("name", choice))
    title = _escape(_preview_title_text(proposal))
    concept = _escape(_sentence(proposal.get("concept") or ""))
    typography = _escape(_typography_summary(proposal))
    tone = _escape(_sentence(proposal.get("tone") or ""))
    density = _escape(_sentence(proposal.get("spacing_density") or ""))
    badge = _escape(proposal.get("variant_label") or "Базовый баланс")
    palette_mode = _escape(proposal.get("palette_mode_label") or proposal.get("palette_mode") or "Базовая")
    palette_markup = _palette_markup(proposal.get("palette") or [])

    specs = []
    if typography:
        specs.append(f'<p><strong>Типографика:</strong> {typography}</p>')
    if tone:
        specs.append(f'<p><strong>Тон:</strong> {tone}</p>')
    if density:
        specs.append(f'<p><strong>Плотность:</strong> {density}</p>')

    hero_copy = {
        "technical": '<div class="style-glass-chiprow"><span>OK</span><span>Задержка</span></div>',
        "minimal": '<div class="style-glass-actions"><span class="style-glass-pill style-glass-pill--accent">Открыть</span><span class="style-glass-pill">Демо</span></div>',
        "balanced": '<div class="style-glass-actions"><span class="style-glass-pill style-glass-pill--accent">Открыть</span><span class="style-glass-pill">Исследовать</span></div>',
    }[flavor]

    return (
        _option_shell_open_tag(
            proposal,
            flavor,
            theme,
            family_token,
            choice,
            name,
            extra_classes="style-option--family-card style-option--glass-card",
        )
        + f'<span class="style-letter">{choice}</span>'
        + f'<div class="style-glass-card style-glass-card--{flavor}">'
        + '<div class="style-glass-topline">'
        + f"<span>{_escape(proposal.get('style_family_label') or 'Glassmorphism 2.0')}</span>"
        + f"<span>{palette_mode}</span><span>{badge}</span>"
        + "</div>"
        + '<div class="style-glass-stage">'
        + '<div class="style-glass-panel style-glass-panel--hero">'
        + f'<p class="style-glass-kicker">{badge}</p>'
        + f'<h2 class="style-glass-headline">{title}</h2>'
        + (f'<p class="style-glass-copy">{concept}</p>' if concept else "")
        + hero_copy
        + "</div>"
        + '<div class="style-glass-panel style-glass-panel--orb"><div class="style-glass-orb-large"></div></div>'
        + "</div>"
        + '<div class="style-glass-meta">'
        + f'<h3 class="style-glass-name">{name}</h3>'
        + (f'<div class="style-glass-palette">{palette_markup}</div>' if palette_markup else "")
        + "".join(specs)
        + "</div></div></div>"
    )


def _render_depth_option_card(
    proposal: Dict[str, Any],
    flavor: str,
    theme: Dict[str, str],
    family_token: str,
) -> str:
    choice = _escape(proposal.get("choice", ""))
    name = _escape(proposal.get("name", choice))
    title = _escape(_preview_title_text(proposal))
    concept = _escape(_sentence(proposal.get("concept") or ""))
    typography = _escape(_typography_summary(proposal))
    tone = _escape(_sentence(proposal.get("tone") or ""))
    density = _escape(_sentence(proposal.get("spacing_density") or ""))
    badge = _escape(proposal.get("variant_label") or "Базовый баланс")
    palette_mode = _escape(proposal.get("palette_mode_label") or proposal.get("palette_mode") or "Базовая")
    palette_markup = _palette_markup(proposal.get("palette") or [])
    side_markup = {
        "expressive": '<span class="style-depth-cta">Исследовать</span>',
        "technical": '<div class="style-depth-stats"><span>Состояние</span><span>График</span></div>',
        "balanced": '<span class="style-depth-cta">Войти</span>',
    }[flavor]

    return (
        _option_shell_open_tag(
            proposal,
            flavor,
            theme,
            family_token,
            choice,
            name,
            extra_classes="style-option--family-card style-option--depth-card",
        )
        + f'<span class="style-letter">{choice}</span>'
        + f'<div class="style-depth-card style-depth-card--{flavor}">'
        + '<div class="style-depth-topline">'
        + f"<span>{_escape(proposal.get('style_family_label') or 'Интерактивное 3D и WebGL')}</span>"
        + f"<span>{palette_mode}</span><span>{badge}</span>"
        + "</div>"
        + '<div class="style-depth-stage">'
        + '<div class="style-depth-object-shell"><div class="style-depth-object-large"></div></div>'
        + '<div class="style-depth-side-panel">'
        + f'<p class="style-depth-kicker">{badge}</p>'
        + f'<h2 class="style-depth-headline">{title}</h2>'
        + (f'<p class="style-depth-copy">{concept}</p>' if concept else "")
        + side_markup
        + "</div></div>"
        + '<div class="style-depth-meta">'
        + f'<h3 class="style-depth-name">{name}</h3>'
        + (f'<div class="style-depth-palette">{palette_markup}</div>' if palette_markup else "")
        + (f'<p><strong>Типографика:</strong> {typography}</p>' if typography else "")
        + (f'<p><strong>Тон:</strong> {tone}</p>' if tone else "")
        + (f'<p><strong>Плотность:</strong> {density}</p>' if density else "")
        + "</div></div></div>"
    )


def _render_option_card(proposal: Dict[str, Any], flavor: Optional[str] = None) -> str:
    flavor = flavor or _candidate_option_flavors(proposal)[0]
    theme = _option_theme(proposal, flavor)
    family_token = _class_token(proposal.get("style_family") or proposal.get("style_family_label") or "")
    if family_token == "kinetic-typography":
        return _render_kinetic_option_card(proposal, flavor, theme, family_token)
    if family_token == "ai-hyperminimalism":
        return _render_hyperminimal_option_card(proposal, flavor, theme, family_token)
    if family_token == "glassmorphism-2":
        return _render_glass_option_card(proposal, flavor, theme, family_token)
    if family_token == "interactive-3d-webgl":
        return _render_depth_option_card(proposal, flavor, theme, family_token)
    return _render_generic_option_card(
        proposal,
        flavor,
        theme,
        family_token,
        _escape(proposal.get("choice", "")),
        _escape(proposal.get("name", proposal.get("choice", ""))),
    )


def render_style_options_html(
    proposals: List[Dict[str, Any]],
    *,
    title: str = "Выбери визуальное направление",
    subtitle: str = "Выбери предложение, которое лучше подходит продукту. Твой клик записывается автоматически.",
) -> str:
    """Render the canonical HTML fragment of the Designer options."""
    assigned_flavors = _assign_option_flavors(proposals)
    cards = [
        _render_option_card(proposal, assigned_flavors.get(str(proposal.get("choice", "")).strip()))
        for proposal in proposals
    ]
    return (
        _font_imports_markup(proposals)
        + '<section class="style-screen">'
        '<div class="style-screen-header">'
        f"<p class=\"style-screen-kicker\">Designer предлагает</p>"
        f"<h1>{_escape(title)}</h1>"
        f"<p class=\"style-screen-subtitle\">{_escape(subtitle)}</p>"
        "</div>"
        '<div class="style-grid">'
        + "".join(cards)
        + "</div></section>"
    )


def build_style_options_payload(
    visual_path: str,
    *,
    proposals_file: Optional[str] = None,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
) -> Dict[str, Any]:
    """Load normalized proposals and build the HTML ready to write."""
    proposals_path = proposals_file or discover_proposals_file(visual_path)
    if not proposals_path:
        raise ValueError("Файл с предложениями Designer не найден.")

    proposals = list(load_style_proposals(proposals_path).values())
    if not proposals:
        raise ValueError("Sidecar с предложениями существует, но в нём нет корректных вариантов.")

    html_fragment = render_style_options_html(
        proposals,
        title=title or "Выбери визуальное направление",
        subtitle=subtitle
        or "Выбери предложение, которое лучше подходит продукту. Твой клик записывается автоматически.",
    )

    return {
        "visual_session_dir": resolve_visual_session_dir(visual_path),
        "proposals_file": proposals_path,
        "choices": [proposal["choice"] for proposal in proposals],
        "html": html_fragment,
    }


def write_style_options_html(
    visual_path: str,
    *,
    proposals_file: Optional[str] = None,
    title: Optional[str] = None,
    subtitle: Optional[str] = None,
) -> Dict[str, Any]:
    """Write style-options.html into the Designer visual session."""
    payload = build_style_options_payload(
        visual_path,
        proposals_file=proposals_file,
        title=title,
        subtitle=subtitle,
    )
    content_dir = os.path.join(payload["visual_session_dir"], "content")
    os.makedirs(content_dir, exist_ok=True)
    html_path = os.path.join(content_dir, STYLE_OPTIONS_HTML_FILENAME)
    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(payload["html"])

    return {
        "status": "ok",
        "html_path": html_path,
        "proposals_file": payload["proposals_file"],
        "choices": payload["choices"],
    }
