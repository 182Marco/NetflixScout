"""The bridge between `tmdb_search` and the catalog: what it picks, what it leaves alone, how it fails."""
from __future__ import annotations

import copy

import pytest

from catalog_enricher import CatalogEnricher


class Outcome:
    def __init__(self, status, reason=""):
        self.status, self.reason = status, reason

    def as_trace(self):
        return {"status": self.status, **({"reason": self.reason} if self.reason else {})}


def request(op="movie_details", status="ok", entities=("movie:10",), **extra):
    return {"index": 0, "operation": op, "status": status,
            "entities": {key: {"essentials": {}} for key in entities}, **extra}


def result(*requests, turn_id="t1", with_step=True):
    trace = [{"kind": "tmdb_calls", "title": "TMDb", "data": {"calls": [], "attributions": [], "items": []}}]
    return {"query": "q", "chunks": [{"x": 1}], "turn_id": turn_id, "metadata": {"tmdb": {"requests": list(requests)}},
            "trace": trace if with_step else []}


def make(**kw):
    log = {"read": [], "sync": [], "inv": 0}

    def read(tmdb_id, turn_id):
        log["read"].append((tmdb_id, turn_id))
        return {"tmdb_id": tmdb_id}, ""

    def sync(record):
        log["sync"].append(record)
        return Outcome("inserted")

    def inv():
        log["inv"] += 1

    opts = {"read_record": read, "sync": sync, "invalidate": inv, "blocking_notes": ("alternative_title_match",)}
    opts.update(kw)
    return CatalogEnricher(**opts), log


def test_a_clean_movie_details_is_written_and_only_the_trace_changes():
    enricher, log = make()
    original = result(request())
    snapshot = copy.deepcopy(original)
    out = enricher.enrich(tool_result=original)
    assert log["sync"] == [{"tmdb_id": 10}] and log["inv"] == 1 and log["read"] == [(10, "t1")]
    assert out["trace"][0]["data"]["catalog"] == [{"status": "inserted", "tmdb_id": 10}]
    assert out["metadata"] == snapshot["metadata"] and out["chunks"] == snapshot["chunks"]
    assert original == snapshot  # the input is not mutated


@pytest.mark.parametrize("req", [
    request(error="unverified_match"),
    request(status="error"),
    request(status="partial"),
    request(candidates=[{"id": 1}]),
    request(skipped_for_budget=["x"]),
    request(notes=["alternative_title_match"]),
    request(op="search"),
    request(op="tv_details", entities=("tv:5",)),
    request(op="person_details", entities=("person:5",)),
    request(entities=()),
])
def test_requests_that_are_not_clean_movie_details_are_left_alone(req):
    enricher, log = make()
    out = enricher.enrich(tool_result=result(req))
    assert log["read"] == [] and log["sync"] == [] and out == result(req)


def test_at_most_two_movies_per_turn_and_never_the_same_one_twice():
    enricher, log = make()
    reqs = [request(entities=(f"movie:{i}",)) for i in (1, 2, 3)]
    enricher.enrich(tool_result=result(*reqs))
    enricher.enrich(tool_result=result(request(entities=("movie:1",)), request(entities=("movie:4",))))
    assert [r["tmdb_id"] for r in log["sync"]] == [1, 2]
    enricher.enrich(tool_result=result(request(entities=("movie:4",)), turn_id="t2"))
    assert [r["tmdb_id"] for r in log["sync"]] == [1, 2, 4]


def test_records_that_cannot_be_read_are_skipped_with_the_reason():
    enricher, log = make(read_record=lambda i, t: (None, "call_limit_reached"))
    out = enricher.enrich(tool_result=result(request()))
    assert out["trace"][0]["data"]["catalog"] == [{"status": "skipped", "reason": "call_limit_reached", "tmdb_id": 10}]
    assert log["inv"] == 0


@pytest.mark.parametrize("where", ["read_record", "sync", "invalidate"])
def test_any_exception_inside_never_escapes_and_never_changes_metadata(where):
    def boom(*a, **k):
        raise RuntimeError("secret detail")

    enricher, _ = make(**{where: boom})
    original = result(request())
    out = enricher.enrich(tool_result=original)
    assert out["metadata"] == original["metadata"] and "enrichment_error" not in str(out["metadata"])
    assert "secret detail" not in str(out)


def test_the_bridge_itself_failing_returns_the_original_result():
    enricher, _ = make()
    broken = {"metadata": "not a dict", "trace": None}
    assert enricher.enrich(tool_result=broken) is broken


def test_no_tmdb_step_means_no_diagnostics():
    enricher, log = make()
    out = enricher.enrich(tool_result=result(request(), with_step=False))
    assert log["sync"] and out["trace"] == []


def test_the_time_budget_stops_the_second_movie():
    ticks = iter([0.0, 1.0, 1.5, 99.0, 99.0, 99.0])
    enricher, log = make(clock=lambda: next(ticks), budget_seconds=20.0)
    out = enricher.enrich(tool_result=result(request(entities=("movie:1",)), request(entities=("movie:2",))))
    statuses = [c["status"] + ":" + c.get("reason", "") for c in out["trace"][0]["data"]["catalog"]]
    assert statuses == ["inserted:", "error:timeout"] and len(log["sync"]) == 1


def test_bridge_imports_nothing_from_the_tool_domains():
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[1] / "catalog_enricher.py").read_text())
    roots = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    roots |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not roots & {"tool", "presenters", "web_api", "web_lists", "app", "orchestrator"}
