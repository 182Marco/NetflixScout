"""The film index retriever with an in-memory index: exclusions, penalty, filters, reorder, adapter contract. No network."""
from __future__ import annotations

import numpy as np
import pytest

from tool.rag.film.retrieval import adapter
from tool.rag.film.retrieval.index import Film, norm
from tool.rag.film.retrieval.models import Signals, TitleRef
from tool.rag.film.retrieval.search import Settings, search


def v(angle):
    return np.array([np.cos(angle), np.sin(angle)], dtype=np.float32)


def film(pid, title, angle, **kw):
    return Film(pid, kw.get("film_id", pid), title, kw.get("original"), kw.get("year", 2000), kw.get("genres", []), kw.get("plot", "plot"),
                franchise_ids=kw.get("fr", []), imdb_id=kw.get("imdb"), vector=v(angle), unverified=kw.get("unverified", False))


class FakeIndex:
    collection = "fake"

    def __init__(self, films, share=0.0):
        self.films, self.share, self.last_filter = films, share, "unset"

    def count(self):
        return len(self.films)

    def search(self, vector, *, limit, flt=None, with_vectors=True):
        self.last_filter = flt
        return sorted(self.films, key=lambda f: -float(f.vector @ vector))[:limit]

    def resolve(self, title_it, title_original, year):
        for f in self.films:
            if norm(f.title) in (norm(title_it), norm(title_original)) or norm(f.original_title) in (norm(title_it), norm(title_original)):
                return f
        return None

    def positive_filter(self, sg):
        return "FILTER" if (sg.year_from or sg.actors) else None

    def genre_share(self, term):
        return self.share


EMBED_ANGLES = {"horror": 0.0, "possessione": 0.45}


def embed(texts):
    return np.vstack([v(next((a for k, a in EMBED_ANGLES.items() if t.startswith(k)), 0.1)) for t in texts])


def sig(**kw):
    return Signals(positive_it=kw.pop("positive_it", "horror psicologico"), positive_en="x", **kw)


def titles(out):
    return [f.title for f in out.films]


def test_cited_films_and_franchises_are_removed_and_crossovers_go_by_id():
    idx = FakeIndex([film("a", "Alien", 0.0, fr=["Q1"]), film("b", "Prometheus", 0.02, fr=["Q1"]), film("c", "Predator", 0.04, fr=["Q2"]),
                     film("d", "Se7en", 0.3)])
    s = sig(like_titles=[TitleRef(title_it="Alien", title_original="Alien", summary_it="x", summary_en="x")], avoid_franchise_names=["Alien"])
    out = search(idx, embed, s, "q", k=5, settings=Settings())
    assert titles(out) == ["Predator", "Se7en"]


def test_penalty_demotes_what_resembles_the_trait_to_avoid():
    idx = FakeIndex([film("a", "Possessed", 0.4), film("b", "Quiet", 0.3), film("c", "Ghost", 0.5)])
    out = search(idx, embed, sig(avoid_descriptions_it=["possessione demoniaca"]), "q", k=3, settings=Settings())
    assert titles(out)[0] == "Quiet" and titles(out).index("Possessed") > titles(out).index("Quiet")


def test_an_avoided_genre_that_is_too_wide_or_also_wanted_is_dropped():
    films = [film("a", "A", 0.0, genres=["film horror"]), film("b", "B", 0.1, genres=["film horror splatter"])]
    out = search(FakeIndex(films), embed, sig(avoid_genres_it=["splatter"], keep_genres_it=["horror"]), "q", k=5, settings=Settings())
    assert titles(out) == ["A"]
    wide = search(FakeIndex(films, share=0.5), embed, sig(avoid_genres_it=["splatter"]), "q", k=5, settings=Settings())
    assert len(wide.films) == 2 and wide.context.dropped_genre_terms[0]["reason"] == "too_wide"
    same = search(FakeIndex(films), embed, sig(avoid_genres_it=["horror"], keep_genres_it=["horror psicologico"]), "q", k=5, settings=Settings())
    assert same.context.dropped_genre_terms[0]["reason"] == "also_wanted" and len(same.films) == 2


def test_positive_filters_are_given_to_the_index():
    idx = FakeIndex([film("a", "A", 0.0)])
    search(idx, embed, sig(actors=["Tom Hanks"]), "q", k=1, settings=Settings())
    assert idx.last_filter == "FILTER"


def test_the_reorder_decides_the_order_and_a_failure_keeps_the_penalty_order():
    idx = FakeIndex([film("a", "A", 0.0), film("b", "B", 0.1), film("c", "C", 0.2)])
    out = search(idx, embed, sig(), "q", k=2, settings=Settings(), reorder=lambda *a: [2, 1])
    assert titles(out) == ["C", "B"] and out.engine == "llm_request"

    def boom(*a):
        raise RuntimeError("down")
    failed = search(idx, embed, sig(), "q", k=2, settings=Settings(), reorder=boom)
    assert titles(failed) == ["A", "B"] and failed.engine == "penalty_after_error"


def test_an_unknown_title_is_described_not_looked_up():
    idx = FakeIndex([film("a", "A", 0.0)])
    s = sig(like_titles=[TitleRef(title_it="Sconosciuto", title_original="Unknown", summary_it="horror lento", summary_en="x")])
    out = search(idx, embed, s, "q", k=1, settings=Settings())
    assert out.context.references[0]["status"] == "described" and out.context.references[0]["source"] == "description"


def test_the_adapter_builds_the_rag_contract(monkeypatch):
    idx = FakeIndex([film("a", "Hereditary", 0.0, imdb="tt7784604", year=2018, genres=["film horror"])])
    monkeypatch.setattr(adapter, "index_for", lambda config: idx)
    monkeypatch.setattr(adapter, "make_parse", lambda *a, **k: (lambda q: sig(avoid_descriptions_it=["possessione"])))
    monkeypatch.setattr(adapter, "make_embed", lambda *a, **k: embed)
    cfg = {"retrieval": {"k_finale": 3}, "embedding": {"model": "m", "dimensions": 8}, "film_index": {"rerank": {"enabled": False}}, "vectorstore": {"collection": "x"}}
    r = adapter.run_film_index(config=cfg, query="q")
    assert r.chunks[0].imdb_id == "tt7784604" and r.chunks[0].release_year == "2018" and r.rerank_engine == "penalty"
    assert r.films[0]["title"] == "Hereditary" and "imdb_id" not in r.films[0] and r.signals.semantic_query == "horror psicologico"


def test_a_parser_failure_still_searches_and_says_so(monkeypatch):
    idx = FakeIndex([film("a", "A", 0.0)])
    monkeypatch.setattr(adapter, "index_for", lambda config: idx)

    def broken(*a, **k):
        def parse(q):
            raise RuntimeError("down")
        return parse
    monkeypatch.setattr(adapter, "make_parse", broken)
    monkeypatch.setattr(adapter, "make_embed", lambda *a, **k: embed)
    cfg = {"retrieval": {"k_finale": 1}, "embedding": {"model": "m"}, "film_index": {"rerank": {"enabled": False}}, "vectorstore": {"collection": "x"}}
    r = adapter.run_film_index(config=cfg, query="horror")
    assert [c.title for c in r.chunks] == ["A"] and r.notes["parser_failed"] == "RuntimeError"


def test_an_empty_collection_is_an_explicit_error(monkeypatch):
    monkeypatch.setattr(adapter, "index_for", lambda config: FakeIndex([]))
    with pytest.raises(RuntimeError, match="empty or missing"):
        adapter.run_film_index(config={"retrieval": {"k_finale": 1}, "embedding": {"model": "m"}}, query="q")
