#!/usr/bin/env python3
"""Generates a gallery of visual demos from the Designer catalog."""

from __future__ import annotations

import argparse
import json
import os
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.designer_style_demo import write_style_demo_gallery


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a gallery and simple landings from the Designer design system catalog"
    )
    parser.add_argument(
        "--visual-path",
        required=True,
        help="Path to session_dir or state_dir of the visual server",
    )
    parser.add_argument("--title", help="Optional gallery title.")
    parser.add_argument("--subtitle", help="Optional gallery subtitle.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    result = write_style_demo_gallery(
        args.visual_path,
        title=args.title,
        subtitle=args.subtitle,
    )
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
