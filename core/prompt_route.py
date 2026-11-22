#!/usr/bin/env python3
"""Clasifica un prompt en castellano y sugiere la ruta Alfred sin slash."""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Optional, Tuple


def _fold(text: str) -> str:
    composed = unicodedata.normalize("NFC", text or "").lower().replace("ё", "е")
    out = []
    for char in composed:
        if ord(char) < 128 or "\u0400" <= char <= "\u04ff":
            out.append(char)
            continue
        decomposed = unicodedata.normalize("NFKD", char)
        out.append(decomposed.encode("ascii", "ignore").decode("ascii"))
    return "".join(out).strip()


def _has_slash_command(text: str) -> bool:
    stripped = (text or "").lstrip()
    if stripped.startswith("/"):
        return True
    return bool(re.search(r"(?m)^/alfred-dev:", text or ""))


# Orden: el primero que encaja gana.
_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "retomar",
        (
            r"\b(sigue|seguir|continua|continuar|retoma|retomar)\b",
            r"donde lo deje",
            r"por donde iba",
            r"\bresume\b",
            r"\bпродолж\w*",
            r"\bдальше\b",
            r"\bвозобнов\w*",
            r"на чем (мы )?остановил",
            r"\bвернемся к\b",
        ),
    ),
    (
        "pause",
        (
            r"\bpausa(r)?\b",
            r"\bпауз\w*",
            r"\bприостанов\w*",
            r"\bна сегодня все\b",
        ),
    ),
    (
        "uat",
        (
            r"\buat\b",
            r"aceptacion (manual|humana)",
            r"aprobado por (el )?usuario",
            r"rechazado",
            r"verificar (el )?entregable",
            r"\bприемк\w*",
            r"одобрено пользовател\w*",
            r"\bотклонен\w*",
            r"провер\w* результат\w*",
        ),
    ),
    (
        "ship",
        (
            r"\b(despliega|desplegar|publica|publicar)\b",
            r"\ba produccion\b",
            r"\brelease\b",
            r"\bship\b",
            r"\bрелиз\w*",
            r"\bдепло\w*",
            r"\bвыкат\w*",
            r"\bразверн\w*",
            r"\bразвертыван\w*",
            r"\bопубликова\w*|\bопубликуй\w*",
            r"\b(в|на) прод\b|\bв продакшн\w*",
        ),
    ),
    (
        "cto",
        (
            r"\bcto\b",
            r"\bтехническ\w* директор\w*",
            r"\blucius\b",  # alias legacy
            r"\bлюциус\w*",  # alias legacy
            r"segunda opinion",
            r"второе мнение",
        ),
    ),
    (
        "audit",
        (
            r"\baudi(t|ta|tar|toria)\b",
            r"\bowasp\b",
            r"seguridad del (repo|proyecto)",
            r"\bаудит\w*",
            r"безопасност\w* (репо|репозитория|проекта)",
        ),
    ),
    (
        "map-codebase",
        (
            r"\bmapea\b",
            r"mapa del (repo|codigo|codebase)",
            r"que hay en este repo",
            r"\bbrownfield\b",
            r"карт\w* (кодовой базы|кода|репо|репозитория)",
            r"что (есть )?в этом репо",
        ),
    ),
    (
        "progress",
        (
            r"como va( el proyecto)?\b",
            r"que hay abierto",
            r"\bkanban\b",
            r"estado del (flujo|proyecto)",
            r"\bстатус\w*",
            r"\bпрогресс\w*",
            r"как (идут дела|продвигается|там проект)",
            r"что (сейчас )?открыто",
            r"\bканбан\w*",
            r"состояние (процесса|проекта)",
        ),
    ),
    (
        "memory",
        (
            r"que decidimos",
            r"por que elegimos",
            r"ultima decision",
            r"что (мы )?решили",
            r"почему (мы )?выбрали",
            r"последн\w* решени\w*",
        ),
    ),
    (
        "fix",
        (
            r"\b(peta|falla|fallo|rompe|roto|bug|error|regresion)\b",
            r"no funciona",
            r"\b500\b",
            r"\bexception\b",
            r"\bбаг\w*",
            r"\bошибк\w*",
            r"\bпада\w*",
            r"\bупал\w*",
            r"\bсломал\w*",
            r"\bсломан\w*",
            r"не работает",
            r"\bрегресс\w*",
            r"\bкраш\w*|\bкрэш\w*",
        ),
    ),
    (
        "discuss",
        (
            r"no se (si|que|como)",
            r"que te parece",
            r"\baterrizar\b",
            r"\buna idea\b",
            r"не знаю,? (как|что|стоит ли|ли)",
            r"что (ты )?думаешь",
            r"как тебе",
            r"\bесть идея\b",
        ),
    ),
    (
        "spike",
        (
            r"\bspike\b",
            r"\bисследу\w*",
            r"\bисследова\w*",
            r"\bсравни\w*",
        ),
    ),
    (
        "feature",
        (
            r"nueva funcionalidad",
            r"\bfeature\b",
            r"queremos que",
            r"implementar (un|una|el|la)",
            r"\bфич\w*",
            r"\bдобав\w*",
            r"нов\w* функци\w*",
            r"хотим,? чтобы",
        ),
    ),
    (
        "quick",
        (
            r"\b(cambia|cambiar|ajusta|ajustar|renombra|renombrar)\b",
            r"\btypo\b",
            r"\bcta\b",
            r"texto del",
            r"\bпоменя\w*",
            r"\bизмени(ть)?\b",
            r"\bпоправ\w*",
            r"\bподправ\w*",
            r"\bпереимену\w*",
            r"\bопечатк\w*",
            r"текст (кнопки|на)",
        ),
    ),
)

_COMMAND_HINT = {
    "retomar": "/alfred-dev:retomar",
    "pause": "/alfred-dev:pause",
    "uat": "/alfred-dev:uat",
    "ship": "/alfred-dev:ship",
    "cto": "/alfred-dev:cto",
    "audit": "/alfred-dev:audit",
    "map-codebase": "/alfred-dev:map-codebase",
    "progress": "/alfred-dev:progress",
    "memory": "/alfred-dev:alfred",
    "fix": "/alfred-dev:fix",
    "discuss": "/alfred-dev:discuss",
    "spike": "/alfred-dev:spike",
    "feature": "/alfred-dev:feature",
    "quick": "/alfred-dev:quick",
}


def classify_prompt(text: str) -> Optional[Dict[str, str]]:
    """Devuelve la ruta sugerida o None si no hay señal o ya hay slash."""
    if not (text or "").strip() or _has_slash_command(text):
        return None
    folded = _fold(text)
    if len(folded) < 4:
        return None
    for route, patterns in _RULES:
        for pattern in patterns:
            if re.search(pattern, folded):
                return {
                    "route": route,
                    "command": _COMMAND_HINT[route],
                }
    return None


def render_route_hint(match: Dict[str, str]) -> str:
    command = match["command"]
    if match["route"] == "memory":
        return (
            f"Этот запрос спрашивает о решении. Загляни в память "
            f"или `docs/adr/` и действуй как `{command}`. Не выдумывай историю."
        )
    return (
        f"Этот запрос без slash подходит под `{command}`. "
        f"Действуй как эта команда. Не проси пользователя её вводить."
    )
