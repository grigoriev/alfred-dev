#!/usr/bin/env python3
"""Render and write the docs/style-direction.md artifact."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.designer_visual import read_latest_style_choice, resolve_state_dir


STYLE_DIRECTION_DOC_RELATIVE_PATH = os.path.join("docs", "style-direction.md")


def resolve_visual_session_dir(path: str) -> str:
    """Accept session_dir or state_dir and return the real session_dir."""
    state_dir = resolve_state_dir(path)
    return os.path.dirname(state_dir)


def discover_proposals_file(visual_path: str) -> Optional[str]:
    """Find the proposals JSON sidecar in the canonical locations."""
    session_dir = resolve_visual_session_dir(visual_path)
    state_dir = resolve_state_dir(visual_path)
    candidates = [
        os.path.join(session_dir, "content", "style-options.json"),
        os.path.join(session_dir, "content", "proposals.json"),
        os.path.join(state_dir, "style-options.json"),
        os.path.join(state_dir, "proposals.json"),
    ]
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return None


def _coerce_string(value: Any) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split()).strip()


def _coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_coerce_string(item) for item in value if _coerce_string(item)]
    text = _coerce_string(value)
    return [text] if text else []


def _merge_unique_texts(*values: Any) -> List[str]:
    items: List[str] = []
    seen = set()
    for value in values:
        for item in _coerce_list(value):
            key = item.casefold()
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
    return items


def _normalize_palette(value: Any) -> List[Dict[str, str]]:
    if isinstance(value, dict):
        return [
            {"role": _coerce_string(role), "value": _coerce_string(color)}
            for role, color in value.items()
            if _coerce_string(role) and _coerce_string(color)
        ]
    if isinstance(value, list):
        items: List[Dict[str, str]] = []
        raw_colors: List[str] = []
        for entry in value:
            if isinstance(entry, dict):
                role = _coerce_string(entry.get("role") or entry.get("name"))
                color = _coerce_string(entry.get("value") or entry.get("color"))
                if role and color:
                    items.append({"role": role, "value": color})
                    continue
            color = _coerce_string(entry)
            if color:
                raw_colors.append(color)
        if items:
            return items
        if raw_colors:
            default_roles = [
                "surface",
                "surface_alt",
                "accent",
                "accent_alt",
                "ink",
                "muted",
            ]
            return [
                {
                    "role": default_roles[idx] if idx < len(default_roles) else f"color_{idx + 1}",
                    "value": color,
                }
                for idx, color in enumerate(raw_colors)
            ]
    return []


def _normalize_tokens(value: Any) -> List[Dict[str, str]]:
    if isinstance(value, dict):
        return [
            {"name": _coerce_string(name), "value": _coerce_string(token_value)}
            for name, token_value in value.items()
            if _coerce_string(name) and _coerce_string(token_value)
        ]
    if isinstance(value, list):
        items: List[Dict[str, str]] = []
        for entry in value:
            if isinstance(entry, dict):
                name = _coerce_string(entry.get("name"))
                token_value = _coerce_string(entry.get("value"))
                if name and token_value:
                    items.append({"name": name, "value": token_value})
        return items
    return []


def _normalize_typography(value: Any) -> Dict[str, str]:
    if isinstance(value, str):
        text = _coerce_string(value)
        if not text:
            return {}
        normalized: Dict[str, str] = {}
        families, separator, notes = text.partition("—")
        families = _coerce_string(families)
        notes = _coerce_string(notes if separator else "")
        parts = [part.strip() for part in families.split("/") if _coerce_string(part)]
        if parts:
            normalized["headings"] = parts[0]
        if len(parts) > 1:
            normalized["body"] = parts[1]
        if notes:
            normalized["notes"] = notes
        elif families:
            normalized["notes"] = families
        return normalized
    if not isinstance(value, dict):
        return {}
    normalized: Dict[str, str] = {}
    for key in (
        "pairing_id",
        "pairing_label",
        "headings",
        "body",
        "scale",
        "notes",
        "headings_url",
        "body_url",
        "css_url",
        "source",
        "custom_url",
    ):
        text = _coerce_string(value.get(key))
        if text:
            normalized[key] = text
    return normalized


def _normalize_reference_urls(value: Any) -> List[Dict[str, str]]:
    if not isinstance(value, list):
        return []

    items: List[Dict[str, str]] = []
    for entry in value:
        if isinstance(entry, dict):
            label = _coerce_string(entry.get("label") or entry.get("name") or entry.get("title"))
            url = _coerce_string(entry.get("url") or entry.get("href"))
            if label and url:
                items.append({"label": label, "url": url})
                continue

        if isinstance(entry, str):
            url = _coerce_string(entry)
            if url:
                items.append({"label": url, "url": url})
    return items


def _semantic_source_text(proposal: Dict[str, Any]) -> str:
    return " ".join(
        part
        for part in [
            proposal.get("name", ""),
            proposal.get("concept", ""),
            proposal.get("tone", ""),
            proposal.get("rationale", ""),
            " ".join(proposal.get("context_signals", [])),
            " ".join(proposal.get("visual_principles", [])),
            proposal.get("layout_grammar", ""),
            proposal.get("surface_treatment", ""),
            proposal.get("shape_language", ""),
            proposal.get("motion_language", ""),
            " ".join(proposal.get("signature_elements", [])),
            " ".join(proposal.get("implementation_guardrails", [])),
            proposal.get("prompt_seed", ""),
            " ".join(item.get("role", "") for item in proposal.get("palette", [])),
        ]
        if part
    ).lower()


def _matches_any(text: str, keywords: List[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _infer_direction_flavor(proposal: Dict[str, Any]) -> str:
    text = _semantic_source_text(proposal)
    if _matches_any(
        text,
        ["grafana", "datadog", "dark", "dark mode", "real-time", "24/7", "мониторинг", "темн", "тёмн", "реальном времени"],
    ):
        return "technical"
    if _matches_any(
        text,
        ["editorial", "premium", "luxury", "magazine", "serif", "warm", "редакцион", "журнал", "премиал", "роскош", "тёпл", "тепл"],
    ):
        return "editorial"
    if _matches_any(
        text,
        ["dashboard", "data", "analytics", "enterprise", "metric", "дашборд", "данн", "аналитик", "операцион", "метрик"],
    ):
        return "operational"
    if _matches_any(
        text,
        ["minimal", "clean", "negative space", "linear", "notion", "attio", "whitespace", "минимал", "чист", "воздушн", "сдержан", "негативн", "ясност"],
    ):
        return "minimal"
    if _matches_any(
        text,
        ["vibrant", "expressive", "energ", "bold", "experimental", "memorable", "impact", "ярк", "выразительн", "энерг", "смел", "эксперимент", "запомина"],
    ):
        return "expressive"
    return "balanced"


def _human_join(items: List[str]) -> str:
    clean = [item for item in (_coerce_string(item) for item in items) if item]
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} и {clean[1]}"
    return f"{', '.join(clean[:-1])} и {clean[-1]}"


def _lower_first(text: str) -> str:
    cleaned = _coerce_string(text)
    if not cleaned:
        return ""
    return cleaned[:1].lower() + cleaned[1:]


def _infer_tone(flavor: str) -> str:
    return {
        "editorial": "Тёплый, продуманный и с премиальным ощущением.",
        "technical": "Технический, точный и нацеленный на постоянный мониторинг.",
        "operational": "Точный, ясный и нацеленный на решения.",
        "minimal": "Сдержанный, лёгкий и очень сфокусированный.",
        "expressive": "Яркий, уверенный и запоминающийся.",
        "balanced": "Сбалансированный, современный и легко читаемый.",
    }[flavor]


def _infer_concept(flavor: str) -> str:
    return {
        "editorial": "Редакционный язык с ясной иерархией, неспешным ритмом и ощущением заботы.",
        "technical": "Технический интерфейс с высоким контрастом, ясными семантическими сигналами и мгновенным чтением состояния.",
        "operational": "Интерфейс для быстрого просмотра, сравнения и приоритизации информации.",
        "minimal": "Чистая и сфокусированная система с большим количеством воздуха и простой иерархией.",
        "expressive": "Направление с выразительным акцентом, ясным контрастом и узнаваемым характером.",
        "balanced": "Сбалансированное направление с ясной иерархией и сдержанным характером.",
    }[flavor]


def _infer_spacing_density(flavor: str) -> str:
    return {
        "editorial": "Воздушная, с дышащими блоками и неспешной иерархией.",
        "technical": "Высокая, с компактными блоками, чтением состояния и иерархией мониторинга.",
        "operational": "Выше средней, для быстрого просмотра и контролируемой плотности.",
        "minimal": "Воздушная, с большим негативным пространством и редкими сменами ритма.",
        "expressive": "Средняя, с динамичным ритмом и ясным контрастом между блоками.",
        "balanced": "Сбалансированная, с достаточными отступами и комфортным чтением.",
    }[flavor]


def _infer_sample_component(flavor: str) -> str:
    return {
        "editorial": "Редакционный hero с главным заголовком, кратким лидом и сдержанным CTA.",
        "technical": "Техническая панель с состояниями, временными рядами и контрастными семантическими алертами.",
        "operational": "Сводная панель с ключевыми метриками, видимым состоянием и контекстным CTA.",
        "minimal": "Продуктовый hero с главным преимуществом, социальным доказательством и доминирующим CTA.",
        "expressive": "Главная карточка или hero с доминирующим визуалом, коротким заголовком и очень ясным CTA.",
        "balanced": "Сводная секция с сильным заголовком, supporting copy и главным CTA.",
    }[flavor]


def _infer_context_signals(flavor: str) -> List[str]:
    return {
        "editorial": ["Нужно передать вкус, спокойствие и ощущение заботы."],
        "technical": ["Нужно обеспечить постоянный мониторинг, высокий контраст и быстрое чтение состояния."],
        "operational": ["Нужно обеспечить быстрое чтение, операционный фокус и низкую визуальную неоднозначность."],
        "minimal": ["Нужно дать мгновенную ясность и снизить визуальный шум."],
        "expressive": ["Нужно дать сильную айдентику и запоминаемость без потери читаемости."],
        "balanced": ["Нужно найти баланс между визуальным характером и удобством использования."],
    }[flavor]


def _signals_to_rationale_prefix(signals: List[str]) -> str:
    cleaned = [_coerce_string(item).rstrip(".!?") for item in signals if _coerce_string(item)]
    if not cleaned:
        return ""

    lowered = [_lower_first(item) for item in cleaned]
    need_prefixes = ("нужно ",)
    if all(item.startswith(need_prefixes) for item in lowered):
        needs = [
            next(item[len(prefix):] for prefix in need_prefixes if item.startswith(prefix))
            for item in lowered
        ]
        return f"Подходит, когда продукту нужно {_human_join(needs)}"

    return f"Подходит для контекста, где есть {_lower_first(_human_join(cleaned))}"


def _infer_rationale(proposal: Dict[str, Any], flavor: str) -> str:
    signals = proposal.get("context_signals", [])
    if signals:
        concept_phrase = _lower_first(
            _coerce_string(proposal["concept"] or _infer_concept(flavor)).rstrip(".!?")
        )
        return (
            f"{_signals_to_rationale_prefix(signals[:2])}, "
            f"потому что в основе лежит {concept_phrase}."
        )

    return {
        "editorial": "Подходит, когда продукту нужно передать вкус, спокойствие и ощущение заботы.",
        "technical": "Подходит, когда продукту нужны постоянный мониторинг, высокий контраст и однозначные семантические сигналы.",
        "operational": "Подходит, когда продукту нужны операционное доверие, быстрое чтение и фокус на задаче.",
        "minimal": "Подходит, когда продукту нужны мгновенная ясность, фокус и чистое первое впечатление.",
        "expressive": "Подходит, когда продукту нужны заметная айдентика и контролируемая энергия без потери читаемости.",
        "balanced": "Подходит, когда продукту нужны сдержанный характер и понятная иерархия.",
    }[flavor]


def _infer_not_this_direction(flavor: str) -> List[str]:
    return {
        "editorial": [
            "Это не плотный dashboard UI и не интерфейс для мониторинга.",
            "Не ищет цветовой агрессии или ощущения холодного технического продукта.",
        ],
        "technical": [
            "Это не lifestyle-предложение и не аспирационный маркетинг.",
            "Не ставит редакционное тепло и щедрый воздух выше чтения состояния.",
        ],
        "operational": [
            "Это не lifestyle- и не журнальное предложение.",
            "Не ставит орнамент выше операционной читаемости.",
        ],
        "minimal": [
            "Не максималистичное и не орнаментальное.",
            "Не стремится к тяжёлому или перегруженному enterprise-виду.",
        ],
        "expressive": [
            "Это не тихий и не нейтральный минимализм.",
            "Не стремится к плоской корпоративной эстетике без визуального напряжения.",
        ],
        "balanced": [
            "Не ищет визуального шума или орнаментальных решений без функции.",
            "Не гонится за крайней эстетикой ценой ясности.",
        ],
    }[flavor]


def _enrich_proposal_semantics(proposal: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(proposal)
    flavor = _infer_direction_flavor(enriched)

    if not enriched.get("tone"):
        enriched["tone"] = _infer_tone(flavor)
    if not enriched.get("concept"):
        enriched["concept"] = _infer_concept(flavor)
    if not enriched.get("spacing_density"):
        enriched["spacing_density"] = _infer_spacing_density(flavor)
    if not enriched.get("sample_component"):
        enriched["sample_component"] = _infer_sample_component(flavor)
    if not enriched.get("context_signals"):
        enriched["context_signals"] = _infer_context_signals(flavor)
    if not enriched.get("rationale"):
        enriched["rationale"] = _infer_rationale(enriched, flavor)
    if not enriched.get("not_this_direction"):
        enriched["not_this_direction"] = _infer_not_this_direction(flavor)
    if not enriched.get("visual_principles"):
        enriched["visual_principles"] = [
            _infer_concept(flavor),
            _infer_spacing_density(flavor),
        ]
    if not enriched.get("layout_grammar"):
        enriched["layout_grammar"] = _infer_sample_component(flavor)
    if not enriched.get("surface_treatment"):
        enriched["surface_treatment"] = _infer_tone(flavor)
    if not enriched.get("shape_language"):
        enriched["shape_language"] = _infer_concept(flavor)
    if not enriched.get("motion_language"):
        enriched["motion_language"] = "Сдержанные взаимодействия, согласованные с основной иерархией."
    if not enriched.get("signature_elements"):
        enriched["signature_elements"] = [enriched["sample_component"]]
    if not enriched.get("implementation_guardrails"):
        enriched["implementation_guardrails"] = list(enriched["not_this_direction"])
    if not enriched.get("prompt_seed"):
        enriched["prompt_seed"] = (
            f"Держи направление {flavor} согласованным с продуктом и не смешивай его с чужими визуальными системами."
        )

    return enriched


def _normalize_single_proposal(choice: str, proposal: Dict[str, Any]) -> Dict[str, Any]:
    name = _coerce_string(
        proposal.get("name")
        or proposal.get("label")
        or proposal.get("title")
        or choice
    )
    return _enrich_proposal_semantics({
        "choice": _coerce_string(choice),
        "name": name,
        "concept": _coerce_string(
            proposal.get("concept")
            or proposal.get("description")
            or proposal.get("summary")
            or proposal.get("pitch")
            or proposal.get("preview_copy")
        ),
        "style_family": _coerce_string(
            proposal.get("style_family")
            or proposal.get("style_trend")
            or proposal.get("trend_id")
            or proposal.get("style_id")
            or proposal.get("family")
        ),
        "style_family_label": _coerce_string(
            proposal.get("style_family_label")
            or proposal.get("trend_name")
            or proposal.get("style_name")
            or proposal.get("family_label")
        ),
        "palette_mode": _coerce_string(
            proposal.get("palette_mode")
            or proposal.get("color_mode")
            or proposal.get("palette_variant")
        ),
        "palette_mode_label": _coerce_string(
            proposal.get("palette_mode_label")
            or proposal.get("color_mode_label")
            or proposal.get("palette_variant_label")
        ),
        "variant_id": _coerce_string(
            proposal.get("variant_id")
            or proposal.get("variant")
        ),
        "variant_label": _coerce_string(
            proposal.get("variant_label")
            or proposal.get("variant_name")
        ),
        "preview_flavor": _coerce_string(proposal.get("preview_flavor")),
        "palette": _normalize_palette(proposal.get("palette")),
        "typography": _normalize_typography(proposal.get("typography")),
        "reference_urls": _normalize_reference_urls(
            proposal.get("reference_urls")
            or proposal.get("references")
            or proposal.get("example_urls")
            or proposal.get("inspiration_urls")
        ),
        "spacing_density": _coerce_string(
            proposal.get("spacing_density")
            or proposal.get("density")
            or proposal.get("spacing")
            or proposal.get("layout_density")
            or proposal.get("density_notes")
        ),
        "tone": _coerce_string(
            proposal.get("tone")
            or proposal.get("tone_visual")
            or proposal.get("tone_visual_general")
            or proposal.get("personality")
            or proposal.get("mood")
        ),
        "sample_component": _coerce_string(
            proposal.get("sample_component")
            or proposal.get("sample")
            or proposal.get("component")
            or proposal.get("component_example")
            or proposal.get("example_component")
            or proposal.get("hero_example")
        ),
        "visual_principles": _merge_unique_texts(
            proposal.get("visual_principles")
            or proposal.get("design_principles")
            or proposal.get("principles")
        ),
        "layout_grammar": _coerce_string(
            proposal.get("layout_grammar")
            or proposal.get("layout_principles")
            or proposal.get("composition_grammar")
        ),
        "surface_treatment": _coerce_string(
            proposal.get("surface_treatment")
            or proposal.get("surface_language")
            or proposal.get("materiality")
        ),
        "shape_language": _coerce_string(
            proposal.get("shape_language")
            or proposal.get("form_language")
            or proposal.get("shape_system")
        ),
        "motion_language": _coerce_string(
            proposal.get("motion_language")
            or proposal.get("motion_character")
            or proposal.get("interaction_motion")
        ),
        "signature_elements": _merge_unique_texts(
            proposal.get("signature_elements")
            or proposal.get("signature_motifs")
            or proposal.get("visual_motifs")
        ),
        "implementation_guardrails": _merge_unique_texts(
            proposal.get("implementation_guardrails")
            or proposal.get("guardrails")
            or proposal.get("execution_guardrails")
        ),
        "prompt_seed": _coerce_string(
            proposal.get("prompt_seed")
            or proposal.get("design_prompt")
            or proposal.get("prompt_injection")
        ),
        "rationale": _coerce_string(
            proposal.get("rationale")
            or proposal.get("why")
            or proposal.get("reason")
            or proposal.get("justification")
        ),
        "not_this_direction": _merge_unique_texts(
            proposal.get("not_this_direction")
            or proposal.get("anti_goals")
            or proposal.get("non_goals")
            or proposal.get("anti_patterns")
            or proposal.get("avoid")
        ),
        "tokens": _normalize_tokens(proposal.get("tokens")),
        "context_signals": _merge_unique_texts(
            proposal.get("context_signals"),
            proposal.get("signals"),
            proposal.get("audience"),
            proposal.get("product_signals"),
            proposal.get("constraints"),
            proposal.get("fit_for"),
        ),
    })


def load_style_proposals(proposals_file: str) -> Dict[str, Dict[str, Any]]:
    """Load and normalize the Designer proposals JSON sidecar."""
    with open(proposals_file, "r", encoding="utf-8") as fh:
        raw = json.load(fh)

    if isinstance(raw, dict) and isinstance(raw.get("proposals"), list):
        source = raw.get("proposals")
    else:
        source = raw

    proposals: Dict[str, Dict[str, Any]] = {}
    if isinstance(source, list):
        for entry in source:
            if not isinstance(entry, dict):
                continue
            choice = _coerce_string(entry.get("choice"))
            if not choice:
                continue
            proposals[choice] = _normalize_single_proposal(choice, entry)
    elif isinstance(source, dict):
        for choice, entry in source.items():
            if not isinstance(entry, dict):
                continue
            normalized_choice = _coerce_string(entry.get("choice") or choice)
            if not normalized_choice:
                continue
            proposals[normalized_choice] = _normalize_single_proposal(normalized_choice, entry)

    return proposals


def build_style_direction_record(
    visual_path: str,
    *,
    proposals_file: Optional[str] = None,
    choice_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Combine the recorded choice with the selected proposal."""
    selected_choice = read_latest_style_choice(visual_path)
    if selected_choice is None and not choice_override:
        raise ValueError("Пока не зарегистрировано ни одного корректного выбора.")

    proposals_path = proposals_file or discover_proposals_file(visual_path)
    if not proposals_path:
        raise ValueError("Файл с предложениями Designer не найден.")

    proposals = load_style_proposals(proposals_path)
    choice = _coerce_string(choice_override or (selected_choice or {}).get("choice"))
    if choice not in proposals:
        raise ValueError(f"Выбранного варианта '{choice}' нет в sidecar с предложениями.")

    proposal = proposals[choice]
    selected_label = _coerce_string((selected_choice or {}).get("label")) or proposal["name"]
    selected_at = _coerce_string((selected_choice or {}).get("timestamp"))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "choice": choice,
        "selected_label": selected_label,
        "selected_at": selected_at,
        "proposal": proposal,
        "proposals_file": proposals_path,
    }


