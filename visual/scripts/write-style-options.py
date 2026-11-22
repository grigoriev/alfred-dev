#!/usr/bin/env python3
"""Generates style-options.html from the Designer proposals sidecar."""

from __future__ import annotations

import argparse
import json
import os
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.designer_style_options import write_style_options_html


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate style-options.html from the Designer sidecar")
    parser.add_argument("--visual-path", required=True, help="Path to session_dir or state_dir of the visual server")
    parser.add_argument(
        "--proposals-file",
        help="Optional path to the proposals JSON sidecar. Detected automatically if omitted.",
    )
    parser.add_argument("--title", help="Optional title for the selection screen.")
    parser.add_argument("--subtitle", help="Optional subtitle for the selection screen.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = write_style_options_html(
            args.visual_path,
            proposals_file=args.proposals_file,
            title=args.title,
            subtitle=args.subtitle,
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
