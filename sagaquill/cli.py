from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from .client import OpenAICompatibleClient
from .codex import load_provider_config, provider_doctor
from .pipeline import NovelPipeline
from .projectio import project_input_from_dict, starter_project_input
from .util import dump_json, ensure_directory, load_json, slugify


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sagaquill", description="Generate complete fiction with a self-reviewing long-form agent flow.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="Inspect Codex config and auth.")
    doctor.add_argument("--codex-dir", default=None, help="Override the Codex config directory.")

    init_spec = subparsers.add_parser("init-spec", help="Write a starter project input JSON file.")
    init_spec.add_argument("--output", required=True, help="Path to the project input JSON file.")

    generate = subparsers.add_parser("generate", help="Run the novel generation pipeline.")
    generate.add_argument("--spec", required=True, help="Path to the project input JSON file.")
    generate.add_argument("--output-dir", default=None, help="Output directory for generated files.")
    generate.add_argument("--codex-dir", default=None, help="Override the Codex config directory.")
    generate.add_argument("--max-rewrites", type=int, default=2, help="Maximum per-chapter rewrite passes.")
    generate.add_argument("--max-final-polish-rounds", type=int, default=1, help="Maximum global polish rounds.")
    generate.add_argument("--no-stream", action="store_true", help="Disable streaming output for prose generation.")
    generate.add_argument("--resume", action="store_true", help="Resume from artifacts already written in the output directory.")

    serve = subparsers.add_parser("serve", help="Launch the local control panel.")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host.")
    serve.add_argument("--port", type=int, default=8765, help="Bind port.")
    serve.add_argument("--codex-dir", default=None, help="Override the Codex config directory.")
    serve.add_argument(
        "--batch-global-max-running",
        type=int,
        default=200,
        help="Global cap for simultaneously running jobs, including batch and single jobs.",
    )
    serve.add_argument(
        "--access-token",
        default=None,
        help="Require this bearer token for all panel/API requests. Also configurable via SAGAQUILL_ACCESS_TOKEN.",
    )
    serve.add_argument(
        "--allow-no-auth",
        action="store_true",
        help="Allow serving on a non-local host without access-token. Only use on trusted private networks.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "doctor":
        print(json.dumps(provider_doctor(args.codex_dir), ensure_ascii=False, indent=2))
        return 0

    if args.command == "init-spec":
        output_path = Path(args.output)
        ensure_directory(output_path.parent)
        dump_json(output_path, starter_project_input())
        print(str(output_path))
        return 0

    if args.command == "generate":
        project_input = load_project_input(args.spec)
        output_dir = Path(args.output_dir) if args.output_dir else Path("runs") / slugify(project_input.title)
        ensure_directory(output_dir)
        provider = load_provider_config(args.codex_dir)
        client = OpenAICompatibleClient(provider)
        pipeline = NovelPipeline(
            client,
            output_dir,
            flagship_model=provider.model,
            light_model=getattr(provider, "light_model", getattr(provider, "review_model", None)),
            review_model=getattr(provider, "review_model", getattr(provider, "light_model", None)),
            max_rewrites=args.max_rewrites,
            max_final_polish_rounds=args.max_final_polish_rounds,
            stream_output=not args.no_stream,
            resume=args.resume,
        )
        summary = pipeline.run(project_input)
        print(json.dumps(asdict(summary), ensure_ascii=False, indent=2))
        return 0

    if args.command == "serve":
        from .server import run_server

        run_server(
            host=args.host,
            port=args.port,
            codex_dir=args.codex_dir,
            batch_global_max_running=args.batch_global_max_running,
            access_token=args.access_token,
            require_auth=False if args.allow_no_auth else None,
        )
        return 0

    parser.print_help()
    return 1


def load_project_input(path: str | Path):
    payload = load_json(path)
    return project_input_from_dict(payload)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
