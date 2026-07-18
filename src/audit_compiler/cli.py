"""Command line entry points for the standalone compiler package."""

from __future__ import annotations

import argparse
from pathlib import Path

from audit_compiler.compiler import compile_dossier
from audit_compiler.inventory import inventory_dossier


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="admissible", description="Admissible audit compiler")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory = subparsers.add_parser("inventory", help="hash and inventory a dossier directory")
    inventory.add_argument("dossier", type=Path, help="directory containing supplied source files")
    inventory.add_argument("--output", type=Path, help="write JSON manifest to this path")
    compile_command = subparsers.add_parser(
        "compile", help="compile GDPdU-declared files into a local DuckDB evidence store"
    )
    compile_command.add_argument("dossier", type=Path, help="directory containing the dossier")
    compile_command.add_argument("--database", type=Path, help="override the DuckDB output path")
    compile_command.add_argument("--output", type=Path, help="write JSON report to this path")
    return parser


def _emit_json(serialized: str, output: Path | None) -> None:
    if output:
        output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if args.command == "inventory":
        manifest = inventory_dossier(args.dossier)
        serialized = manifest.model_dump_json(indent=2) + "\n"
        _emit_json(serialized, args.output)
    elif args.command == "compile":
        report = compile_dossier(args.dossier, database=args.database)
        _emit_json(report.model_dump_json(indent=2) + "\n", args.output)
        if report.errors:
            raise SystemExit(1)
