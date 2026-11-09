"""Shared helpers and paths of this package.

The generic components (dump reader, plot cleaning, Wikidata client) are COPIES of the film project's
ones (`dump.py`, `clean_plot.py`, `wikidata_client.py`): this package imports nothing from
`pipelines/wikipedia_films` (enforced by tests/test_tool_package.py). Only the dump FILE is shared, by path.
"""
from __future__ import annotations

from pathlib import Path

from .clean_plot import clean_wikitext, normalize_heading  # noqa: F401
from .dump import Page, iter_pages, open_dump  # noqa: F401
from .wikidata_client import Snapshot, WikidataClient, WikidataError  # noqa: F401

PACKAGE_DIR = Path(__file__).resolve().parent
FILM_DIR = PACKAGE_DIR.parent / "wikipedia_films"
DATA_DIR = PACKAGE_DIR / "data"
REPO = PACKAGE_DIR.parents[1]


def load_env() -> None:
    """Make the OpenAI key available to the evaluation scripts (the runtime retriever in `tool/rag/series` does not read `.env` itself)."""
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")


DUMP_DATE = "20261101"
# The 4 GiB dump FILE is shared read-only with the film project by path (data, not code): it is never
# copied or modified.
DUMP_PATH = FILM_DIR / "data" / "raw" / f"itwiki-{DUMP_DATE}-pages-articles.xml.bz2"
