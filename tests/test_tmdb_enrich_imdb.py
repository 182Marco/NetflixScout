"""RAG -> TMDb completion in IMDb mode (the film index): one `/find` per RETURNED film, never a title search, never more than max_candidates."""
from __future__ import annotations

from tmdb_support import make_tool

from tool.tmdb.enrich import ENRICHMENT_KEY, TmdbRagEnricher, select_candidates


def _found(movie_id: int, title: str) -> dict:
    return {"movie_results": [{"id": movie_id, "title": title, "original_title": title, "release_date": "2018-06-07", "poster_path": f"/{movie_id}.jpg",
                               "overview": "x", "vote_average": 7.0, "vote_count": 100, "popularity": 10.0}],
            "tv_results": [], "person_results": []}


def _chunk(title, year, imdb):
    return {"title": title, "release_year": str(year), "imdb_id": imdb, "cast": "Attore A; Attore B"}


def _enrich(chunks, routes, max_candidates=5):
    tool, transport = make_tool(routes)
    result = TmdbRagEnricher(tool=tool, max_candidates=max_candidates, by_imdb_only=True).enrich(
        tool_result={"query": "q", "chunks": chunks, "metadata": {}, "trace": []})
    return result, transport


def test_candidates_carry_their_imdb_id():
    assert select_candidates([_chunk("Hereditary", 2018, "tt7784604")], 5)[0].imdb_id == "tt7784604"


def test_one_find_per_returned_film_and_a_card_with_the_poster():
    routes = {"/find/tt7784604": _found(493922, "Hereditary"), "/find/tt1234567": _found(7, "Altro")}
    result, transport = _enrich([_chunk("Hereditary", 2018, "tt7784604"), _chunk("Altro", 2018, "tt1234567")], routes)

    rows = result["metadata"][ENRICHMENT_KEY]["candidates"]
    assert [r["status"] for r in rows] == ["matched", "matched"] and rows[0]["matched_by"] == "imdb_id"
    assert [p for p in transport.paths if p.startswith("/find")] == ["/find/tt7784604", "/find/tt1234567"]
    assert not any(p.startswith(("/search", "/movie")) for p in transport.paths)       # never a title search, never a details call
    items = result["trace"][-1]["data"]["items"]
    assert [i["id"] for i in items] == [493922, 7] and all(i.get("poster_path") for i in items)


def test_a_film_without_an_imdb_id_is_skipped_not_searched_by_title():
    result, transport = _enrich([_chunk("Senza IMDb", 2001, None)], {})
    assert result["metadata"][ENRICHMENT_KEY]["candidates"][0] == {"rank": 1, "rag_title": "Senza IMDb", "rag_year": 2001, "status": "skipped", "reason": "no_imdb_id"}
    assert transport.paths == []


def test_only_the_first_max_candidates_are_looked_up():
    chunks = [_chunk(f"F{i}", 2000 + i, f"tt{1000000 + i}") for i in range(6)]
    routes = {f"/find/tt{1000000 + i}": _found(i + 1, f"F{i}") for i in range(6)}
    result, transport = _enrich(chunks, routes, max_candidates=3)
    assert len(result["metadata"][ENRICHMENT_KEY]["candidates"]) == 3 and len([p for p in transport.paths if p.startswith("/find")]) == 3


def test_an_unknown_imdb_id_is_not_found():
    result, _ = _enrich([_chunk("X", 2000, "tt7777777")], {"/find/tt7777777": {"movie_results": [], "tv_results": [], "person_results": []}})
    assert result["metadata"][ENRICHMENT_KEY]["candidates"][0]["status"] == "not_found" and result["metadata"][ENRICHMENT_KEY]["status"] == "none"
