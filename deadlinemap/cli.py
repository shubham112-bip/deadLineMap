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
        description="Check NGINX and Gunicorn timeout settings.",
        epilog=(
            "Examples:\n"
            "  deadlinemap .\n"
            "  deadlinemap ./my-project --details\n"
            "  deadlinemap ./my-project --format json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subs = parser.add_subparsers(dest="command", required=True)
    cmd = subs.add_parser("scan", help="scan a project or supported config file")
    cmd.add_argument("path", type=Path, help="project folder or config file")
    cmd.add_argument(
        "-f", "--format", choices=("text", "json"), default="text",
        help="report format (default: text)",
    )
    cmd.add_argument(
        "--details", action="store_true",
        help="show parsed settings, all evidence, and rule assumptions",
    )
    cmd.add_argument(
        "--fail-on", choices=("risk", "needs-review", "never"), default="risk",
        help="exit with code 1 at this finding level (default: risk)",
    )
    return parser


def _normalise_argv(argv: list[str] | None) -> list[str]:
    """Allow a project path directly, as well as the explicit scan subcommand."""
    values = list(sys.argv[1:] if argv is None else argv)
    if values and values[0] not in {"scan", "-h", "--help", "--version"} and not values[0].startswith("-"):
        values.insert(0, "scan")
    return values


def main(argv: list[str] | None = None) -> int:
    values = _normalise_argv(argv)
    if not values:
        build_parser().print_help()
        return 0

    args = build_parser().parse_args(values)
    if not args.path.exists() or not (args.path.is_dir() or args.path.is_file()):
        print(f"deadlinemap: cannot read '{args.path}'", file=sys.stderr)
        return EXIT_IO
    try:
        result = scan(args.path)
    except (OSError, PermissionError) as exc:
        print(f"deadlinemap: scan failed: {exc}", file=sys.stderr)
        return EXIT_IO

    if args.format == "json":
        print(render_json(result))
    else:
        print(render_text(result, details=args.details))

    if not result.nginx_files and not result.gunicorn_files:
        return EXIT_NO_CONFIG
    if args.fail_on != "never":
        threshold = SEVERITY[args.fail_on]
        if any(SEVERITY.get(f.verdict, 99) <= threshold for f in result.findings):
            return EXIT_FINDINGS
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