def _render_table(headers: List[str], rows: List[List[str]]) -> List[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _fallback_text(value: str, fallback: str = "Пока не задокументировано.") -> str:
    return value or fallback


def _ensure_sentence(text: str) -> str:
    cleaned = _coerce_string(text)
    if not cleaned:
        return ""
    if cleaned[-1] in ".!?":
        return cleaned
    return f"{cleaned}."


def _proposal_source_label(record: Dict[str, Any]) -> str:
    proposals_file = _coerce_string(record.get("proposals_file"))
    if not proposals_file:
        return ""

    visual_session_dir = _coerce_string(record.get("visual_session_dir"))
    if visual_session_dir:
        try:
            session_root = os.path.abspath(visual_session_dir)
            proposals_path = os.path.abspath(proposals_file)
            if os.path.commonpath([session_root, proposals_path]) == session_root:
                return os.path.relpath(proposals_path, session_root)
        except ValueError:
            pass

    project_dir = _coerce_string(record.get("project_dir"))
    if project_dir:
        try:
            project_root = os.path.abspath(project_dir)
            proposals_path = os.path.abspath(proposals_file)
            if os.path.commonpath([project_root, proposals_path]) == project_root:
                return os.path.relpath(proposals_path, project_root)
        except ValueError:
            pass

    return os.path.basename(proposals_file)


def render_style_direction_markdown(record: Dict[str, Any]) -> str:
    """Build the final Markdown for docs/style-direction.md."""
    proposal = _normalize_single_proposal(
        _coerce_string(record.get("choice") or (record.get("proposal") or {}).get("choice") or "A"),
        dict(record["proposal"]),
    )
    decision_summary = _ensure_sentence(
        proposal["concept"] or proposal["tone"] or proposal["rationale"]
    ) or "Designer зарегистрировал выбранное направление, но визуальное намерение ещё нужно дополнить."
    rationale = _fallback_text(
        proposal["rationale"],
        "Ещё нужно объяснить, почему это предложение лучше остальных.",
    )
    proposals_source = _proposal_source_label(record)
    lines: List[str] = [
        "# Базовая дизайн-система",
        "",
        "## Сводка",
        "",
        f"Designer рекомендует `{record['choice']}` — {record['selected_label']} как базовую дизайн-систему для этой фазы.",
        "",
        f"Приоритет этого варианта: {decision_summary[0].lower() + decision_summary[1:] if len(decision_summary) > 1 else decision_summary.lower()}",
        "",
        f"- Рабочее название: **{proposal['name']}**",
    ]
    if record.get("selected_at"):
        lines.append(f"- Выбор зарегистрирован: {record['selected_at']}")
    lines.extend(
        [
            f"- Созданный артефакт: `{STYLE_DIRECTION_DOC_RELATIVE_PATH}`",
            "",
            "## Выбранная дизайн-система",
            "",
            f"**Название:** {proposal['name']}",
            "",
            f"**Концепция:** {_fallback_text(proposal['concept'])}",
            "",
        ]
    )

    if proposal.get("style_family_label") or proposal.get("style_family"):
        family_label = proposal.get("style_family_label") or proposal.get("style_family")
        lines.extend(
            [
                "### Основа системы",
                "",
                f"- Семейство: {family_label}",
            ]
        )
        if proposal.get("style_family"):
            lines.append(f"- Канонический id: `{proposal['style_family']}`")
        if proposal.get("palette_mode"):
            palette_mode_label = proposal.get("palette_mode_label") or proposal["palette_mode"]
            lines.append(f"- Режим палитры: **{palette_mode_label}**")
            if palette_mode_label != proposal["palette_mode"]:
                lines.append(f"- Id палитры: `{proposal['palette_mode']}`")
        if proposal.get("variant_label"):
            lines.append(f"- Финальный вариант: **{proposal['variant_label']}**")
        lines.append("")

    lines.extend(["### Палитра", ""])
    if proposal["palette"]:
        lines.extend(
            _render_table(
                ["Роль", "Значение"],
                [[item["role"], item["value"]] for item in proposal["palette"]],
            )
        )
    else:
        lines.append("Ещё не задокументировано.")

    lines.extend(["", "### Типографика", ""])
    typography = proposal["typography"]
    if typography:
        if typography.get("pairing_label"):
            lines.append(f"- Pairing: {typography['pairing_label']}")
        if typography.get("pairing_id"):
            lines.append(f"- Id pairing: `{typography['pairing_id']}`")
        if typography.get("headings"):
            lines.append(f"- Заголовки: {typography['headings']}")
        if typography.get("body"):
            lines.append(f"- Основной текст: {typography['body']}")
        if typography.get("scale"):
            lines.append(f"- Шкала: {typography['scale']}")
        if typography.get("notes"):
            lines.append(f"- Заметки: {typography['notes']}")
        if typography.get("headings_url"):
            lines.append(f"- URL headings: {typography['headings_url']}")
        if typography.get("body_url"):
            lines.append(f"- URL body: {typography['body_url']}")
        if typography.get("css_url"):
            lines.append(f"- CSS URL: {typography['css_url']}")
        if typography.get("source"):
            lines.append(f"- Источник шрифтов: {typography['source']}")
    else:
        lines.append("- Ещё не задокументировано.")

    lines.extend(
        [
            "",
            "### Отступы и плотность",
            "",
            _fallback_text(proposal["spacing_density"]),
            "",
            "### Общий визуальный тон",
            "",
            _fallback_text(proposal["tone"]),
            "",
            "### Пример компонента",
            "",
            _fallback_text(proposal["sample_component"]),
        ]
    )
    lines.extend(["", "## Выполнимые принципы системы", ""])
    if proposal["visual_principles"]:
        lines.extend(f"- {item}" for item in proposal["visual_principles"])
    else:
        lines.append("- Пока не задокументировано.")

    lines.extend(
        [
            "",
            "### Грамматика композиции",
            "",
            _fallback_text(proposal["layout_grammar"]),
            "",
            "### Обработка поверхностей",
            "",
            _fallback_text(proposal["surface_treatment"]),
            "",
            "### Язык формы",
            "",
            _fallback_text(proposal["shape_language"]),
            "",
            "### Язык движения",
            "",
            _fallback_text(proposal["motion_language"]),
            "",
            "### Фирменные элементы",
            "",
        ]
    )
    if proposal["signature_elements"]:
        lines.extend(f"- {item}" for item in proposal["signature_elements"])
    else:
        lines.append("- Пока не задокументировано.")

    lines.extend(["", "### Guardrails реализации", ""])
    if proposal["implementation_guardrails"]:
        lines.extend(f"- {item}" for item in proposal["implementation_guardrails"])
    else:
        lines.append("- Пока не задокументировано.")

    lines.extend(
        [
            "",
            "## Зерно направления",
            "",
            _fallback_text(proposal["prompt_seed"]),
            "",
            "## Почему выигрывает этот вариант",
            "",
            rationale,
            "",
            "## Чем эта система НЕ является",
            "",
        ]
    )
    if proposal["not_this_direction"]:
        lines.extend(f"- {item}" for item in proposal["not_this_direction"])
    else:
        lines.append("- Пока не определено.")

    lines.extend(["", "## Предлагаемые начальные токены", ""])
    if proposal["tokens"]:
        lines.extend(
            _render_table(
                ["Токен", "Начальное значение"],
                [[item["name"], item["value"]] for item in proposal["tokens"]],
            )
        )
    else:
        lines.append("Пока не задокументировано.")

    if proposal["context_signals"]:
        lines.extend(["", "## Сигналы контекста", ""])
        lines.extend(f"- {item}" for item in proposal["context_signals"])

    if proposal.get("reference_urls"):
        lines.extend(["", "## Визуальные референсы", ""])
        lines.extend(
            f"- [{item['label']}]({item['url']})"
            for item in proposal["reference_urls"]
        )

    lines.extend(
        [
            "",
            "## Метаданные",
            "",
            f"- Создано автоматически: {record['generated_at']}",
        ]
    )
    if proposals_source:
        lines.append(f"- Исходные предложения: `{proposals_source}`")
    return "\n".join(lines).rstrip() + "\n"


def write_style_direction_artifact(
    project_dir: str,
    visual_path: str,
    *,
    proposals_file: Optional[str] = None,
    choice_override: Optional[str] = None,
) -> Dict[str, Any]:
    """Write docs/style-direction.md from the chosen option."""
    record = build_style_direction_record(
        visual_path,
        proposals_file=proposals_file,
        choice_override=choice_override,
    )
    record["project_dir"] = project_dir
    record["visual_session_dir"] = resolve_visual_session_dir(visual_path)
    output_path = os.path.join(project_dir, STYLE_DIRECTION_DOC_RELATIVE_PATH)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(render_style_direction_markdown(record))
    return {
        "status": "ok",
        "artifact_path": output_path,
        "choice": record["choice"],
        "selected_label": record["selected_label"],
        "selected_at": record.get("selected_at", ""),
        "proposals_file": record.get("proposals_file", ""),
    }
