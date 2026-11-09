"""FASE 19K: the film trace reports the filters the parser produced (diagnostic only). It must not change retrieval, results or what the presenters show."""
from __future__ import annotations

import json

from test_film_index import FakeIndex, embed, film, sig
from tool.rag.film.results import QuerySignals
from tool.rag.film.retrieval import adapter
from tool.rag.film.retrieval.models import Signals
from tool.rag.film.tool import RagTool
from turn import TraceStep
from presenters.terminal.renderer import STEP_RENDERERS
from presenters.web.payload import STEP_SERIALIZERS
from movie_db.harness.evaluation import run_rag_semantic_smoke as H

FILTERED = dict(year_from=1960, year_to=1969, countries=["Italia"], directors=["Federico Fellini"], actors=["Marcello Mastroianni"], rare_terms=["mafia"])
CFG = {"retrieval": {"k_finale": 3}, "embedding": {"model": "m", "dimensions": 8}, "film_index": {"rerank": {"enabled": False}}, "vectorstore": {"collection": "x"}}


def test_the_trace_reports_only_the_non_empty_filters_the_parser_produced() -> None:
    assert adapter.query_signals(sig(**FILTERED)).filters == FILTERED
    assert adapter.query_signals(sig(year_from=1990)).filters == {"year_from": 1990}
    assert adapter.query_signals(sig()).filters == {}                                # nothing filtered: an empty report, not invented keys
    assert adapter.query_signals(sig(year_to=0, countries=[])).filters == {"year_to": 0}   # a real zero is kept, an empty list is not


def _run(monkeypatch, make_signals, *, old_query_signals=None):
    idx = FakeIndex([film("a", "Alfa", 0.0, imdb="tt1", year=1962), film("b", "Beta", 0.2, imdb="tt2", year=1965), film("c", "Gamma", 0.5, imdb="tt3", year=1970)])
    monkeypatch.setattr(adapter, "index_for", lambda config: idx)
    monkeypatch.setattr(adapter, "make_parse", lambda *a, **k: (lambda q: make_signals()))
    monkeypatch.setattr(adapter, "make_embed", lambda *a, **k: embed)
    if old_query_signals:
        monkeypatch.setattr(adapter, "query_signals", old_query_signals)
    return adapter.run_film_index(config=CFG, query="q")


def test_retrieval_is_identical_with_and_without_the_diagnostic_field(monkeypatch) -> None:
    def old_query_signals(s):            # the function as it was before FASE 19K
        return QuerySignals(positive_signals=[s.positive_it], negative_signals=list(s.avoid_descriptions_it), hard_exclusions=list(s.avoid_franchise_names),
                            semantic_query=s.positive_it, avoid_query="; ".join(s.avoid_descriptions_it), genres=list(s.keep_genres_it), excluded_genres=list(s.avoid_genres_it))
    new = _run(monkeypatch, lambda: sig(**FILTERED))
    old = _run(monkeypatch, lambda: sig(**FILTERED), old_query_signals=old_query_signals)
    for field in ("chunks", "candidates", "reranked", "films", "notes", "rerank_engine", "embedded_text", "rerank_query", "references"):
        assert getattr(new, field) == getattr(old, field), field
    assert new.signals.model_dump(exclude={"filters"}) == old.signals.model_dump(exclude={"filters"})
    assert new.signals.filters == FILTERED and old.signals.filters == {}


def test_the_filters_reach_the_trace_of_the_tool_and_not_the_prompt_metadata(monkeypatch) -> None:
    _run(monkeypatch, lambda: sig(**FILTERED))
    result = RagTool(config=CFG).run(query="q", params={"query": "q"})
    trace_signals = result["trace"][0]["data"]["signals"]
    assert trace_signals["filters"] == FILTERED
    assert "mafia" not in json.dumps(result["metadata"]) and "filters" not in json.dumps(result["metadata"])


def _step(filters):
    signals = {"genres": ["Sci-Fi"], **({"filters": filters} if filters is not None else {})}
    return TraceStep(kind="retrieval", title="x", data={"embedded_text": "robots", "signals": signals, "chunks": [{"id": "c1", "testo": "t", "score": 0.9, "title": "Matrix", "release_year": "1999"}]})


def test_terminal_and_web_show_exactly_the_same_with_or_without_the_filters(capsys) -> None:
    for language in ("it", "en"):
        outputs = []
        for filters in (None, {}, FILTERED):
            STEP_RENDERERS["retrieval"](_step(filters), language)
            outputs.append((capsys.readouterr().out, json.dumps(STEP_SERIALIZERS["retrieval"](_step(filters), language), sort_keys=True, default=str)))
        assert "Matrix" in outputs[0][0] and outputs[0][1]                          # the comparison is not vacuous
        assert outputs[0] == outputs[1] == outputs[2]
        assert "mafia" not in outputs[2][0] + outputs[2][1]                         # the frontends are untouched: nothing new is shown


def test_the_review_sheet_of_a_film_run_lists_the_parser_filters(tmp_path) -> None:
    row = {"id": "F03", "category": "year_filter", "query": "q", "grade": {"valid": True, "hit_rank": 1}, "engine": "llm_request", "embedded_text": "x",
           "signals": {"semantic_query": "commedie", "filters": FILTERED}, "items": [{"title": "T", "year": 1962, "level": "film", "imdb_id": "tt1"}]}
    H._write_review_sheet(tmp_path, [row])
    text = (tmp_path / "review.md").read_text()
    assert "'year_from': 1960" in text and "'directors': ['Federico Fellini']" in text and "'rare_terms': ['mafia']" in text
