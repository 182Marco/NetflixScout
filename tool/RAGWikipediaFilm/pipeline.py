"""CLI of the pipeline: python -m tool.RAGWikipediaFilm.pipeline <command> (from the repository root)."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .config import PipelineConfig, load_config
from .download import download_dump
from .enrich_metadata import run_enrich
from .extract_films import run_extract
from .manifest import compare_films, verify_manifest, write_manifest

CONTACT_ENV = "RAGWIKI_WIKIDATA_CONTACT"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tool.RAGWikipediaFilm.pipeline", description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="YAML config (default: config.yaml)")
    parser.add_argument("--set", action="append", default=[], metavar="section.key=value",
                        help="override a config value (repeatable), e.g. --set wikidata.mode=online")
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)
    d = sub.add_parser("download", help="download the dated dump (resumable, SHA-1 verified)")
    d.add_argument("--max-bytes", type=int, default=None, help="fetch only a prefix into a .sample file")
    e = sub.add_parser("extract", help="dump -> candidates.jsonl (streaming)")
    e.add_argument("--dump", type=Path, default=None)
    e.add_argument("--limit", type=int, default=None, help="stop after N films")
    e.add_argument("--allow-truncated", action="store_true", help="accept a partial dump sample")
    e.add_argument("--no-resume", action="store_true")
    n = sub.add_parser("enrich", help="candidates.jsonl + Wikidata snapshot -> films.jsonl")
    n.add_argument("--limit", type=int, default=None)
    r = sub.add_parser("run", help="download + extract + enrich + manifest")
    r.add_argument("--limit", type=int, default=None)
    sub.add_parser("manifest", help="write manifests/build_manifest.json")
    sub.add_parser("verify", help="compare the files on disk with the manifest")
    c = sub.add_parser("compare", help="compare two films.jsonl files")
    c.add_argument("left", type=Path)
    c.add_argument("right", type=Path)
    return parser


def _config(args: argparse.Namespace) -> PipelineConfig:
    overrides: dict[str, object] = {}
    for item in args.set:
        key, _, value = item.partition("=")
        overrides[key] = int(value) if value.isdigit() else value
    if os.environ.get(CONTACT_ENV):
        overrides.setdefault("wikidata.contact", os.environ[CONTACT_ENV])
    return load_config(args.config, overrides)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = _config(args)
    if args.command == "download":
        download_dump(config, max_bytes=args.max_bytes)
    elif args.command == "extract":
        run_extract(config, dump_path=args.dump, limit=args.limit, allow_truncated=args.allow_truncated,
                    resume=not args.no_resume)
    elif args.command == "enrich":
        print(json.dumps(run_enrich(config, limit=args.limit), indent=2))
    elif args.command == "run":
        download_dump(config)
        run_extract(config, limit=args.limit)
        print(json.dumps(run_enrich(config, limit=args.limit), indent=2))
        print(write_manifest(config, args.config))
    elif args.command == "manifest":
        print(write_manifest(config, args.config))
    elif args.command == "verify":
        problems = verify_manifest(config, config_path=args.config)
        print("\n".join(problems) if problems else "OK: the build matches the manifest")
        return 1 if problems else 0
    elif args.command == "compare":
        report = compare_films(args.left, args.right)
        print(json.dumps(report, indent=2))
        return 0 if report["identical"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
