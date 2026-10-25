"""RAG -> TMDb completion (tool/tmdb/enrich.py): offline, fake transport, no `.env`."""
from __future__ import annotations

import json

import pytest
from tmdb_support import make_tool

import tool.tmdb.tool as tool_module
from orchestrator import LLMOrchestrator
from tool.tmdb.enrich import ENRICHMENT_KEY, TmdbRagEnricher, select_candidates
from tool.tmdb.errors import TmdbConfigError
from stream_support import reply

MOVIES = {
    501: {"title": "Arrival", "year": 2016, "director": "Regista Uno", "cast": ["Attrice A", "Attore B"]},
    502: {"title": "Contact", "year": 1997, "director": "Regista Due", "cast": ["Attrice C"]},
    503: {"title": "Dune", "year": 1984, "director": "Regista Tre", "cast": ["Attore D"]},
    504: {"title": "Dune", "year": 2021, "director": "Regista Quattro", "cast": ["Attore E"]},
    505: {"title": "Contagion", "year": 1997, "director": "Regista Cinque", "cast": []},
    506: {"title": "Contact", "year": 1985, "director": "Regista Sei", "cast": []},
}


def _search_result(movie_id: int, popularity: int = 10) -> dict:
    movie = MOVIES[movie_id]
    return {"id": movie_id, "title": movie["title"], "original_title": movie["title"],
            "release_date": f"{movie['year']}-06-01", "popularity": popularity}


def _details(movie_id: int, *, with_credits: bool = True) -> dict:
    movie = MOVIES[movie_id]
    payload = {
        "id": movie_id, "title": movie["title"], "original_title": movie["title"], "original_language": "en",
        "release_date": f"{movie['year']}-06-01", "runtime": 100,
        "overview": f"Sinossi di prova di {movie['title']} {movie['year']}.",
        "vote_average": 7.1, "vote_count": 900,
        "translations": {"translations": []},
    }
    if with_credits:
        payload["credits"] = {
            "cast": [{"name": name, "character": "Ruolo", "order": i} for i, name in enumerate(movie["cast"])],
            "crew": [{"name": movie["director"], "job": "Director"}],
        }
    return payload


def _routes(search: dict[tuple[str, str | None], list[dict]], **details_options) -> dict:
    routes = {f"/movie/{movie_id}": _details(movie_id, **details_options) for movie_id in MOVIES}
    routes["/search/movie"] = lambda params: {"results": search.get((params["query"], params.get("year")), [])}
    return routes


def _chunk(title, year, score=0.9):
    return {"id": f"c-{title}-{year}", "testo": f"Trama di {title}.", "score": score, "title": title,
            "release_year": None if year is None else str(year)}


def _rag_result(*chunks):
    return {"query": "q", "chunks": list(chunks), "metadata": {"search_mode": "semantic"}, "trace": [{"kind": "retrieval", "title": "K", "data": {}}]}


def _enrich(chunks, search, max_candidates=3, max_calls=6, **details_options):
    tool, transport = make_tool(_routes(search, **details_options), max_calls=max_calls)
    enricher = TmdbRagEnricher(tool=tool, max_candidates=max_candidates)
    rag_result = _rag_result(*chunks)
    return enricher.enrich(tool_result=rag_result), rag_result, transport


def _rows(result):
    return result["metadata"][ENRICHMENT_KEY]["candidates"]


def test_candidates_are_the_distinct_final_chunks_in_rag_order() -> None:
    chunks = [_chunk("Arrival", 2016), _chunk("Arrival", 2016, 0.5), {"testo": "senza titolo"}, "x",
              _chunk("Contact", "1997-07-11"), _chunk("Dune", None), _chunk("Solaris", 1972)]

    selected = select_candidates(chunks, 3)

    assert [(c.rank, c.title, c.year) for c in selected] == [(1, "Arrival", 2016), (2, "Contact", 1997), (3, "Dune", None)]


