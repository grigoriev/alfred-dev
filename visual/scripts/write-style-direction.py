#!/usr/bin/env python3
"""Generates docs/style-direction.md from the Designer choice."""

from __future__ import annotations

import argparse
import json
import os
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.designer_style_direction import write_style_direction_artifact


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate docs/style-direction.md from the Designer choice")
    parser.add_argument("--project-dir", required=True, help="Project root path")
    parser.add_argument("--visual-path", required=True, help="Path to session_dir or state_dir of the visual server")
    parser.add_argument(
        "--proposals-file",
        help="Optional path to the proposals JSON sidecar. Detected automatically if omitted.",
    )
    parser.add_argument(
        "--choice",
        help="Override the recorded choice and force a given sidecar option.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        result = write_style_direction_artifact(
            os.path.abspath(args.project_dir),
            args.visual_path,
            proposals_file=args.proposals_file,
            choice_override=args.choice,
        )
    except ValueError as exc:
        payload = {
            "status": "pending",
            "message": str(exc),
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return 0

    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
