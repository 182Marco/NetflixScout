"""A card is found when the answer names the film by its film-index (Italian) title, not by the English TMDb one."""
from __future__ import annotations

from tool.tmdb.enrich import _rag_title_forms
from web_lists.schema.llm.list_ref import TmdbRef
from web_lists.select.select_refs import _accepted

RECORD = {"source": "tmdb", "media_type": "movie", "id": 407559, "title": "I Am the Pretty Thing That Lives in the House", "release_date": "2016-10-28"}
ANSWER = "6. **Sono la bella creatura che vive in questa casa** (2016), regia di Oz Perkins."


def _ref() -> TmdbRef:
    return TmdbRef(source="tmdb", media_type="movie", id=407559, quote=ANSWER, reason="Una casa isolata.")


def test_without_the_italian_title_the_card_is_dropped():
    assert not _accepted(_ref(), ANSWER, {"tmdb:movie:407559": RECORD})


def test_with_the_film_index_title_as_alias_the_card_is_kept():
    record = {**RECORD, "aliases": _rag_title_forms("Sono la bella creatura che vive in questa casa")}
    assert _accepted(_ref(), ANSWER, {"tmdb:movie:407559": record})


def test_disambiguation_suffix_is_also_tried_without():
    assert _rag_title_forms("Relic (film 2020)") == ["Relic (film 2020)", "Relic"]
