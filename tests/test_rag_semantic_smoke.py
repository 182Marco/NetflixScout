"""Offline tests of the free-text RAG harness. SIMULATED parts (canned tool outputs, fake OpenAI client) are named as such; nothing here calls a model, an embedding or the
network. The REAL path (parser -> embedding -> Qdrant -> reorder) only runs with `run --live`."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from movie_db.harness.evaluation import run_rag_semantic_smoke as H


def _usage(i=10, o=5):
    return SimpleNamespace(input_tokens=i, output_tokens=o, total_tokens=i + o)


class FakeOpenAI:
    """SIMULATED inner client: records nothing itself, fails the stage it is told to."""

    def __init__(self, fail: str | None = None):
        self.fail = fail
        self.embeddings = SimpleNamespace(create=lambda **kw: self._go("embedding", kw))
        self.responses = SimpleNamespace(parse=lambda **kw: self._go("parser", kw))

    def _go(self, stage, kw):
        if self.fail == stage:
            raise TimeoutError("boom")
        return SimpleNamespace(usage=_usage())


# ---------------------------------------------------------------- cases file
def test_the_case_file_has_12_film_12_series_and_a_2_plus_2_trial():
    cases = H.load_cases("full")
    assert len(cases) == 24 and len({c["id"] for c in cases}) == 24
    assert sum(c["kind"] == "film" for c in cases) == 12 and sum(c["kind"] == "series" for c in cases) == 12
    smoke = H.load_cases("smoke")
    assert [c["kind"] for c in smoke].count("film") == 2 and [c["kind"] for c in smoke].count("series") == 2
    assert any(c.get("expect_empty") for c in cases)
    est = H.estimate(smoke)
    assert est["calls_max"] == 12 and H.estimate(cases)["calls_max"] == 72


# ---------------------------------------------------------------- grading (pure)
def test_matching_ignores_the_catalogue_qualifier_and_checks_every_key_given():
    item = {"title": "Il grande Gatsby (film 2013)", "original_title": "The Great Gatsby", "year": 2013}
    assert H.matches({"title": "Il grande Gatsby", "year": 2013}, item)
    assert H.matches({"title": "The Great Gatsby"}, item)
    assert not H.matches({"title": "Il grande Gatsby", "year": 1949}, item)
    ep = {"title": "Pilot", "series": "Lost (serie televisiva)", "level": "episode", "season": 1}
    assert H.matches({"series": "Lost", "level": "episode"}, ep) and not H.matches({"series": "Lost", "season": 2}, ep)


def test_grade_reports_hit_forbidden_and_filter_violations_separately():
    case = {"k": 3, "expect_any": [{"title": "Tenet"}], "forbid_title_contains": ["matrix"], "filters": {"director": "nolan", "year_from": 2000}}
    good = [{"title": "Tenet", "year": 2020, "directors": ["Christopher Nolan"]}]
    assert H.grade(case, good, {})["valid"] and H.grade(case, good, {})["hit_rank"] == 1
    bad = [{"title": "The Matrix", "year": 1999, "directors": ["Wachowski"]}, {"title": "Tenet", "year": 2020, "directors": ["Christopher Nolan"]}]
    g = H.grade(case, bad, {})
    assert g["hit_rank"] == 2 and g["forbidden"] == ["The Matrix"] and len(g["filter_violations"]) == 2 and not g["valid"]
    # results beyond k are not judged
    assert H.grade({**case, "k": 1, "forbid_title_contains": ["matrix"]}, [good[0], bad[0]], {})["forbidden"] == []


def test_an_empty_expectation_and_a_note_expectation():
    empty = {"k": 5, "expect_empty": True, "expect_note": "series_not_in_index"}
    assert H.grade(empty, [], {"series_not_in_index": "Zorblax"})["valid"]
    assert not H.grade(empty, [{"title": "x"}], {"series_not_in_index": "Zorblax"})["valid"]
    assert not H.grade(empty, [], {})["valid"]


# ---------------------------------------------------------------- recorder (SIMULATED client)
def test_the_recorder_labels_stages_measures_tokens_and_reraises():
    rec = H.Recorder(inner=FakeOpenAI())
    rec.client.embeddings.create(model="e", input=["x"])
    class Signals: ...
    rec.client.responses.parse(model="m", text_format=Signals)
    class Order: ...
    rec.client.responses.parse(model="m", text_format=Order)
    assert [e["stage"] for e in rec.events] == ["embedding", "parser", "reranking"]
    assert all(e["ok"] and e["usage"]["total"] == 15 for e in rec.events)
    rec.reset()
    rec.inner = FakeOpenAI(fail="embedding")
    with pytest.raises(TimeoutError):
        rec.client.embeddings.create(model="e", input=["x"])
    assert rec.events[0]["ok"] is False and rec.events[0]["error"] == "TimeoutError"


def test_failure_attribution():
    ok = {"stage": "parser", "ok": True}
    assert H.attribute_failure([ok], None) is None
    assert H.attribute_failure([ok, {"stage": "embedding", "ok": False}], "TimeoutError") == "embedding"
    assert H.attribute_failure([{"stage": "parser", "ok": False}, {"stage": "embedding", "ok": False}], "TimeoutError") == "embedding"  # the swallowed parser error is not the cause
    assert H.attribute_failure([ok], "ResponseHandlingException") == "retrieval"  # Qdrant: no model call failed
    assert H.attribute_failure([{"stage": "reranking", "ok": False}], None) == "reranking"  # swallowed by the tool, still seen by the proxy


# ---------------------------------------------------------------- run_case with SIMULATED tools
class CannedTool:
    def __init__(self, result=None, raises=None, events=None, recorder=None):
        self.result, self.raises, self.events, self.recorder = result, raises, events or [], recorder

    def run(self, **kw):
        if self.recorder is not None:
            self.recorder.events.extend(self.events)
        if self.raises:
            raise self.raises
        return self.result


def test_run_case_with_canned_film_and_series_outputs():
    rec = H.Recorder()
    film = {"chunks": [{"title": "Tenet", "original_title": "Tenet", "release_year": "2020", "imdb_id": "tt6723592", "directors": ["Christopher Nolan"], "countries": ["Stati Uniti"], "cast": "A; B"}],
            "metadata": {"search_notes": {}}}
    events = [{"stage": "parser", "model": "p", "ok": True, "error": None, "ms": 5, "usage": {"input": 1, "output": 1, "total": 2}}]
    case = next(c for c in H.load_cases("full") if c["id"] == "F05")
    row = H.run_case(case, {"film": CannedTool(film, events=events, recorder=rec)}, rec, None)
    assert row["grade"]["valid"] and row["items"][0]["imdb_id"] == "tt6723592" and row["calls"]["parser"] == 1 and row["failed_stage"] is None
    s08 = next(c for c in H.load_cases("full") if c["id"] == "S08")
    series = {"metadata": {"series_rag": {"status": "empty", "items": [], "notes": {"series_not_in_index": "Zorblax Quest"}}}}
    row = H.run_case(s08, {"series": CannedTool(series, recorder=rec)}, rec, None)
    assert row["grade"]["valid"] and row["items"] == []
    row = H.run_case(case, {"film": CannedTool(raises=ConnectionError("down"), recorder=rec)}, rec, None)
    assert row["exception"] == "ConnectionError" and row["failed_stage"] == "retrieval" and not row["grade"]["valid"]


def test_a_parser_fallback_is_reported_as_degraded_even_though_the_tool_swallowed_it():
    rec = H.Recorder()
    film = {"chunks": [], "metadata": {"search_notes": {"parser_failed": "TimeoutError"}}}
    events = [{"stage": "parser", "model": "p", "ok": False, "error": "TimeoutError", "ms": 9}]
    row = H.run_case(next(c for c in H.load_cases("full") if c["id"] == "F01"), {"film": CannedTool(film, events=events, recorder=rec)}, rec, None)
    assert row["failed_stage"] == "parser" and row["degraded"] == ["parser"]  # no exception: the swallowed stage is reported


# ---------------------------------------------------------------- REAL series tool, SIMULATED model (no network: the fake client raises before Qdrant is touched)
def test_the_real_series_tool_attributes_an_embedding_failure_through_the_recording_client():
    rec = H.Recorder(inner=FakeOpenAI(fail="embedding"))

    def parse_stub(**kw):  # the parser answers nothing usable -> the tool falls back to the plain request, as in production
        raise TimeoutError("parser down")
    rec.inner.responses = SimpleNamespace(parse=parse_stub)
    tool = H.build_series_tool(rec)
    row = H.run_case(next(c for c in H.load_cases("full") if c["id"] == "S01"), {"series": tool}, rec, None)
    stages = [(e["stage"], e["ok"]) for e in rec.events]
    assert ("parser", False) in stages and ("embedding", False) in stages
    assert row["failed_stage"] == "embedding" and "parser" in row["degraded"] and row["tool_error"]["error"] == "series_rag_unavailable"


# ---------------------------------------------------------------- guards and report
def test_run_refuses_without_live_or_without_the_authorisation(monkeypatch, capsys):
    def boom(): raise AssertionError("the OpenAI client must not be built")
    monkeypatch.setattr(H, "real_openai", boom)
    args = lambda **kw: SimpleNamespace(live=False, set="smoke", only=None, label="t", force=False, no_handoff=True, price=None, **kw)  # noqa: E731
    assert H.cmd_run(args()) == 2
    monkeypatch.delenv(H.AUTH_ENV, raising=False)
    assert H.cmd_run(SimpleNamespace(live=True, set="smoke", only=None, label="t", force=False, no_handoff=True, price=None)) == 2
    monkeypatch.setenv(H.AUTH_ENV, "maybe")
    assert H.cmd_run(SimpleNamespace(live=True, set="smoke", only=None, label="t", force=False, no_handoff=True, price=None)) == 2


def test_summary_counts_tokens_cost_and_latency(tmp_path, monkeypatch):
    ev = lambda stage, model, i, o, ok=True: {"stage": stage, "model": model, "ok": ok, "error": None if ok else "X", "ms": 100, "usage": {"input": i, "output": o, "total": i + o}}  # noqa: E731
    grade = {"valid": True, "hit_rank": 2, "forbidden": [], "filter_violations": []}
    rows = [{"id": "F01", "kind": "film", "events": [ev("parser", "luna", 1000, 100), ev("embedding", "emb", 50, 0), ev("reranking", "sol", 20000, 50)],
             "grade": grade, "failed_stage": None, "degraded": [], "total_ms": 3000, "handoff": {"ok": 5, "without_imdb_id": 0}}]
    s = H.summarize(rows, {"luna": (1.0, 2.0)})
    assert s["model_calls"] == 3 and s["tokens_by_stage"]["reranking"]["input"] == 20000 and s["unpriced_models"] == ["sol"]
    assert s["cost_usd_priced_calls"] == round((1000 * 1.0 + 100 * 2.0) / 1e6 + 50 * 0.13 / 1e6, 4)
    assert s["by_kind"]["film"]["handoff"] == {"ok": 5, "without_imdb_id": 0} and s["by_kind"]["film"]["latency_ms"]["median"] == 3000
    monkeypatch.setattr(H, "OUT_ROOT", tmp_path)
    (tmp_path / "t").mkdir()
    rows[0].update(category="x", query="q", items=[], notes={})
    (tmp_path / "t" / "run.jsonl").write_text(json.dumps(rows[0]) + "\n")
    assert H.cmd_report(SimpleNamespace(label="t", price=["luna=1:2"])) == 0 and (tmp_path / "t" / "summary.json").exists()
    with pytest.raises(SystemExit):
        H.parse_prices(["bad"])


# ---------------------------------------------------------------- REAL film tool + real Qdrant (local, read only), SIMULATED model: skipped when the server is down
def _qdrant_ready() -> bool:
    try:
        from qdrant_client import QdrantClient
        return "wikipedia_films_it_v3" in {c.name for c in QdrantClient(url="http://127.0.0.1:6333", timeout=3).get_collections().collections}
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _qdrant_ready(), reason="needs the local Qdrant with the film collection")
def test_the_real_film_tool_reaches_the_recording_client_and_an_embedding_failure_is_attributed():
    rec = H.Recorder(inner=FakeOpenAI(fail="embedding"))
    rec.inner.responses = SimpleNamespace(parse=lambda **kw: (_ for _ in ()).throw(TimeoutError("parser down")))
    case = next(c for c in H.load_cases("full") if c["id"] == "F05")
    row = H.run_case(case, {"film": H.build_film_tool()}, rec, None)
    assert [(e["stage"], e["ok"]) for e in rec.events][:2] == [("parser", False), ("embedding", False)]
    assert row["exception"] == "TimeoutError" and row["failed_stage"] == "embedding" and row["items"] == []


# ---------------------------------------------------------------- FASE 19 preparation (offline)
def test_the_interpretation_and_the_review_sheet_come_from_the_tools_own_trace(tmp_path):
    result = {"trace": [{"kind": "retrieval", "data": {"signals": {"semantic_query": "simulated realities", "negative_signals": ["Matrix sequels"]}, "embedded_text": "simulated realities"}},
                        {"kind": "rerank", "data": {"backend": "llm"}}]}
    got = H._interpretation(result)
    assert got["signals"]["semantic_query"] == "simulated realities" and got["engine"] == "llm" and H._interpretation({}) == {"signals": {}, "embedded_text": None, "engine": None}
    row = {"id": "F02", "category": "like_but_not", "query": "q", "grade": {"valid": True, "hit_rank": 1}, "items": [{"title": "Dark City", "year": 1998, "level": "film", "imdb_id": "tt1"}], **got}
    H._write_review_sheet(tmp_path, [row])
    text = (tmp_path / "review.md").read_text()
    assert "simulated realities" in text and "Matrix sequels" in text and "| 1 | Dark City | 1998 | film | tt1 |  |" in text and "film >= 10/12" in text


def test_the_full_batteries_have_clear_criteria_and_the_estimate_matches_the_plan():
    cases = H.load_cases("full")
    est = H.estimate(cases)
    assert est["requests"] == 24 and est["calls_max"] == 72
    for c in cases:  # every request can be judged: an acceptable set, a nonexistence/empty expectation, or a contradiction note
        assert c.get("expect_any") or c.get("expect_empty") or c.get("expect_note"), c["id"]
        assert c.get("k", 5) in range(1, 11) and c["query"].strip()


# ---------------------------------------------------------------- FASE 19I: the actor check uses the complete cast, the one the retriever filters on
GATSBY_SHOWN = ["Carey Mulligan", "Joel Edgerton", "Isla Fisher", "Jason Clarke", "Amitabh Bachchan", "Elizabeth Debicki", "Callan McAuliffe", "Adelaide Clemens"]   # the 8 names of the result
ACTOR_CASE = {"k": 5, "filters": {"actor": "dicaprio"}}


def test_f06_the_actor_beyond_the_shown_names_is_not_a_violation_when_the_complete_cast_has_him():
    gatsby = {"title": "Il grande Gatsby (film 2013)", "year": 2013, "imdb_id": "tt1343092", "cast": GATSBY_SHOWN}
    assert len(H.grade(ACTOR_CASE, [gatsby], {})["filter_violations"]) == 1                      # the recorded false alarm, without the complete cast
    complete = {**gatsby, "cast_full": [H.norm(n) for n in [*GATSBY_SHOWN, "Leonardo DiCaprio", "Daniel Newman"]]}
    g = H.grade(ACTOR_CASE, [complete], {})
    assert g["filter_violations"] == [] and g["checks"]["filters"]


def test_a_real_violation_is_still_reported_with_the_complete_cast():
    other = {"title": "Un altro film", "year": 2010, "imdb_id": "tt0000001", "cast": GATSBY_SHOWN[:5], "cast_full": [H.norm(n) for n in GATSBY_SHOWN]}
    g = H.grade(ACTOR_CASE, [other], {})
    assert len(g["filter_violations"]) == 1 and "cast lacks dicaprio" in g["filter_violations"][0] and not g["checks"]["filters"]
    assert "complete cast not available" not in g["filter_violations"][0]


def test_without_the_complete_cast_the_check_is_exactly_as_strict_as_before_and_says_why():
    item = {"title": "X", "year": 2000, "cast": ["Leonardo DiCaprio"]}
    assert H.grade(ACTOR_CASE, [item], {})["filter_violations"] == []
    short = {"title": "X", "year": 2000, "cast": ["A", "B"]}
    v = H.grade(ACTOR_CASE, [short], {})["filter_violations"]
    assert len(v) == 1 and "complete cast not available" in v[0]


def test_the_other_filters_are_untouched_by_the_cast_change():
    case = {"k": 5, "filters": {"director": "nolan", "year_from": 2000, "country": "Giappone", "actor": "dicaprio"}}
    item = {"title": "T", "year": 1999, "directors": ["X"], "countries": ["Francia"], "cast": [], "cast_full": ["leonardo dicaprio"]}
    kinds = [v.split(": ", 1)[1].split(" ")[0] for v in H.grade(case, [item], {})["filter_violations"]]
    assert sorted(kinds) == ["countries", "directors", "year"]


def test_attach_full_cast_runs_only_for_an_actor_filter_and_never_invents_a_cast():
    calls = []

    def lookup(ids):
        calls.append(ids)
        return {"tt1": ["leonardo dicaprio"]}
    items = [{"imdb_id": "tt1"}, {"imdb_id": "tt2"}, {"imdb_id": None}]
    H.attach_full_cast({"filters": {"year_from": 1990}}, items, lookup)
    assert calls == [] and all("cast_full" not in i for i in items)
    H.attach_full_cast(ACTOR_CASE, items, lookup)
    assert len(calls) == 1 and set(calls[0]) == {"tt1", "tt2", None}
    assert items[0]["cast_full"] == ["leonardo dicaprio"] and "cast_full" not in items[1] and "cast_full" not in items[2]
    H.attach_full_cast(ACTOR_CASE, [{"imdb_id": "tt1"}], None)                                 # no lookup: untouched


def test_the_lookup_reads_the_filter_field_from_the_collection_and_writes_nothing():
    import numpy as np
    from qdrant_client import QdrantClient, models
    client = QdrantClient(":memory:")
    client.create_collection("f", vectors_config=models.VectorParams(size=2, distance=models.Distance.COSINE))
    client.upsert("f", points=[models.PointStruct(id=1, vector=[1.0, 0.0], payload={"imdb_id": "tt1343092", "actor_names_norm": ["carey mulligan", "leonardo dicaprio"]}),
                               models.PointStruct(id=2, vector=[0.0, 1.0], payload={"imdb_id": "tt9", "actor_names_norm": ["someone"]})])
    index = type("Idx", (), {"client": client, "collection": "f"})()
    lookup = H.full_cast_lookup(index)
    assert lookup(["tt1343092", None]) == {"tt1343092": ["carey mulligan", "leonardo dicaprio"]} and lookup([]) == {}
    assert client.count("f").count == 2


def test_run_case_wires_the_complete_cast_into_the_grade_of_an_actor_case_without_any_model():
    """The path `run --live` takes: `run_case` -> film items -> complete cast attached -> grade. The film tool is a stub, the recorder has no client."""
    case = next(c for c in H.load_cases("full") if c["id"] == "F06")
    chunk = {"title": "Il grande Gatsby (film 2013)", "original_title": "The Great Gatsby", "release_year": "2013", "imdb_id": "tt1343092", "directors": ["Baz Luhrmann"],
             "countries": ["Stati Uniti"], "cast": "; ".join(GATSBY_SHOWN)}
    tools = {"film": type("T", (), {"run": lambda self, *, query, params: {"chunks": [chunk], "metadata": {}, "trace": []}})()}
    lookup = lambda ids: {"tt1343092": [H.norm(n) for n in [*GATSBY_SHOWN, "Leonardo DiCaprio"]]}
    without = H.run_case(case, tools, H.Recorder(), None)
    with_cast = H.run_case(case, tools, H.Recorder(), None, lookup)
    assert without["grade"]["filter_violations"] and with_cast["grade"]["filter_violations"] == []
    assert with_cast["items"][0]["cast_full"] and with_cast["calls"] == {"parser": 0, "embedding": 0, "reranking": 0}


def test_cmd_run_builds_the_cast_lookup_and_passes_it_to_run_case() -> None:
    import inspect
    source = inspect.getsource(H.cmd_run)
    assert "full_cast_lookup(index_for(" in source and "run_case(c, tools, recorder, cinema, cast_lookup)" in source
