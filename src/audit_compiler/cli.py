"""Command line entry points for the Evidentia audit compiler."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from audit_compiler.compiler import compile_dossier
from audit_compiler.inventory import inventory_dossier
from audit_compiler.pipeline import compile_engagement


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="admissible", description="Evidentia audit compiler")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inventory = subparsers.add_parser("inventory", help="hash and inventory a dossier directory")
    inventory.add_argument("dossier", type=Path, help="directory containing supplied source files")
    inventory.add_argument("--output", type=Path, help="write JSON manifest to this path")

    compile_command = subparsers.add_parser(
        "compile",
        help="compile a dossier end-to-end and emit the cases.json replay bundle",
    )
    compile_command.add_argument("dossier", type=Path, help="directory containing the dossier")
    compile_command.add_argument("--name", type=str, help="engagement display name")
    compile_command.add_argument(
        "--cases-out", type=Path, help="write the cases.json replay bundle to this path"
    )
    compile_command.add_argument("--output", type=Path, help="alias for --cases-out")

    store = subparsers.add_parser(
        "store", help="compile GDPdU/XLSX sources into a local DuckDB evidence store (M1)"
    )
    store.add_argument("dossier", type=Path, help="directory containing the dossier")
    store.add_argument("--database", type=Path, help="override the DuckDB output path")
    store.add_argument("--output", type=Path, help="write the JSON compilation report here")

    serve = subparsers.add_parser("serve", help="serve the FastAPI review API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main(argv: list[str] | None = None) -> None:
    try:  # load local secrets (OPENAI/COGNEE keys) if present; harmless if absent
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass
    args = build_parser().parse_args(argv)
    if args.command == "inventory":
        manifest = inventory_dossier(args.dossier)
        serialized = manifest.model_dump_json(indent=2) + "\n"
        _emit(serialized, args.output)
    elif args.command == "compile":
        bundle = compile_engagement(args.dossier, name=args.name)
        serialized = json.dumps(bundle, indent=2, ensure_ascii=False) + "\n"
        _emit(serialized, args.cases_out or args.output)
        counts = bundle["engagement"]["counts"]
        print(
            f"Compiled {counts['source_files']} files: "
            f"{counts['confirmed']} confirmed, {counts['human_review']} for review, "
            f"{counts['dismissed']} dismissed."
        )
    elif args.command == "store":
        report = compile_dossier(args.dossier, database=args.database)
        _emit(report.model_dump_json(indent=2) + "\n", args.output)
        if report.errors:
            raise SystemExit(1)
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("audit_compiler.api.app:app", host=args.host, port=args.port)


def _emit(serialized: str, output: Path | None) -> None:
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    else:
        print(serialized, end="")
