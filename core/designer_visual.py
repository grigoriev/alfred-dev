#!/usr/bin/env python3
"""Helpers to read the Designer visual choice."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional


STYLE_OPTION_SELECTOR = ".style-option"
STATE_DIRNAME = "state"
EVENTS_FILENAME = "events"


def resolve_state_dir(path: str) -> str:
    """Accept session_dir or state_dir and return the real state_dir."""
    candidate = os.path.abspath(path)
    if os.path.basename(candidate) == STATE_DIRNAME:
        return candidate
    return os.path.join(candidate, STATE_DIRNAME)


def events_file_for(path: str) -> str:
    """Return the events file path for a visual session."""
    return os.path.join(resolve_state_dir(path), EVENTS_FILENAME)


def _normalize_choice_event(raw_event: Dict[str, Any]) -> Optional[Dict[str, Optional[str]]]:
    """Normalize a click event in the legacy or canonical format."""
    if not isinstance(raw_event, dict):
        return None

    choice = raw_event.get("choice")
    if not isinstance(choice, str) or not choice.strip():
        return None

    event_type = raw_event.get("type")
    if event_type not in (None, "", "click"):
        return None

    element = raw_event.get("element")
    if element not in (None, "", STYLE_OPTION_SELECTOR):
        return None

    label = raw_event.get("label")
    if label is not None:
        label = str(label).strip() or None

    timestamp = raw_event.get("ts") or raw_event.get("timestamp")
    if timestamp is not None:
        timestamp = str(timestamp).strip() or None

    return {
        "choice": choice.strip(),
        "label": label,
        "timestamp": timestamp,
        "element": element or STYLE_OPTION_SELECTOR,
    }


def read_latest_style_choice(path: str) -> Optional[Dict[str, Optional[str]]]:
    """Read the last valid click of a Designer visual session."""
    events_path = events_file_for(path)
    if not os.path.isfile(events_path):
        return None

    latest_choice: Optional[Dict[str, Optional[str]]] = None
    with open(events_path, "r", encoding="utf-8") as fh:
        for line in fh:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw_event = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            normalized = _normalize_choice_event(raw_event)
            if normalized is not None:
                latest_choice = normalized

    return latest_choice
