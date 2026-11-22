#!/usr/bin/env python3
"""Generates the Designer guided selection screens."""

from __future__ import annotations

import argparse
import json
import os
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.designer_style_selector import write_style_selector_html


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the Designer base system screen or the typography/palette screen"
    )
    parser.add_argument("--visual-path", required=True, help="Path to session_dir or state_dir of the visual server")
    parser.add_argument(
        "--style-id",
        help="If set, renders the second screen with typography and palette combinations for that family.",
    )
    parser.add_argument("--title", help="Optional screen title.")
    parser.add_argument("--subtitle", help="Optional screen subtitle.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    result = write_style_selector_html(
        args.visual_path,
        style_id=args.style_id,
        title=args.title,
        subtitle=args.subtitle,
    )
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
