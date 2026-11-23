#!/usr/bin/env python3
"""Classify a Russian prompt and suggest the Alfred route without a slash."""

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


# Order matters: the first match wins.
_RULES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    (
        "resume",
        (
            r"\bresume\b",
            r"\bпродолж\w*",
            r"\bдальше\b",
            r"\bвозобнов\w*",
            r"на чем (мы )?остановил",
            r"где (мы )?остановил",
            r"\bвернемся к\b|\bвернись к\b",
        ),
    ),
    (
        "pause",
        (
            r"\bпауз\w*",
            r"\bприостанов\w*",
            r"\bна сегодня все\b",
            r"\bзакончим на сегодня\b",
        ),
    ),
    (
        "uat",
        (
            r"\buat\b",
            r"\bприемк\w*",
            r"ручн\w* проверк\w*",
            r"одобрено пользовател\w*",
            r"\bотклонен\w*",
            r"провер\w* результат\w*",
        ),
    ),
    (
        "pr",
        (
            r"\bpr\b",
            r"\bpull request\w*",
            r"\bпулл?[- ]?реквест\w*",
            r"\bсмерж\w*",
            r"\bвмерж\w*",
            r"\bмерж\w*",
        ),
    ),
    (
        "ship",
        (
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
            r"второе мнение",
            r"взгляд со стороны",
        ),
    ),
    (
        "audit",
        (
            r"\bowasp\b",
            r"\bаудит\w*",
            r"безопасност\w* (репо|репозитория|проекта|кода)",
            r"провер\w* безопасност\w*",
        ),
    ),
    (
        "map-codebase",
        (
            r"\bbrownfield\b",
            r"карт\w* (кодовой базы|кода|репо|репозитория)",
            r"что (есть )?в этом репо",
            r"разбер\w* (в )?(репо|репозитори|код)",
        ),
    ),
    (
        "progress",
        (
            r"\bkanban\b",
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
            r"что (мы )?решили",
            r"почему (мы )?выбрали",
            r"последн\w* решени\w*",
        ),
    ),
    (
        "fix",
        (
            r"\b(bug|error|exception)\b",
            r"\b500\b",
            r"\bбаг\w*",
            r"\bошибк\w*",
            r"\bпада\w*",
            r"\bупал\w*",
            r"\bсломал\w*",
            r"\bсломан\w*",
            r"не работает",
            r"не (открывается|грузится|загружается)",
            r"\bрегресс\w*",
            r"\bкраш\w*|\bкрэш\w*",
        ),
    ),
    (
        "discuss",
        (
            r"не знаю,? (как|что|стоит ли|ли)",
            r"что (ты )?думаешь",
            r"как тебе",
            r"\bесть идея\b",
            r"как (лучше|бы ты)",
            r"\bпосоветуй\w*",
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
            r"\bfeature\b",
            r"\bфич\w*",
            r"\bдобав\w*",
            r"нов\w* функци\w*",
            r"хотим,? чтобы",
            r"\bреализ\w*",
        ),
    ),
    (
        "quick",
        (
            r"\btypo\b",
            r"\bcta\b",
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
    "resume": "/alfred-dev:resume",
    "pause": "/alfred-dev:pause",
    "uat": "/alfred-dev:uat",
    "pr": "/alfred-dev:pr",
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


_HARNESS_MESSAGE_RE = re.compile(r"^\s*<(task-notification|system-reminder)>")


def _is_harness_message(text: str) -> bool:
    """Return True for messages that the harness sends, not the user."""
    return bool(_HARNESS_MESSAGE_RE.match(text))


def classify_prompt(text: str) -> Optional[Dict[str, str]]:
    """Return the suggested route, or None if there is no signal or a slash command is present."""
    if not (text or "").strip() or _has_slash_command(text) or _is_harness_message(text):
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
            f"This prompt asks about a past decision. Check the memory "
            f"or `docs/adr/` and act as `{command}`. Do not invent history."
        )
    return (
        f"This prompt without a slash command matches `{command}`. "
        f"Act as that command. Do not ask the user to type it."
    )
