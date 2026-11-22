#!/usr/bin/env python3
"""Guided generation of three final variants for Designer."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from core.designer_style_catalog import (
    build_style_catalog_proposal,
    get_style_trend,
    resolve_font_pairing,
    resolve_palette_mode_meta,
)
from core.designer_style_direction import resolve_visual_session_dir
from core.designer_style_options import write_style_options_html
from core.designer_style_selector import parse_guided_choice
from core.designer_visual import read_latest_style_choice


STYLE_VARIANTS_JSON_FILENAME = "style-options.json"


STYLE_VARIANT_FLAVORS: Dict[str, Tuple[str, str, str]] = {
    "free-default": ("balanced", "minimal", "editorial"),
    "maximalism-neo-retro": ("expressive", "editorial", "balanced"),
    "kinetic-typography": ("editorial", "expressive", "minimal"),
    "interactive-3d-webgl": ("expressive", "technical", "balanced"),
    "glassmorphism-2": ("balanced", "minimal", "technical"),
    "dopamine-colors": ("expressive", "balanced", "minimal"),
    "nature-distilled": ("editorial", "balanced", "minimal"),
    "neo-brutalism": ("expressive", "operational", "minimal"),
    "ai-hyperminimalism": ("minimal", "balanced", "editorial"),
    "narrative-scroll-gamification": ("editorial", "expressive", "balanced"),
}


VARIANT_PROFILES: Dict[str, Dict[str, str]] = {
    "expressive": {
        "label": "Выразительный почерк",
        "concept_suffix": "Этот вариант подаёт систему как заметный почерк, с большим напряжением и мгновенным присутствием",
        "preview_copy": "Самая брендовая версия: более фронтальная и с более сильным визуальным жестом.",
        "preview_note": "Выразительный почерк",
        "density": "Средняя, с главными блоками, выраженным контрастом и чуть более театральным ритмом.",
        "tone_suffix": "Ощущается более фронтальной: акценты запоминаются, композиция менее нейтральна.",
        "component": "Главный hero с сильным жестом, акцентами бренда и очень заметным CTA.",
        "rationale_suffix": "Лучше всех защищает айдентику и запоминаемость, не покидая выбранную систему.",
        "not_this": "Не пытается смягчить характер или выглядеть плоским корпоративным интерфейсом.",
    },
    "editorial": {
        "label": "Редакционный нарратив",
        "concept_suffix": "Этот вариант добавляет нарративную иерархию, ведомое чтение и ощущение продуманности",
        "preview_copy": "Версия, которая лучше объясняет и сильнее передаёт визуальный вкус.",
        "preview_note": "Редакционный нарратив",
        "density": "Воздушная, с ясной последовательностью, более заметными заголовками и намеренными паузами.",
        "tone_suffix": "Воспринимается более продуманной, неспешной и нацеленной объяснять, а не подталкивать.",
        "component": "Последовательность hero + редакционный блок + сдержанный CTA с большим пространством для чтения.",
        "rationale_suffix": "Работает, когда продукту нужно хорошо объяснить свою ценность, не теряя характера.",
        "not_this": "Не самый агрессивный вариант и не самый подходящий для постоянного операционного просмотра.",
    },
    "technical": {
        "label": "Технический сигнал",
        "concept_suffix": "Этот вариант усиливает семантику состояний, контраст и чтение в духе мониторинга",
        "preview_copy": "Самая точная версия, нацеленная на техническое чтение продукта.",
        "preview_note": "Технический сигнал",
        "density": "Выше средней, с компактными блоками, акцентом на состояниях и иерархией для быстрого чтения.",
        "tone_suffix": "Выглядит более точной, инструментальной и нацеленной на ясность системы.",
        "component": "Главная панель с состояниями, короткими графиками и ясной иерархией сигналов.",
        "rationale_suffix": "Подходит, когда продукту нужно усилить контроль, видимость состояния и однозначное чтение.",
        "not_this": "Не ищет редакционного тепла или визуальной тишины как первого слоя опыта.",
    },
    "operational": {
        "label": "Рабочий продукт",
        "concept_suffix": "Этот вариант делает систему удобнее для реального продукта, с фокусом на задаче и быстром чтении",
        "preview_copy": "Самая приземлённая версия для ежедневной работы и быстрого просмотра.",
        "preview_note": "Рабочий продукт",
        "density": "Средняя, с балансом ясности, решений и достаточной плотности для реальной работы.",
        "tone_suffix": "Ощущается скорее живым продуктом, чем визуальным манифестом, и сохраняет выбранное семейство.",
        "component": "Рабочая сводка с ключевыми метриками, контекстным CTA и очень ясной иерархией просмотра.",
        "rationale_suffix": "Обычно это самый приземлённый вариант для постоянно развивающегося продукта и широкой аудитории.",
        "not_this": "Не превращает направление в чисто брендовую вещь или storytelling.",
    },
    "minimal": {
        "label": "Чистый продукт",
        "concept_suffix": "Этот вариант чище, сфокусированнее и тише, с меньшим шумом вокруг базовой системы",
        "preview_copy": "Самая чистая, лёгкая и простая в реализации версия.",
        "preview_note": "Чистый продукт",
        "density": "Воздушная, с большим негативным пространством, меньшим числом одновременных слоёв и фокусом на главном.",
        "tone_suffix": "Даёт ощущение лёгкости, изысканности и простоты в ежедневной реализации.",
        "component": "Чистый продуктовый hero с доминирующим CTA, социальным доказательством и минимумом поддержки.",
        "rationale_suffix": "Помогает сохранить выбранное семейство, не перегружая итоговый опыт.",
        "not_this": "Не самый выразительный вариант и не тот, что доводит визуальный жест до предела.",
    },
    "balanced": {
        "label": "Базовый баланс",
        "concept_suffix": "Этот вариант держит более сбалансированный тон, чтобы одновременно поддерживать бренд и продукт",
        "preview_copy": "Синтез визуального характера и удобства использования.",
        "preview_note": "Базовый баланс",
        "density": "Сбалансированная: достаточно воздуха, чтобы дышать, и достаточно структуры, чтобы вести.",
        "tone_suffix": "Воспринимается более стабильной, универсальной и простой для расширения на всю систему.",
        "component": "Секция ценности с supporting copy, социальным доказательством и главным CTA с ясной иерархией.",
        "rationale_suffix": "Хороший синтез характера и простоты реализации.",
        "not_this": "Не ищет визуальных крайностей и не драматизирует каждый блок продукта.",
    },
}


def _build_variant_name(style_name: str, profile: Dict[str, str]) -> str:
    return f"{style_name} — {profile['label']}"


def _build_variant_concept(style_description: str, profile: Dict[str, str]) -> str:
    return f"{style_description} {profile['concept_suffix']}."


def _build_variant_tone(base_tone: str, profile: Dict[str, str]) -> str:
    return f"{base_tone} {profile['tone_suffix']}"


def _build_variant_rationale(base_when_to_use: str, profile: Dict[str, str]) -> str:
    return f"{base_when_to_use} {profile['rationale_suffix']}"


def _resolve_guided_selection(
    visual_path: str,
    *,
    style_id: Optional[str] = None,
    font_pairing_id: Optional[str] = None,
    palette_mode: Optional[str] = None,
) -> Dict[str, str]:
    if style_id and font_pairing_id and palette_mode:
        return {
            "style_id": style_id,
            "font_pairing_id": font_pairing_id,
            "palette_mode": palette_mode,
        }

    latest_choice = read_latest_style_choice(visual_path)
    parsed = parse_guided_choice((latest_choice or {}).get("choice"))
    if not parsed or parsed.get("stage") != "style-brief":
        raise ValueError(
            "Пока нет корректного выбора в guided-режиме: система + типографика + палитра."
        )

    return {
        "style_id": parsed["style_id"],
        "font_pairing_id": parsed["font_pairing_id"],
        "palette_mode": parsed["palette_mode"],
    }


def build_guided_style_variants(
    *,
    style_id: str,
    font_pairing_id: str,
    palette_mode: str,
) -> List[Dict[str, Any]]:
    """Build three final proposals inside the same chosen family."""
    style = get_style_trend(style_id)
    font_pairing = resolve_font_pairing(style_id, pairing_id=font_pairing_id)
    palette_meta = resolve_palette_mode_meta(palette_mode)
    variant_flavors = STYLE_VARIANT_FLAVORS.get(style_id, ("balanced", "minimal", "editorial"))

    proposals: List[Dict[str, Any]] = []
    for choice, flavor in zip(("A", "B", "C"), variant_flavors):
        profile = VARIANT_PROFILES[flavor]
        proposal = build_style_catalog_proposal(
            style_id,
            choice=choice,
            palette_mode=palette_mode,
            font_pairing_id=font_pairing_id,
        )
        proposal["preview_flavor"] = flavor
        proposal["variant_id"] = flavor
        proposal["variant_label"] = profile["label"]
        proposal["preview_title"] = profile["label"]
        proposal["preview_copy"] = profile["preview_copy"]
        proposal["preview_note"] = profile["preview_note"]
        proposal["name"] = _build_variant_name(style["name"], profile)
        proposal["concept"] = _build_variant_concept(style["description"], profile)
        proposal["tone"] = _build_variant_tone(style["suggested_tone"], profile)
        proposal["spacing_density"] = profile["density"]
        proposal["sample_component"] = profile["component"]
        proposal["rationale"] = _build_variant_rationale(style["when_to_use"], profile)
        proposal["not_this_direction"] = [
            profile["not_this"],
            *list(style["anti_patterns"])[:1],
        ]
        proposal["context_signals"] = [
            f"Семейство, зафиксированное пользователем: {style['name']}.",
            f"Pairing, зафиксированный пользователем: {font_pairing['label']} ({font_pairing['headings']} / {font_pairing['body']}).",
            f"Цветовая гамма, зафиксированная пользователем: {palette_meta['label']}.",
            *list(style.get("visual_principles", []))[:2],
            f"Фирменные элементы системы: {', '.join(style.get('signature_elements', [])[:3])}.",
        ]
        proposal["prompt_seed"] = (
            f"{style.get('prompt_seed', '').strip()} "
            f"Сохраняй это визуальное семейство, даже когда смещаешь предложение к варианту «{profile['label']}»."
        ).strip()
        proposals.append(proposal)

    return proposals


def write_guided_style_options(
    visual_path: str,
    *,
    style_id: Optional[str] = None,
    font_pairing_id: Optional[str] = None,
    palette_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Write the sidecar and the final screen with three guided variants."""
    selection = _resolve_guided_selection(
        visual_path,
        style_id=style_id,
        font_pairing_id=font_pairing_id,
        palette_mode=palette_mode,
    )
    proposals = build_guided_style_variants(**selection)
    style = get_style_trend(selection["style_id"])
    font_pairing = resolve_font_pairing(selection["style_id"], pairing_id=selection["font_pairing_id"])
    palette_meta = resolve_palette_mode_meta(selection["palette_mode"])

    session_dir = resolve_visual_session_dir(visual_path)
    content_dir = os.path.join(session_dir, "content")
    os.makedirs(content_dir, exist_ok=True)
    proposals_path = os.path.join(content_dir, STYLE_VARIANTS_JSON_FILENAME)
    with open(proposals_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "guided_selection": selection,
                "proposals": proposals,
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )

    html_result = write_style_options_html(
        visual_path,
        proposals_file=proposals_path,
        title=f"Выбери финальную версию для {style['name']}",
        subtitle=(
            f"Основа зафиксирована: {font_pairing['label']} + {palette_meta['label']}. "
            "Теперь Designer показывает три сопоставимые финальные версии внутри этого же семейства."
        ),
    )

    return {
        "status": "ok",
        "style_id": selection["style_id"],
        "font_pairing_id": selection["font_pairing_id"],
        "palette_mode": selection["palette_mode"],
        "proposals_file": proposals_path,
        "html_path": html_result["html_path"],
        "choices": html_result["choices"],
    }
