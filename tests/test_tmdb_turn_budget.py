"""The TMDb call budget belongs to the turn, not to one run: a turn can run several tools."""
from __future__ import annotations

from tmdb_support import make_tool, search_movie_payload

from turn import TOOL_PARAM_TURN_ID


def _search(tool, title: str, turn_id: str | None):
    params = {"requests": [{"operation": "search", "kind": "movie", "search_query": title, "limit": 1}]}
    if turn_id:
        params[TOOL_PARAM_TURN_ID] = turn_id
    return tool.run(query="domanda", params=params, conversation_history=[])


def test_runs_of_the_same_turn_share_one_budget() -> None:
    tool, transport = make_tool({"/search/movie": search_movie_payload()}, max_calls=2, cache_ttl=0)

    for title in ("Uno", "Due", "Tre", "Quattro"):
        _search(tool, title, "turn-1")

    assert len(transport.calls) == 2


def test_a_new_turn_gets_a_fresh_budget() -> None:
    tool, transport = make_tool({"/search/movie": search_movie_payload()}, max_calls=1, cache_ttl=0)

    _search(tool, "Uno", "turn-1")
    _search(tool, "Due", "turn-1")
    _search(tool, "Tre", "turn-2")

    assert len(transport.calls) == 2


def test_without_a_turn_id_every_run_has_its_own_budget() -> None:
    tool, transport = make_tool({"/search/movie": search_movie_payload()}, max_calls=1, cache_ttl=0)

    _search(tool, "Uno", None)
    _search(tool, "Due", None)

    assert len(transport.calls) == 2


def test_the_turn_id_is_not_a_tool_input_and_never_reaches_the_result() -> None:
    tool, _ = make_tool({"/search/movie": search_movie_payload()})

    result = _search(tool, "Uno", "turn-1")

    assert "turn-1" not in str(result)
