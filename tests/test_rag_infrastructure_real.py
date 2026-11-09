"""The two RAGs against the REAL Qdrant collections with vectors already stored in them (no model call, read only): skipped when the server or a collection is missing.
The checks themselves live in `movie_db/harness/evaluation/run_rag_infra_check.py`; this only runs them. It proves wiring and filters, not the semantic quality of a text query."""
from __future__ import annotations

import pytest

from movie_db.harness.evaluation import run_rag_infra_check as check

try:
    from qdrant_client import QdrantClient

    _client = QdrantClient(url=check.URL, timeout=5)
    names = {c.name for c in _client.get_collections().collections}
    READY = {"wikipedia_films_it_v3", "wikipedia_series_it_v1"} <= names and (check.ROOT / "cinema_db/data/cinema.v4.candidate6.sqlite3").is_file()
except Exception:  # noqa: BLE001  (no server: the test is skipped, not failed)
    READY = False


@pytest.mark.skipif(not READY, reason="needs Qdrant with both RAG collections and the schema-4 candidate")
def test_both_rags_work_on_their_collections_with_stored_vectors_and_hand_their_ids_to_cinema_sql(capsys):
    assert check.main([]) == 0, capsys.readouterr().out[-1500:]
