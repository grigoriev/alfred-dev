#!/usr/bin/env python3
"""Generates the final round of three variants from the Designer guided selection."""

from __future__ import annotations

import argparse
import json
import os
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.designer_style_variants import write_guided_style_options


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate style-options.html/json from the Designer guided selection"
    )
    parser.add_argument("--visual-path", required=True, help="Path to session_dir or state_dir of the visual server")
    parser.add_argument("--style-id", help="Override the selected visual family.")
    parser.add_argument("--font-pairing-id", help="Override the selected font pairing.")
    parser.add_argument("--palette-mode", help="Override the selected palette mode.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = write_guided_style_options(
            args.visual_path,
            style_id=args.style_id,
            font_pairing_id=args.font_pairing_id,
            palette_mode=args.palette_mode,
        )
    except ValueError as exc:
        sys.stdout.write(
            json.dumps({"status": "pending", "message": str(exc)}, ensure_ascii=False) + "\n"
        )
        return 0

    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
