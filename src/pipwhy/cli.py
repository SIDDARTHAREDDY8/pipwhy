"""pipwhy CLI: pipe pip's error output in, get the conflict explained."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .analyze import analyze
from .parse import found_conflict, parse
from .report import render_json, render_text


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pipwhy",
        description="Explain pip's dependency-conflict errors: which "
                    "requirement is the blocker and how to fix it.")
    p.add_argument("file", nargs="?",
                   help="file containing pip's error output "
                        "(default: read stdin)")
    p.add_argument("--json", action="store_true",
                   help="emit machine-readable JSON instead of text")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.file:
            with open(args.file, encoding="utf-8",
                      errors="replace") as fh:
                text = fh.read()
        elif sys.stdin.isatty():
            print("pipwhy: waiting on stdin — pipe pip's error output in, e.g.\n"
                  "  pip install -r requirements.txt 2>&1 | pipwhy",
                  file=sys.stderr)
            text = sys.stdin.read()
        else:
            text = sys.stdin.read()
    except OSError as exc:
        print(f"pipwhy: cannot read input: {exc}", file=sys.stderr)
        return 1

    report = parse(text)
    if not found_conflict(report):
        print("pipwhy: no dependency conflict found in the input.\n"
              "Hint: capture pip's full stderr, e.g.\n"
              "  pip install -r requirements.txt 2>&1 | pipwhy",
              file=sys.stderr)
        return 1

    analysis = analyze(report)
    if args.json:
        sys.stdout.write(render_json(analysis))
    else:
        sys.stdout.write(render_text(analysis))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
