"""Fixed choices of Phase 3 (approved after the Phase 2 benchmark, see PHASE2_BENCHMARK.md). Not in config.yaml on purpose:
changing config.yaml would change the SHA-256 recorded in the Phase 1 manifest."""
from __future__ import annotations

import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # pipelines/wikipedia_films
REPO = ROOT.parents[1]
FILMS = ROOT / "data" / "processed" / "films.jsonl"
RUN_ID = "itwiki-20261101-large1536"
DATA = ROOT / "data" / "embeddings" / RUN_ID
SHARDS = DATA / "shards"
LOG = DATA / "embed.log"
MANIFEST = ROOT / "manifests" / "embeddings_manifest.json"  # already git-ignored (README, section 7)
QUERY_CACHE = DATA / "queries"

# --- embedding
MODEL = "text-embedding-3-large"
DIMENSIONS = 1536                    # `dimensions` parameter of the API (Phase 2: no measurable loss vs 3072)
PRICE_PER_M_TOKENS = 0.13            # USD, standard price read on 2026-11-04
MAX_INPUT_TOKENS = 8191              # hard limit of text-embedding-3-* per input
MAX_USD = 5.0                        # budget authorised for the embeddings
EXCEPTION_CHUNK_TOKENS = 3000        # target size of the chunks of the plots over the limit
REQUEST_MAX_INPUTS = 128             # per API request (the API allows 2048 inputs / 300k tokens)
REQUEST_MAX_TOKENS = 120_000
WORKERS = 6
MAX_ATTEMPTS = 8

# --- Qdrant
QDRANT_URL = "http://127.0.0.1:6333"
COLLECTION = "wikipedia_films_it"
COLLECTION_V2 = "wikipedia_films_it_v2"             # built from data/clean/films.clean.jsonl (Phase 7); v1 is never touched by it
COLLECTION_V3 = "wikipedia_films_it_v3"             # clean_v3 catalogue (2026-11-04): v2 plus Aftershock and the retrieval fields
FORBIDDEN_COLLECTIONS = {"netflix_scout"}          # the old RAG: never read-write from here
QDRANT_NAMESPACE = uuid.UUID("0b5a3c7e-6d0e-4a52-9a6c-5e1f3b2d8c41")  # fixed forever: it defines every point id
UPSERT_BATCH = 256


TEST_PREFIX = "test_wikipedia_"  # throw-away collections of the tests (memory / temporary path)


def assert_own_collection(name: str) -> None:
    """Every write/delete goes through this check: only the Wikipedia collection (or a test one) may be touched."""
    if name in FORBIDDEN_COLLECTIONS or not (name in (COLLECTION, COLLECTION_V2, COLLECTION_V3) or name.startswith(TEST_PREFIX)):
        raise SystemExit(f"refusing to operate on collection '{name}': only '{COLLECTION}', '{COLLECTION_V2}' and '{COLLECTION_V3}' belong to this phase")
