from __future__ import annotations

import ast
import threading
from pathlib import Path

import pytest
from tmdb_support import (
    MOVIE_ID,
    calls_shown,
    make_tool,
    movie_payload,
    run,
    search_movie_payload,
    tmdb_meta,
)

from tool.tmdb.budget import CallBudget
from tool.tmdb.cache import TtlCache, cache_key
from tool.tmdb.cooldown import Cooldown, retry_after_seconds

ROOT = Path(__file__).resolve().parents[1]
DETAILS = {"operation": "movie_details", "tmdb_id": MOVIE_ID}


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_budget_reserves_atomically_up_to_the_limit() -> None:
    budget = CallBudget(50)
    granted: list[bool] = []
    threads = [threading.Thread(target=lambda: granted.append(budget.try_reserve())) for _ in range(80)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert granted.count(True) == 50 and budget.remaining == 0
    with pytest.raises(ValueError):
        CallBudget(0)


def test_cache_ttl_expiry_lru_and_disabled() -> None:
    clock = Clock()
    cache = TtlCache(10, max_entries=2, clock=clock)
    cache.set(("a", ()), {"v": 1})
    clock.now += 9.9
    assert cache.get(("a", ())) == {"v": 1}
    clock.now += 0.1
    assert cache.get(("a", ())) is None

    for name in "bcd":
        cache.set((name, ()), {"v": name})
    assert len(cache) == 2 and cache.get(("b", ())) is None

    disabled = TtlCache(0)
    disabled.set(("a", ()), {"v": 1})
    assert disabled.get(("a", ())) is None


def test_cache_key_is_order_independent_and_has_no_credential() -> None:
    assert cache_key("/movie/1", {"b": "2", "a": "1"}) == cache_key("/movie/1", {"a": "1", "b": "2"})
    assert "api_key" not in repr(cache_key("/movie/1", {"language": "it-IT"}))


def test_exact_http_count_and_cache_hits_are_free_across_turns() -> None:
    tool, transport = make_tool({"/search/movie": search_movie_payload(), f"/movie/{MOVIE_ID}": movie_payload()})
    request = {"operation": "movie_details", "title": "Interstellar"}

    first = run(tool, request)
    second = run(tool, request)

    assert transport.paths == ["/search/movie", f"/movie/{MOVIE_ID}"]
    assert len(calls_shown(first)) == 2
    assert calls_shown(second) == []  # served from cache: nothing called, nothing shown
    assert tmdb_meta(second)["status"] == "ok"


def test_cache_expires_between_turns() -> None:
    clock = Clock()
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": movie_payload()}, cache_ttl=60, clock=clock)

    run(tool, DETAILS)
    clock.now += 61
    run(tool, DETAILS)

    assert transport.paths == [f"/movie/{MOVIE_ID}"] * 2


def test_turn_memo_dedupes_even_without_cache() -> None:
    tool, transport = make_tool({f"/movie/{MOVIE_ID}": movie_payload()}, cache_ttl=0)

    run(tool, DETAILS, DETAILS)
    run(tool, DETAILS)

    assert transport.paths == [f"/movie/{MOVIE_ID}"] * 2  # once per turn


@pytest.mark.parametrize("limit", [1, 2, 6, 20])
def test_budget_holds_for_any_configured_limit(limit) -> None:
    routes = {"/search/movie": search_movie_payload(), f"/movie/{MOVIE_ID}": movie_payload()}
    routes |= {f"/movie/{i}": movie_payload(id=i) for i in range(1, 5)}
    tool, transport = make_tool(routes, max_calls=limit)
    requests = [{"operation": "movie_details", "title": "Interstellar"}] + [
        {"operation": "movie_details", "tmdb_id": i} for i in range(1, 4)
    ]

    result = run(tool, *requests)

    needed = 5  # search + 4 details
    assert len(transport.calls) == min(limit, needed)
    assert len(calls_shown(result)) == len(transport.calls)
    statuses = [r["status"] for r in tmdb_meta(result)["requests"]]
    if limit < needed:
        assert "call_limit_reached" in [r.get("error") for r in tmdb_meta(result)["requests"]]
        assert tmdb_meta(result)["status"] in ("partial", "error")
    else:
        assert statuses == ["ok"] * 4


def test_optional_calls_are_skipped_when_the_budget_is_spent() -> None:
    # watch/providers missing from the append response → separate (optional) call.
    tool, transport = make_tool(
        {"/search/movie": search_movie_payload(), f"/movie/{MOVIE_ID}": movie_payload()}, max_calls=2
    )

    result = run(tool, {"operation": "movie_details", "title": "Interstellar", "facets": ["watch_providers"]})

    request = tmdb_meta(result)["requests"][0]
    assert request["status"] == "partial" and request["skipped_for_budget"] == ["watch_providers"]
    assert len(transport.calls) == 2


def test_rate_limit_trips_a_cooldown_without_retries() -> None:
    clock = Clock()
    tool, transport = make_tool({"/movie/1": (429, {"Retry-After": "30"}, {}), "/movie/2": movie_payload(id=2)})
    tool.cooldown = Cooldown(clock=clock)

    first = run(tool, {"operation": "movie_details", "tmdb_id": 1}, {"operation": "movie_details", "tmdb_id": 2})

    assert transport.paths == ["/movie/1"]  # second request not sent during the pause
    assert [r["error"] for r in tmdb_meta(first)["requests"]] == ["rate_limited", "rate_limited"]
    clock.now += 31
    run(tool, {"operation": "movie_details", "tmdb_id": 2})
    assert transport.paths == ["/movie/1", "/movie/2"]
    assert retry_after_seconds({}) == 10.0 and retry_after_seconds({"retry-after": "9999"}) == 120.0


def test_unauthorized_stops_further_calls() -> None:
    tool, transport = make_tool({"/movie/1": (401, {}, {}), "/movie/2": movie_payload(id=2)})

    result = run(tool, {"operation": "movie_details", "tmdb_id": 1}, {"operation": "movie_details", "tmdb_id": 2})

    assert transport.paths == ["/movie/1"]
    assert [r["error"] for r in tmdb_meta(result)["requests"]] == ["unauthorized", "unauthorized"]


def test_http_module_is_the_only_io_point() -> None:
    offenders = []
    for path in sorted((ROOT / "tool" / "tmdb").rglob("*.py")):
        if path.name == "http.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            imported = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
            if any(name.startswith(("urllib.request", "http.client", "socket", "requests", "httpx")) for name in imported):
                offenders.append(path.name)
            if isinstance(node, ast.Attribute) and node.attr == "transport" and isinstance(node.ctx, ast.Load):
                parent_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.func is node]
                if parent_calls:
                    offenders.append(path.name)
    assert offenders == []