def test_each_candidate_gets_only_its_own_metadata_and_ranking_is_unchanged() -> None:
    search = {("Arrival", "2016"): [_search_result(501)], ("Contact", "1997"): [_search_result(502)]}

    result, rag_result, transport = _enrich([_chunk("Arrival", 2016), _chunk("Contact", 1997)], search)

    first, second = _rows(result)
    assert (first["status"], first["tmdb"]["directors"], first["tmdb"]["top_cast"]) == ("matched", ["Regista Uno"], ["Attrice A", "Attore B"])
    assert (second["status"], second["tmdb"]["directors"]) == ("matched", ["Regista Due"])
    assert "Arrival" in first["tmdb"]["overview"] and first["tmdb"]["tmdb_vote_average"] == 7.1
    assert result["chunks"] == rag_result["chunks"] and rag_result["metadata"] == {"search_mode": "semantic"}
    assert transport.paths == ["/search/movie", "/movie/501", "/search/movie", "/movie/502"]
    assert all(call[1]["language"] == "en-US" for call in transport.calls)
    assert [step["kind"] for step in result["trace"]] == ["retrieval", "tmdb_calls"]
    assert all(url.endswith("?api_key=***") for url in result["trace"][-1]["data"]["calls"])


def test_trace_items_hold_only_the_verified_matches() -> None:
    search = {("Arrival", "2016"): [_search_result(501)], ("Contact", "1997"): [_search_result(505)]}

    result, _, _ = _enrich([_chunk("Arrival", 2016), _chunk("Contact", 1997)], search)

    assert [row["status"] for row in _rows(result)] == ["matched", "unverified"]
    items = result["trace"][-1]["data"]["items"]
    assert [(item["id"], item["media_type"]) for item in items] == [(501, "movie")]


def test_year_mismatch_is_not_attributed() -> None:
    search = {("Contact", "1997"): [], ("Contact", None): [_search_result(506)]}

    result, _, _ = _enrich([_chunk("Contact", 1997)], search)

    assert _rows(result) == [{"rank": 1, "rag_title": "Contact", "rag_year": 1997, "status": "unverified", "reason": "year_mismatch"}]


def test_title_mismatch_is_not_attributed() -> None:
    search = {("Contact", "1997"): [_search_result(505)]}

    result, _, _ = _enrich([_chunk("Contact", 1997)], search)

    assert _rows(result)[0]["status"] == "unverified" and "tmdb" not in _rows(result)[0]


def test_zero_results_is_not_found_and_nothing_is_invented() -> None:
    result, _, transport = _enrich([_chunk("Film Inesistente", 2001)], {})

    assert _rows(result) == [{"rank": 1, "rag_title": "Film Inesistente", "rag_year": 2001, "status": "not_found"}]
    assert result["metadata"][ENRICHMENT_KEY]["status"] == "none"
    assert transport.paths == ["/search/movie", "/search/movie"]  # with year, then once without (counted)


def test_ambiguous_title_is_resolved_by_the_rag_year() -> None:
    search = {("Dune", "1984"): [_search_result(504, popularity=99), _search_result(503, popularity=5)]}

    result, _, transport = _enrich([_chunk("Dune", 1984)], search)

    row = _rows(result)[0]
    assert row["status"] == "matched" and row["tmdb"]["year"] == 1984 and row["tmdb"]["directors"] == ["Regista Tre"]
    assert "/movie/504" not in transport.paths


def test_missing_metadata_stays_missing() -> None:
    search = {("Arrival", "2016"): [_search_result(501)]}

    result, _, _ = _enrich([_chunk("Arrival", 2016)], search, with_credits=False)

    tmdb = _rows(result)[0]["tmdb"]
    assert "directors" not in tmdb and "top_cast" not in tmdb and tmdb["title"] == "Arrival"


