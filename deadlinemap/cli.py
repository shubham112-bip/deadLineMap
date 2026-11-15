"""DeadlineMap CLI."""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from deadlinemap import __version__
from deadlinemap.report import render_json, render_text
from deadlinemap.scanner import scan

EXIT_FINDINGS, EXIT_USAGE, EXIT_IO, EXIT_NO_CONFIG = 1, 2, 3, 4
SEVERITY = {"risk": 0, "needs-review": 1, "info": 2}

def build_parser():
    parser = argparse.ArgumentParser(
        prog="deadlinemap",
        description="Read-only timeout configuration analysis for NGINX and Gunicorn."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subs = parser.add_subparsers(dest="command", required=True)
    cmd = subs.add_parser("scan", help="scan a project or supported config file")
    cmd.add_argument("path", type=Path)
    cmd.add_argument("-f", "--format", choices=("text", "json"), default="text")
    cmd.add_argument("--fail-on", choices=("risk", "needs-review", "never"), default="risk")
    return parser

def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.path.exists() or not (args.path.is_dir() or args.path.is_file()):
        print(f"deadlinemap: error: cannot read '{args.path}'", file=sys.stderr)
        return EXIT_IO
    try:
        result = scan(args.path)
    except (OSError, PermissionError) as exc:
        print(f"deadlinemap: error: {exc}", file=sys.stderr)
        return EXIT_IO
    print(render_json(result) if args.format == "json" else render_text(result))
    if not result.nginx_files and not result.gunicorn_files:
        return EXIT_NO_CONFIG
    if args.fail_on != "never":
        threshold = SEVERITY[args.fail_on]
        if any(SEVERITY.get(f.verdict, 99) <= threshold for f in result.findings):
            return EXIT_FINDINGS
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
