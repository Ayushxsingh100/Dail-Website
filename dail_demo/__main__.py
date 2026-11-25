"""Command line entry point: ``python -m dail_demo <command>``.

L0 provides one command, ``check``, which runs the startup checks.
"""

from __future__ import annotations

import argparse
import sys

from dail_demo import DEMO_LABEL, __version__
from dail_demo.environment import exit_code, format_result, run_checks


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m dail_demo",
        description=f"DAIL Live {__version__} ({DEMO_LABEL}).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="run the startup checks and exit")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        results = run_checks()
        for result in results:
            print(format_result(result))
        return exit_code(results)
    return 2  # unreachable: argparse rejects unknown commands


if __name__ == "__main__":
    sys.exit(main())