def test_budget_caps_the_lookups_and_marks_the_rest_skipped() -> None:
    search = {(MOVIES[i]["title"], str(MOVIES[i]["year"])): [_search_result(i)] for i in (501, 502, 503, 505)}
    chunks = [_chunk(MOVIES[i]["title"], MOVIES[i]["year"]) for i in (501, 502, 503, 505)]

    result, _, transport = _enrich(chunks, search, max_candidates=4, max_calls=6)

    assert [row["status"] for row in _rows(result)] == ["matched", "matched", "matched", "skipped"]
    assert _rows(result)[3]["reason"] == "call_limit_reached" and len(transport.calls) == 6


def test_no_titled_chunks_means_no_calls_and_an_unchanged_result() -> None:
    tool, transport = make_tool({})
    rag_result = _rag_result({"testo": "x", "score": 1.0})

    assert TmdbRagEnricher(tool=tool, max_candidates=3).enrich(tool_result=rag_result) is rag_result
    assert transport.calls == []


def test_missing_credentials_skip_every_candidate_without_http(monkeypatch) -> None:
    tool, transport = make_tool({})
    tool.credentials = None

    def missing():
        raise TmdbConfigError("TMDb API key missing.")

    monkeypatch.setattr(tool_module, "load_credentials", missing)
    result = TmdbRagEnricher(tool=tool, max_candidates=3).enrich(tool_result=_rag_result(_chunk("Arrival", 2016)))

    assert result["metadata"][ENRICHMENT_KEY]["error"] == "not_configured"
    assert _rows(result)[0]["status"] == "skipped" and transport.calls == []


class _RagTool:
    name, description, input_schema = "rag_search", "fake", {}

    def __init__(self, result) -> None:
        self.result = result

    def run(self, *, query, params=None, conversation_history=None):
        return self.result


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = json.dumps({"standalone_query": "q", "tool_name": "rag_search", "confidence": 0.9}) if len(self.calls) == 1 else "ok"
        return reply(text, kwargs)


def test_orchestrator_passes_the_verified_metadata_to_the_final_answer() -> None:
    search = {("Arrival", "2016"): [_search_result(501)], ("Contact", "1997"): []}
    tmdb_tool, _ = make_tool(_routes(search))
    rag_result = _rag_result(_chunk("Arrival", 2016), _chunk("Contact", 1997))
    client = _Client()
    orchestrator = LLMOrchestrator(
        config={"orchestrator": {"fallback_tool": "rag_search"}},
        tools=[_RagTool(rag_result), tmdb_tool],
        client=client,
        enrichers={"rag_search": TmdbRagEnricher(tool=tmdb_tool, max_candidates=3)},
    )

    decision = orchestrator.run(query="film sugli alieni", conversation_history=[])

    final_prompt = client.calls[-1]["input"][-1]["content"]
    assert "Regista Uno" in final_prompt and '"status": "not_found"' in final_prompt
    assert final_prompt.index("[1] Arrival 2016") < final_prompt.index("[2] Contact 1997")
    assert decision["result"]["chunks"] == rag_result["chunks"]


@pytest.mark.parametrize("tool_name", ["tmdb_search", "movie_db_search"])
def test_enrichment_runs_only_after_rag(tool_name) -> None:
    calls = []

    class _Recorder:
        def enrich(self, *, tool_result):
            calls.append(tool_result)
            return tool_result

    class _Other(_RagTool):
        name = tool_name

    class _PlanClient(_Client):
        def create(self, **kwargs):
            self.calls.append(kwargs)
            text = json.dumps({"standalone_query": "q", "tool_name": tool_name, "confidence": 0.9}) if len(self.calls) == 1 else "ok"
            return reply(text, kwargs)

    orchestrator = LLMOrchestrator(
        config={"orchestrator": {"fallback_tool": "rag_search"}},
        tools=[_RagTool(_rag_result()), _Other(_rag_result())],
        client=_PlanClient(),
        enrichers={"rag_search": _Recorder()},
    )

    orchestrator.run(query="q", conversation_history=[])

    assert calls == []
