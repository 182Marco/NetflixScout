"""Reference films with real vectors: from the index, or from their TMDb plot kept in Qdrant (offline, in-memory Qdrant).

TMDb is a fake reader that counts its calls; the embedding is a fake that counts its calls too. What is checked:
where each vector comes from, that nothing is called twice, that no duplicate point appears, and that the stored vectors
are the ones the Qdrant search actually receives."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from tool.rag.FromQueryEmbeddingToRes import pipeline, retrieval, vectorstore
from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals, ReferenceTitle
from tool.rag.FromQueryEmbeddingToRes.reference_flow import ReferenceFlow, references_summary
from tool.rag.FromQueryEmbeddingToRes.references import ReferenceInput
from tool.rag.FromQueryEmbeddingToRes.store import StorePoint, point_uuid
from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
from tool.rag.FromQueryEmbeddingToRes.store.catalog import CatalogStore
from tool.rag.FromQueryEmbeddingToRes.store.collection import QdrantCollection
from tool.rag.FromQueryEmbeddingToRes.store.qdrant_store import QdrantStore, open_client

DIM = 6
PLOT = "A crew crosses a wormhole to find a new home for humanity while time slows down around them. " * 2


def vec(*head):
    v = np.zeros(DIM, dtype=np.float32)
    v[: len(head)] = head
    return v.tolist()


def unit(v):
    v = np.asarray(v, dtype=np.float64)
    return (v / np.linalg.norm(v)).tolist()


def corpus_point(i, v, title, year, movie_id, cast=""):
    meta = {"title": title, "movie_id": movie_id, "genres": "Drama", "source": "plots"}
    if year is not None:
        meta["release_year"] = str(year)
    if cast:
        meta["cast"] = cast
    return StorePoint(id=f"p{i}", vector=v, document=f"plot {title}", metadata=meta)


class Embed:
    """Counting fake: the vector depends on the text, so what is stored can be told apart from what is not."""

    def __init__(self):
        self.texts = []

    def __call__(self, text):
        self.texts.append(text)
        return vec(0, 0, 0, 0, 1, 0) if "wormhole" in text else vec(0, 0, 0, 0, 0, 1)


class Tmdb:
    """Fake of `read_film`: a script of answers by (title, year) or by tmdb_id; every call is recorded."""

    def __init__(self, films=None, errors=None):
        self.films, self.errors, self.calls = films or {}, errors or {}, []

    def __call__(self, *, title=None, year=None, tmdb_id=None, turn_id=None):
        self.calls.append({"title": title, "year": year, "tmdb_id": tmdb_id, "turn_id": turn_id})
        key = tmdb_id if tmdb_id is not None else (title, year)
        if key in self.errors:
            return SimpleNamespace(record=None, reason=self.errors[key], calls=1, tmdb_id=None)
        record = self.films.get(key)
        if record is None:
            return SimpleNamespace(record=None, reason="not_found", calls=1, tmdb_id=None)
        return SimpleNamespace(record=dict(record), reason="", calls=2 if tmdb_id is None else 1, tmdb_id=record["tmdb_id"])


def film(tmdb_id, title, year, overview=PLOT, ts=2_000_000_000_000, **kw):
    return dict(tmdb_id=tmdb_id, title=title, overview=overview, year=year, fetched_ts=ts, genres=("Science Fiction",),
                cast=("Ann Lee", "Bob Ray", "Cy Dunn"), **kw)


@pytest.fixture
def env():
    client = open_client("memory")
    store = QdrantStore(client, "c", IndexMeta("m", DIM))
    store.create()
    store.upsert([
        corpus_point(0, vec(1, 0, 0, 0), "The Dark Knight", 2008, "m-dk"),
        corpus_point(1, vec(0.9, 0.3, 0, 0), "Batman Returns", 1992, "m-br"),
        corpus_point(2, vec(0, 1, 0, 0), "Whiplash", 1948, "m-w48"),
        corpus_point(3, vec(0, 0, 1, 0), "Alien", 1979, "m-a79"),
        corpus_point(4, vec(0, 0, 0.9, 0.2), "Alien", 1999, "m-a99"),
        corpus_point(5, vec(0.2, 0.2, 0.2, 0.9), "Heist", 1995, "m-h"),
    ])
    catalog = CatalogStore(client, "c", "m", DIM)
    catalog.ensure_indexes()
    return SimpleNamespace(client=client, store=store, catalog=catalog, embed=Embed(), invalidated=[])


def make_flow(env, tmdb, **kw):
    return ReferenceFlow(store=env.store, catalog=env.catalog, read_film=tmdb, embed_text=env.embed,
                         invalidate=lambda: env.invalidated.append(1), **kw)


def tmdb_point(env, tmdb_id):
    got = env.client.retrieve("c", ids=[point_uuid(f"tmdb:movie:{tmdb_id}")], with_payload=True, with_vectors=True)
    return got[0] if got else None


# ---- 1. a movie already in the index
def test_a_movie_in_the_index_reuses_its_stored_vector_with_no_external_call(env):
    tmdb = Tmdb()
    refs = make_flow(env, tmdb).resolve([ReferenceInput("The Dark Knight", 2008)], [])
    (entry,) = refs.entries
    assert entry.status == "resolved" and entry.source == "index" and entry.legacy_id == "p0"
    assert np.allclose(entry.vector, unit(vec(1, 0, 0, 0)))
    assert tmdb.calls == [] and env.embed.texts == [] and env.client.count("c").count == 6
    assert entry.detail == {"origin": "corpus", "tmdb_calls": 0, "embedding_created": False}


# ---- 2. an absent movie: TMDb plot -> one embedding -> a persistent point
def test_an_absent_movie_is_read_from_tmdb_embedded_once_and_persisted(env):
    tmdb = Tmdb({("Interstellar", 2014): film(157336, "Interstellar", 2014)})
    refs = make_flow(env, tmdb).resolve([ReferenceInput("Interstellar", 2014)], [], turn_id="t1")
    (entry,) = refs.entries
    assert tmdb.calls == [{"title": "Interstellar", "year": 2014, "tmdb_id": None, "turn_id": "t1"}]
    assert env.embed.texts == [PLOT.strip()]  # the embedding is of the PLOT, not of the question
    point = tmdb_point(env, 157336)
    assert point.payload["source"] == "tmdb" and point.payload["legacy_id"] == "tmdb:movie:157336"
    assert point.payload["title"] == "Interstellar" and point.payload["release_year_int"] == 2014
    assert point.payload["tmdb_id"] == 157336 and point.payload["document"] == PLOT.strip() and point.payload["version"] == 1
    assert np.allclose(point.vector, unit(vec(0, 0, 0, 0, 1, 0)))
    assert entry.status == "resolved" and entry.source == "tmdb_inserted" and entry.movie_id == "tmdb:movie:157336"
    assert np.allclose(entry.vector, point.vector) and entry.detail["embedding_created"] is True and entry.detail["tmdb_calls"] == 2
    assert env.client.count("c").count == 7 and env.invalidated == [1]


# ---- 7. repeated requests: reuse, no duplicates
def test_a_repeated_request_costs_nothing_and_adds_no_duplicate(env):
    tmdb = Tmdb({("Interstellar", 2014): film(157336, "Interstellar", 2014)})
    flow = make_flow(env, tmdb)
    first = flow.resolve([ReferenceInput("Interstellar", 2014)], []).entries[0]
    before = tmdb_point(env, 157336)
    second = flow.resolve([ReferenceInput("Interstellar", 2014)], []).entries[0]
    third = flow.resolve([ReferenceInput("interstellar", None)], []).entries[0]  # no year: unique title in the index
    assert len(tmdb.calls) == 1 and len(env.embed.texts) == 1 and env.client.count("c").count == 7
    assert second.status == third.status == "resolved" and second.detail["origin"] == "catalog"
    assert np.allclose(second.vector, first.vector) and tmdb_point(env, 157336).payload["version"] == before.payload["version"]


# ---- 3 / 4. positive only and positive + negative reach the Qdrant search
def search_with(env, refs, monkeypatch):
    seen = {}
    col = QdrantCollection(env.store)
    real = col.recommend

    def spy(positive, negative, n_results, **kw):
        seen.update(positive=[list(map(float, v)) for v in positive], negative=[list(map(float, v)) for v in negative], kw=kw)
        return real(positive, negative, n_results, **kw)

    monkeypatch.setattr(col, "recommend", spy)
    monkeypatch.setattr(vectorstore, "embed", lambda texts, backend=None, model=None: np.array([vec(0, 0, 1, 0)], dtype=np.float32))
    rows = vectorstore.search(col, "q", 5, "openai", "m", semantic_query="a quiet drama", references=refs)
    return seen, rows


def test_the_vectors_of_the_references_are_the_examples_of_the_qdrant_search(env, monkeypatch):
    tmdb = Tmdb({("Interstellar", 2014): film(157336, "Interstellar", 2014), ("Deadpool", 2016): film(293660, "Deadpool", 2016, overview="A wisecracking mercenary " * 8)})
    refs = make_flow(env, tmdb).resolve([ReferenceInput("Interstellar", 2014)], [ReferenceInput("The Dark Knight", 2008)])
    seen, rows = search_with(env, refs, monkeypatch)
    stored_x = tmdb_point(env, 157336).vector
    stored_y = env.client.retrieve("c", ids=[point_uuid("p0")], with_vectors=True)[0].vector
    assert len(seen["positive"]) == 2 and np.allclose(seen["positive"][0], unit(vec(0, 0, 1, 0)))  # the query vector first
    assert np.allclose(seen["positive"][1], stored_x)  # then the PERSISTED vector of the plot of X
    assert len(seen["negative"]) == 1 and np.allclose(seen["negative"][0], stored_y)  # Y: its index vector
    assert set(seen["kw"]["exclude_movie_ids"]) == {"tmdb:movie:157336", "m-dk"}
    titles = {r["title"] for r in rows}
    assert "The Dark Knight" not in titles and "Interstellar" not in titles  # the references never come back


def test_positive_only_request(env, monkeypatch):
    refs = make_flow(env, Tmdb()).resolve([ReferenceInput("The Dark Knight", 2008)], [])
    seen, _ = search_with(env, refs, monkeypatch)
    assert len(seen["positive"]) == 2 and seen["negative"] == []


# ---- 5. homonyms
def test_the_year_tells_a_homonym_from_the_indexed_film_and_keeps_both_out_of_the_results(env):
    tmdb = Tmdb({("Whiplash", 2014): film(244786, "Whiplash", 2014)})
    (entry,) = make_flow(env, tmdb).resolve([ReferenceInput("Whiplash", 2014)], []).entries
    assert entry.source == "tmdb_inserted" and entry.legacy_id == "tmdb:movie:244786"  # not the 1948 film
    assert "m-w48" in entry.homonym_movie_ids  # the same-title film of the index is excluded too (decision of Phase 5)
    assert tmdb.calls and tmdb.calls[0]["year"] == 2014


def test_two_homonyms_without_a_year_give_no_vector_and_say_why(env):
    tmdb = Tmdb(errors={("Alien", None): "unverified_match:ambiguous"})
    (entry,) = make_flow(env, tmdb).resolve([ReferenceInput("Alien", None)], []).entries
    assert entry.status == "ambiguous" and entry.vector is None and entry.detail["reason"] == "unverified_match:ambiguous"
    assert env.embed.texts == [] and env.client.count("c").count == 6


def test_the_year_picks_the_right_homonym_in_the_index(env):
    (entry,) = make_flow(env, Tmdb()).resolve([ReferenceInput("Alien", 1979)], []).entries
    assert entry.status == "resolved" and entry.legacy_id == "p3"


# ---- 6. no usable plot
@pytest.mark.parametrize("overview,reason", [(None, "no_english_overview"), ("too short", "overview_too_short")])
def test_a_movie_without_a_reliable_plot_gets_no_embedding_and_no_point(env, overview, reason):
    tmdb = Tmdb({("Obscure", 2020): film(999, "Obscure", 2020, overview=overview)})
    (entry,) = make_flow(env, tmdb).resolve([ReferenceInput("Obscure", 2020)], []).entries
    assert entry.status == "no_plot" and entry.vector is None and entry.detail["reason"] == reason
    assert env.embed.texts == [] and tmdb_point(env, 999) is None and env.client.count("c").count == 6
    assert ("obscure", 2020) in entry_titles(make_flow(env, tmdb).resolve([ReferenceInput("Obscure", 2020)], []))  # still kept out of results


def entry_titles(refs):
    return refs.excluded_titles()


# ---- 8. errors of the external source and the limits
@pytest.mark.parametrize("reason,status", [("not_found", "unavailable"), ("rate_limited", "unavailable"),
                                           ("call_limit_reached", "unavailable"), ("network_error", "unavailable"),
                                           ("unverified_match:title_mismatch", "unavailable"), ("adult", "unavailable")])
def test_source_errors_leave_the_reference_without_a_vector_but_never_break_the_flow(env, reason, status):
    tmdb = Tmdb(errors={("X", 2000): reason})
    (entry,) = make_flow(env, tmdb).resolve([ReferenceInput("X", 2000)], []).entries
    assert entry.status == status and entry.vector is None and entry.detail["reason"] == reason and env.embed.texts == []


def test_an_embedding_failure_is_an_unavailable_reference_not_an_exception(env):
    def boom(text):
        raise TimeoutError("openai down")

    flow = ReferenceFlow(store=env.store, catalog=env.catalog, read_film=Tmdb({("I", 2014): film(1, "I", 2014)}), embed_text=boom)
    (entry,) = flow.resolve([ReferenceInput("I", 2014)], []).entries
    assert entry.status == "unavailable" and entry.detail["reason"] == "sync_error:TimeoutError" and tmdb_point(env, 1) is None


def test_external_lookups_per_turn_are_limited(env):
    tmdb = Tmdb({("A", 2001): film(1, "A", 2001), ("B", 2002): film(2, "B", 2002), ("C", 2003): film(3, "C", 2003)})
    refs = make_flow(env, tmdb, max_lookups=2, max_positive=3).resolve(
        [ReferenceInput("A", 2001), ReferenceInput("B", 2002), ReferenceInput("C", 2003)], [])
    assert [e.status for e in refs.entries] == ["resolved", "resolved", "not_in_index"]
    assert refs.entries[2].detail["reason"] == "lookup_limit" and len(tmdb.calls) == 2


def test_references_over_the_per_role_limit_and_duplicates_are_set_aside(env):
    flow = make_flow(env, Tmdb(), max_positive=1, max_negative=1)
    refs = flow.resolve([ReferenceInput("The Dark Knight", 2008), ReferenceInput("Batman Returns", 1992)],
                        [ReferenceInput("The Dark Knight", 2008), ReferenceInput("Heist", 1995)])
    assert [e.status for e in refs.entries] == ["resolved", "ignored_over_limit", "duplicate", "resolved"]
    assert [e.role for e in refs.usable] == ["positive", "negative"]


def test_with_persistence_off_nothing_is_read_or_written(env):
    tmdb = Tmdb({("Interstellar", 2014): film(157336, "Interstellar", 2014)})
    (entry,) = make_flow(env, tmdb, persist=False).resolve([ReferenceInput("Interstellar", 2014)], []).entries
    assert entry.status == "not_in_index" and tmdb.calls == [] and env.embed.texts == [] and env.client.count("c").count == 6


# ---- the same work already in the corpus is linked, never duplicated
def test_a_movie_the_corpus_already_has_under_another_year_is_linked_not_duplicated(env):
    env.store.upsert([corpus_point(9, vec(0, 0, 0, 1), "Solaris", 2002, "m-sol", cast="Ann Lee; Bob Ray; Cy Dunn")])
    tmdb = Tmdb({("Solaris", 2003): film(593, "Solaris", 2003)})
    before = env.client.count("c").count
    (entry,) = make_flow(env, tmdb).resolve([ReferenceInput("Solaris", 2003)], []).entries
    # the index lookup finds the corpus film within +-1 year: no external call at all
    assert entry.status == "resolved" and entry.legacy_id == "p9" and tmdb.calls == [] and env.client.count("c").count == before


# ---- refresh of an old plot
def test_an_old_tmdb_plot_is_refreshed_and_a_failed_refresh_keeps_the_stored_vector(env):
    tmdb = Tmdb({("Interstellar", 2014): film(157336, "Interstellar", 2014, ts=1_000)})
    flow = make_flow(env, tmdb, refresh_days=30, clock=lambda: 2_000_000_000)  # 2e9 s: the stored plot is years old
    flow.resolve([ReferenceInput("Interstellar", 2014)], [])  # inserted (fetched_ts is ancient)
    tmdb.films[157336] = film(157336, "Interstellar", 2014, overview="A lone astronaut drifts home after a rescue gone wrong. " * 3, ts=1_900_000_000_000)
    entry = flow.resolve([ReferenceInput("Interstellar", 2014)], []).entries[0]
    assert entry.detail["refresh"] == "updated" and entry.detail["embedding_created"] is True
    assert tmdb_point(env, 157336).payload["version"] == 2 and np.allclose(entry.vector, tmdb_point(env, 157336).vector)
    tmdb.errors[157336] = "rate_limited"
    flow.clock = lambda: 4_000_000_000
    kept = flow.resolve([ReferenceInput("Interstellar", 2014)], []).entries[0]
    assert kept.status == "resolved" and kept.detail["refresh"] == "failed:rate_limited" and np.allclose(kept.vector, entry.vector)


def test_a_fresh_plot_is_not_read_again(env):
    tmdb = Tmdb({("Interstellar", 2014): film(157336, "Interstellar", 2014)})
    flow = make_flow(env, tmdb, refresh_days=30, clock=lambda: 2_000_000_000)  # the plot's fetched_ts is 2e12 ms = now
    flow.resolve([ReferenceInput("Interstellar", 2014)], [])
    flow.resolve([ReferenceInput("Interstellar", 2014)], [])
    assert len(tmdb.calls) == 1


# ---- the summary the final prompt gets
def test_the_summary_says_what_was_used_and_what_was_not(env):
    tmdb = Tmdb({("Interstellar", 2014): film(157336, "Interstellar", 2014)}, errors={("Nope", 2000): "not_found"})
    refs = make_flow(env, tmdb).resolve([ReferenceInput("Interstellar", 2014)], [ReferenceInput("Nope", 2000), ReferenceInput("Heist", 1995)])
    lines = references_summary(refs)
    assert "like 'Interstellar': used, a vector made from its TMDb plot (new)" in lines
    assert "avoid 'Nope': NOT used as a vector (unavailable: not_found)" in lines
    assert "avoid 'Heist': used, its vector from the index" in lines


# ---- pipeline: when references apply and what the trace says
class FlowStub:
    def __init__(self, refs=None, boom=False):
        self.refs, self.boom, self.calls = refs, boom, []

    def resolve(self, like, avoid, *, turn_id=None):
        self.calls.append((like, avoid, turn_id))
        if self.boom:
            raise RuntimeError("secret detail")
        return self.refs


def cfg(enabled=True, mode="semantic"):
    return {"reference": {"enabled": enabled}, "retrieval": {"search_mode": mode}}


SIGNALS = QuerySignals(like_titles=[ReferenceTitle(title="X", year=2014)], avoid_titles=[ReferenceTitle(title="Y")])


@pytest.mark.parametrize("config,skipped", [
    (cfg(enabled=False), "disabled"),
    (cfg(mode="hybrid"), "only_the_semantic_mode_uses_references"),
])
def test_references_are_skipped_with_a_stated_reason(config, skipped):
    from tool.rag.FromQueryEmbeddingToRes.models import SearchMode

    if config["retrieval"]["search_mode"] == "hybrid":
        config["retrieval"]["search_mode"] = SearchMode.hybrid
    else:
        config["retrieval"]["search_mode"] = SearchMode.semantic
    stub = FlowStub()
    refs, info = pipeline._resolve_references(config, SIGNALS, stub, "t")
    assert refs is None and info == {"skipped": skipped} and stub.calls == []
    assert pipeline._references_trace(refs, info) == {"used": False, "skipped": skipped}


def test_no_cited_movie_means_no_flow_and_no_trace_noise():
    from tool.rag.FromQueryEmbeddingToRes.models import SearchMode

    config = cfg()
    config["retrieval"]["search_mode"] = SearchMode.semantic
    stub = FlowStub()
    assert pipeline._resolve_references(config, QuerySignals(), stub, "t") == (None, {}) and stub.calls == []
    assert pipeline._references_trace(None, {}) == {}


def test_the_flow_is_called_with_the_titles_and_years_and_its_errors_do_not_escape():
    from tool.rag.FromQueryEmbeddingToRes.models import SearchMode

    config = cfg()
    config["retrieval"]["search_mode"] = SearchMode.semantic
    ok = FlowStub(refs=SimpleNamespace())
    pipeline._resolve_references(config, SIGNALS, ok, "turn-9")
    like, avoid, turn_id = ok.calls[0]
    assert (like[0].title, like[0].year, avoid[0].title, avoid[0].year, turn_id) == ("X", 2014, "Y", None, "turn-9")
    refs, info = pipeline._resolve_references(config, SIGNALS, FlowStub(boom=True), "t")
    assert refs is None and info == {"skipped": "reference_flow_error:RuntimeError"} and "secret" not in str(info)
    assert pipeline._resolve_references(config, SIGNALS, lambda: None, "t") == (None, {"skipped": "reference_flow_unavailable"})
    assert pipeline._resolve_references(config, SIGNALS, lambda: FlowStub(refs="R"), "t")[0] == "R"  # a provider is called lazily


# ---- parser: the titles are asked for only when the switch is on
class ParserClient:
    def __init__(self):
        self.instructions = None
        self.responses = self

    def parse(self, *, model, instructions, input, text_format):
        self.instructions = instructions
        return SimpleNamespace(output_parsed=QuerySignals(
            semantic_query="s", like_titles=[ReferenceTitle(title=" Interstellar ", year=2014), ReferenceTitle(title="interstellar", year=2014),
                                              ReferenceTitle(title="Old", year=1500), ReferenceTitle(title="  ")],
            avoid_titles=[ReferenceTitle(title="Star Wars", year=None)]))


def test_parser_asks_for_reference_titles_only_when_switched_on_and_cleans_them(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    client = ParserClient()
    monkeypatch.setattr(retrieval, "_signal_client", lambda: client)
    base = {"generation": {"model": "m"}}
    off = retrieval._build_signal_aware_query("q", {**base, "signals": {"avoid_query": True, "reference_titles": False}})
    assert "like_titles" not in client.instructions and off.like_titles == [] and off.avoid_titles == []
    on = retrieval._build_signal_aware_query("q", {**base, "signals": {"avoid_query": True, "reference_titles": True}})
    assert "8) like_titles" in client.instructions and "9) avoid_titles" in client.instructions and "never guess a year" in client.instructions
    assert [(t.title, t.year) for t in on.like_titles] == [("Interstellar", 2014), ("Old", None)]  # trimmed, deduplicated, bad year dropped
    assert [(t.title, t.year) for t in on.avoid_titles] == [("Star Wars", None)]
    alone = retrieval._build_signal_aware_query("q", {**base, "signals": {"avoid_query": False, "reference_titles": True}})
    assert "7) like_titles" in client.instructions and alone.like_titles
