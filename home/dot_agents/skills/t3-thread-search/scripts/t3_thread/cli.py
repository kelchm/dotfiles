"""One command for thread discovery and execution diagnostics."""

from __future__ import annotations

import argparse
from typing import Sequence

from . import search, status


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t3-thread", description="Read-only T3 thread search and status.")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, module, summary in (
        ("search", search, "Find threads or inspect a thread's metadata."),
        ("status", status, "Inspect one thread's run, blockers, and recent activity."),
    ):
        options = module.build_parser()
        command = commands.add_parser(name, parents=[options], add_help=False,
                                      help=summary, description=options.description, epilog=options.epilog)
        command.set_defaults(handler=module.run)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)
