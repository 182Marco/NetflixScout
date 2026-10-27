"""'Like X, not like Y': the parser's avoid_query, the wider candidate pool and the LLM list-wise rerank (offline, fakes)."""
from __future__ import annotations

import app as app_module
from tool.rag.FromQueryEmbeddingToRes import rerank as rerank_module
from tool.rag.FromQueryEmbeddingToRes import retrieval
from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals

CHUNKS = [{"id": f"c{i}", "title": f"Film {i}", "release_year": "2000", "genres": "Drama", "testo": f"plot {i}", "score": 0.5} for i in range(4)]


def cfg(**rerank):
    base = {"backend": "cohere", "cohere_model": "m", "llm_model": "llm", "avoid_llm": True, "avoid_pool": 50}
    return {"rerank": {**base, **rerank}, "retrieval": {"k_largo": 10, "k_finale": 2}}


class FakeParse:
    def __init__(self, indices):
        self.output_parsed = type("O", (), {"indici": indices})()


class FakeClient:
    def __init__(self, indices):
        self.indices, self.calls = indices, []
        self.responses = self

    def parse(self, **kw):
        self.calls.append(kw)
        return FakeParse(self.indices)


def test_defaults_enable_the_measured_configuration():
    rag = app_module.CONFIG["rag"]
    assert rag["rerank"]["avoid_llm"] is True and rag["rerank"]["avoid_pool"] == 50 and rag["signals"]["avoid_query"] is True
    assert "avoid_penalty" not in rag["rerank"]  # the Cohere fusion did not beat the baseline and was removed


def test_candidate_pool_grows_only_for_requests_with_something_to_avoid():
    plain, avoiding = QuerySignals(), QuerySignals(avoid_query="epic space opera")
    assert retrieval.candidate_pool_size(cfg(), plain) == 10
    assert retrieval.candidate_pool_size(cfg(), avoiding) == 50
    assert retrieval.candidate_pool_size(cfg(avoid_llm=False), avoiding) == 10
    assert retrieval.candidate_pool_size({"retrieval": {"k_largo": 80}, "rerank": {"avoid_llm": True, "avoid_pool": 50}}, avoiding) == 80


def test_llm_rerank_orders_best_first_ignores_bad_indices_and_keeps_the_rest():
    client = FakeClient([2, 2, 9, -1, 0])
    out = rerank_module.rerank_llm_request("like X not Y", "wanted", "avoid", CHUNKS, "llm", openai_client=client)
    assert [c["id"] for c in out] == ["c2", "c0", "c1", "c3"] and out[0]["score"] > out[-1]["score"]
    sent = client.calls[0]["input"]
    assert "like X not Y" in sent and "wanted" in sent and "avoid" in sent and "[3] Film 3 (2000) | Drama | plot 3" in sent


def test_rerank_uses_the_llm_for_avoid_requests(monkeypatch):
    seen = {}

    def fake_llm(request, wanted, avoid, chunks, model):
        seen.update(request=request, wanted=wanted, avoid=avoid, model=model, n=len(chunks))
        return list(reversed(chunks))

    monkeypatch.setattr(retrieval, "rerank_llm_request", fake_llm)
    monkeypatch.setattr(retrieval, "rerank_cohere", lambda *a, **k: (_ for _ in ()).throw(AssertionError("cohere must not run")))
    out = retrieval._rerank("wanted text", CHUNKS, cfg(), signals=QuerySignals(avoid_query="to avoid"), request="user words")
    assert [c["id"] for c in out] == ["c3", "c2"]  # k_finale=2
    assert seen == {"request": "user words", "wanted": "wanted text", "avoid": "to avoid", "model": "llm", "n": 4}


def test_rerank_falls_back_to_cohere_when_the_llm_fails_or_is_not_applicable(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("llm down")

    monkeypatch.setattr(retrieval, "rerank_llm_request", boom)
    calls = []
    monkeypatch.setattr(retrieval, "rerank_cohere", lambda q, chunks, model: calls.append(q) or [{**c, "score": 1.0 - i / 10} for i, c in enumerate(chunks)])
    avoiding = QuerySignals(avoid_query="to avoid")
    assert [c["id"] for c in retrieval._rerank("q", CHUNKS, cfg(), signals=avoiding, request="r")] == ["c0", "c1"]
    # not applicable: nothing to avoid, no request text, or the switch is off
    monkeypatch.setattr(retrieval, "rerank_llm_request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not run")))
    retrieval._rerank("q", CHUNKS, cfg(), signals=QuerySignals(), request="r")
    retrieval._rerank("q", CHUNKS, cfg(), signals=avoiding, request=None)
    retrieval._rerank("q", CHUNKS, cfg(avoid_llm=False), signals=avoiding, request="r")
    assert len(calls) == 4


class ParserClient:
    def __init__(self):
        self.instructions = None
        self.responses = self

    def parse(self, *, model, instructions, input, text_format):
        self.instructions = instructions
        return type("R", (), {"output_parsed": QuerySignals(semantic_query="a space film", avoid_query="epic space opera")})()


def test_parser_prompt_has_the_avoid_field_only_when_switched_on(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    client = ParserClient()
    monkeypatch.setattr(retrieval, "_signal_client", lambda: client)
    on = retrieval._build_signal_aware_query("q", {"generation": {"model": "m"}, "signals": {"avoid_query": True}})
    assert "7) avoid_query" in client.instructions and "describing ONLY the kind of movie" in client.instructions
    assert on.avoid_query == "epic space opera"
    off = retrieval._build_signal_aware_query("q", {"generation": {"model": "m"}, "signals": {"avoid_query": False}})
    assert "avoid_query" not in client.instructions and off.avoid_query == ""  # the old prompt, and the field is dropped


def test_untitled_plots_do_not_take_part_in_the_llm_rerank(monkeypatch):
    seen = {}

    def fake_llm(request, wanted, avoid, chunks, model):
        seen["titles"] = [c.get("title") for c in chunks]
        return chunks

    monkeypatch.setattr(retrieval, "rerank_llm_request", fake_llm)
    chunks = [{"id": "u", "title": None, "testo": "x", "score": 1.0}, *CHUNKS]
    out = retrieval._rerank("q", chunks, cfg(), signals=QuerySignals(avoid_query="a"), request="r")
    assert None not in seen["titles"] and all(c["title"] for c in out)
    # too few titled plots to fill k_finale: nothing is thrown away
    retrieval._rerank("q", [chunks[0], CHUNKS[0]], cfg(), signals=QuerySignals(avoid_query="a"), request="r")
    assert seen["titles"] == [None, "Film 0"]
