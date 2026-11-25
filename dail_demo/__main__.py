"""Command line entry point: ``python -m dail_demo <command>``.

* ``check``: the startup checks (L0).
* ``evaluate``: one candidate under DAIL (C) and target-only (A), with a trace (B, L1 and L2).
* ``generate``: Gemini repair attempts through DAIL's generator, each valid one evaluated (B, L2).
"""

from __future__ import annotations

import argparse
import os
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

    evaluate = commands.add_parser("evaluate", help="evaluate one candidate under DAIL and target-only")
    evaluate.add_argument("--scenario", required=True, help="canonical or a curated TerraPreserve id")
    evaluate.add_argument(
        "--patch",
        required=True,
        help="safe or regression (canonical), fixed (TerraPreserve step 1), or a directory (typed)",
    )
    evaluate.add_argument("--out", help="write the trace here (never inside a repository)")

    generate = commands.add_parser("generate", help="ask Gemini for a repair and evaluate it")
    generate.add_argument("--scenario", required=True, help="canonical or a curated TerraPreserve id")
    generate.add_argument("--attempts", type=int, default=3, help="attempts within DAIL's generator (1-3)")
    generate.add_argument("--out", help="write the trace here (never inside a repository)")

    bundle = commands.add_parser("bundle", help="build site/vendor/ (DAIL, the core, scenarios, Pyodide)")
    bundle.add_argument(
        "--pyodide",
        help="a folder with the Pyodide 0.27.7 files to copy in (default: check the ones in site/vendor)",
    )
    commands.add_parser("record", help="record the site's replays into site/runs/ (local engine, gate on)")
    return parser


def _evaluate(args: argparse.Namespace) -> int:
    from dail_demo.engine import run_evaluate, summary_lines
    from dail_demo.settings import SetupError

    try:
        outcome = run_evaluate(args.scenario, args.patch, environ=os.environ, out=args.out)
    except SetupError as error:
        print(f"FAIL evaluate: {error}")
        return 1
    for line in summary_lines(outcome.trace, outcome.path):
        print(line)
    return outcome.exit_code


def _generate(args: argparse.Namespace) -> int:
    from dail_demo.generate import run_generate, summary_lines
    from dail_demo.settings import SetupError

    try:
        outcome = run_generate(args.scenario, attempts=args.attempts, environ=os.environ, out=args.out)
    except SetupError as error:
        print(f"FAIL generate: {error}")
        return 1
    for line in summary_lines(outcome.trace, outcome.path):
        print(line)
    return outcome.exit_code


def _bundle(args: argparse.Namespace) -> int:
    from pathlib import Path

    from dail_demo.bundle import bundle
    from dail_demo.settings import SetupError

    try:
        summary = bundle(os.environ, pyodide=None if args.pyodide is None else Path(args.pyodide))
    except SetupError as error:
        print(f"FAIL bundle: {error}")
        return 1
    print(f"bundle: {summary['out']}")
    print(f"  dail/: {summary['dail_files']} DAIL files, byte-identical to the committed dail-v1.0")
    print(f"  bundled for the browser: {summary['bundled_files']} files, {summary['bundled_bytes']:,} bytes")
    print(f"  pyodide: {summary['pyodide_bytes']:,} bytes, every file matches its pinned SHA-256")
    print(f"  scenarios: {', '.join(summary['scenarios'])}")
    return 0


def _record(args: argparse.Namespace) -> int:
    from dail_demo.record import run_record
    from dail_demo.settings import SetupError

    try:
        summary = run_record(os.environ)
    except SetupError as error:
        print(f"FAIL record: {error}")
        return 1
    print(f"record: {summary['runs']} runs written to {summary['out']} (Gemini: {summary['gemini']})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        results = run_checks()
        for result in results:
            print(format_result(result))
        return exit_code(results)
    if args.command == "evaluate":
        return _evaluate(args)
    if args.command == "generate":
        return _generate(args)
    if args.command == "bundle":
        return _bundle(args)
    if args.command == "record":
        return _record(args)
    return 2  # unreachable: argparse rejects unknown commands


if __name__ == "__main__":
    sys.exit(main())
