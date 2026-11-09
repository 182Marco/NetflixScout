"""CLI:  python -m pipelines.wikipedia_films.indexing <plan|embed|verify|index|check|retrieval> [options]   (from the repository root)"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import settings as S


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="indexing")
    p.add_argument("command", choices=["plan", "embed", "verify", "index", "check", "retrieval"])
    p.add_argument("--recreate", action="store_true", help="index: drop and rebuild ONLY the wikipedia collection")
    p.add_argument("--max-usd", type=float, default=S.MAX_USD)
    p.add_argument("--workers", type=int, default=S.WORKERS)
    a = p.parse_args(argv)
    S.DATA.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler(S.LOG)])
    for _n in ("httpx", "httpx2", "httpcore"):
        logging.getLogger(_n).setLevel(logging.WARNING)  # keep the log readable (no secrets there anyway)
    if a.command == "plan":
        from .embed_run import preflight
        from .units import build_units
        print(json.dumps(preflight(build_units()), indent=1))
    elif a.command == "embed":
        from .embed_run import run
        print(json.dumps(run(max_usd=a.max_usd, workers=a.workers), indent=1))
    elif a.command == "verify":
        from .verify_embeddings import verify
        r = verify()
        print(json.dumps(r, indent=1))
        return 0 if r["ok"] else 1
    elif a.command == "index":
        from .qdrant_index import build_index
        print(json.dumps(build_index(recreate=a.recreate), indent=1))
    elif a.command == "check":
        from .qdrant_index import check_index
        r = check_index()
        print(json.dumps(r, indent=1))
        return 0 if r["ok"] else 1
    elif a.command == "retrieval":
        from .retrieval_eval import evaluate
        print(json.dumps(evaluate(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
