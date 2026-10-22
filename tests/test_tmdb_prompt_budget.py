"""The TMDb context passed to the LLM stays bounded, keeps essentials and reports omissions."""
from __future__ import annotations

import json

from tmdb_support import make_tool, movie_payload, run, tmdb_meta

from orchestrator import LLMOrchestrator
from tmdb.models.results import Entity, RequestOutcome
from tmdb.prompt_budget import (
    ESSENTIALS_CHARS,
    MAX_CHUNKS,
    MAX_TMDB_CONTEXT_CHARS,
    fit_essentials,
    json_size,
    pack_context,
)

LONG = "Una frase molto lunga sul film. " * 40
MOVIE_FACETS = [
    "credits", "images", "videos", "keywords", "reviews", "recommendations", "similar",
    "release_dates", "watch_providers", "alternative_titles", "translations", "external_ids",
]  # fmt: skip


def _huge_movie(movie_id: int) -> dict:
    many = lambda n, make: [make(i) for i in range(n)]  # noqa: E731
    return movie_payload(
        id=movie_id,
        title=f"Film {movie_id} " + "titolo lunghissimo " * 10,
        overview=LONG,
        tagline=LONG,
        credits={
            "cast": many(100, lambda i: {"name": f"Attore {i} " * 3, "character": f"Ruolo {i} " * 3, "order": i}),
            "crew": many(60, lambda i: {"name": f"Regista {i}", "job": "Director"}),
        },
        images={"posters": many(60, lambda i: {"file_path": f"/p{i}.jpg"}), "backdrops": many(60, lambda i: {"file_path": f"/b{i}.jpg"})},
        videos={"results": many(40, lambda i: {"site": "YouTube", "key": f"k{i}", "type": "Trailer", "name": LONG[:80]})},
        keywords={"keywords": many(80, lambda i: {"name": f"keyword {i}"})},
        reviews={"results": many(50, lambda i: {"author": f"A{i}", "content": LONG})},
        recommendations={"results": many(20, lambda i: {"id": 1000 + i, "title": f"Rec {i}"})},
        similar={"results": many(20, lambda i: {"id": 2000 + i, "title": f"Sim {i}"})},
        release_dates={"results": [{"iso_3166_1": "IT", "release_dates": many(30, lambda i: {"release_date": "2014-11-06", "type": 3})}]},
        alternative_titles={"titles": many(40, lambda i: {"iso_3166_1": "IT", "title": f"Titolo alternativo {i}"})},
        translations={"translations": many(40, lambda i: {"iso_639_1": "en", "iso_3166_1": "US", "data": {"title": "T", "overview": LONG}})},
        external_ids={"imdb_id": "tt0816692", "wikidata_id": "Q13417189"},
        **{"watch/providers": {"results": {"IT": {"flatrate": many(30, lambda i: {"provider_name": f"Provider {i}"})}}}},
    )


def _context_size(result: dict) -> int:
    """What `_build_final_context` actually prints for this result."""
    orchestrator = LLMOrchestrator(config={"orchestrator": {}}, tools=[], client=object())
    message = orchestrator._build_final_context(query="", tool_result={"tool_name": "tmdb_search", **result})[-1]["content"]
    return len(message)


def test_four_requests_with_every_facet_stay_within_the_budget() -> None:
    routes = {f"/movie/{i}": _huge_movie(i) for i in range(1, 5)}
    tool, transport = make_tool(routes, max_results=20)

    result = run(tool, *({"operation": "movie_details", "tmdb_id": i, "facets": MOVIE_FACETS} for i in range(1, 5)))

    meta = tmdb_meta(result)
    packed = json_size(meta) + sum(len(c["testo"]) + len(c["title"]) + len(c["genres"] or "") + 40 for c in result["chunks"])
    assert packed <= MAX_TMDB_CONTEXT_CHARS
    assert _context_size(result) <= MAX_TMDB_CONTEXT_CHARS + 300
    assert len(transport.calls) == 4
    # P0 and P1 of every requested entity are present.
    for index, request in enumerate(meta["requests"], start=1):
        essentials = request["entities"][f"movie:{index}"]["essentials"]
        assert essentials["directors"] and essentials["watch_providers"]["available"]
        assert json_size(essentials) <= ESSENTIALS_CHARS
    assert [chunk["tmdb_id"] for chunk in result["chunks"]] == [1, 2, 3, 4]
    assert all(f"TMDb movie/{i}" in result["chunks"][i - 1]["testo"] for i in range(1, 5))
    # Omissions are explicit.
    assert meta["context_truncated"] is True
    assert any(note.startswith("r1 movie:1 cast: ") and note.endswith("/100") for note in meta["omitted"])
    assert result["trace"][0]["data"]["attributions"] == ["justwatch"]


def test_packing_is_deterministic() -> None:
    routes = {f"/movie/{i}": _huge_movie(i) for i in range(1, 3)}
    requests = [{"operation": "movie_details", "tmdb_id": i, "facets": MOVIE_FACETS} for i in (1, 2)]

    first = run(make_tool(routes)[0], *requests)
    second = run(make_tool(routes)[0], *requests)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_small_results_are_not_cut() -> None:
    tool, _ = make_tool({"/movie/1": movie_payload(id=1)})

    result = run(tool, {"operation": "movie_details", "tmdb_id": 1, "facets": ["credits"]})

    meta = tmdb_meta(result)
    assert meta["context_truncated"] is False
    assert meta["omitted"] == ["r1 movie:1 cast: 15/30"]  # only the fixed list cap


def test_lists_beyond_the_chunk_limit_become_compact_rows() -> None:
    items = [Entity(kind="movie", tmdb_id=i, title=f"Film {i}", year=2000 + i) for i in range(20)]
    outcomes = [RequestOutcome(index=1, operation="trending", items=items[:12]), RequestOutcome(index=2, operation="chart", items=items[12:])]

    packed = pack_context(outcomes, api_language="it-IT", status="ok")

    assert len(packed.chunks) == MAX_CHUNKS
    assert len(packed.metadata["more_results"]) == 10
    assert packed.metadata["more_results"][0].startswith("r1 Film Film 10 (2010)")


def test_essentials_are_fitted_without_losing_identity_fields() -> None:
    essentials = {
        "overview": LONG,
        "tagline": LONG[:150],
        "directors": [f"Regista {i}" for i in range(20)],
        "top_cast": [f"Attore {i}" for i in range(5)],
        "watch_providers": {"region": "IT", "flatrate": [f"Provider {i}" for i in range(10)], "available": True},
        "tmdb_url": "https://www.themoviedb.org/movie/1",
    }

    fitted = fit_essentials(essentials)

    assert json_size(fitted) <= ESSENTIALS_CHARS
    assert fitted["overview"].endswith("…") and fitted["watch_providers"]["available"] is True
    assert "tagline" not in fitted
