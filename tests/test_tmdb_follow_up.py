"""When TMDb finds nothing for a request, the tool offers the planner another step (`turn.RESULT_FOLLOW_UP`)
instead of the turn ending on the failure; when it found what was asked, nothing is added."""
from __future__ import annotations

from tmdb_support import MOVIE_ID, make_tool, movie_payload, run

from turn import RESULT_FOLLOW_UP


def test_a_request_that_is_not_found_offers_the_planner_to_look_elsewhere() -> None:
    tool, _ = make_tool({})

    result = run(tool, {"operation": "movie_details", "tmdb_id": 404})

    assert result["outcome"] == {"status": "error", "reason": "not_found"}
    follow_up = result[RESULT_FOLLOW_UP]
    assert follow_up["available"] is True and follow_up["reasons"] == ["not_found"]
    assert "movie_details" in follow_up["summary"] and "(not_found)" in follow_up["summary"]
    assert "trilogia" in follow_up["summary"] and "ritorna done" in follow_up["summary"]


def test_a_collection_that_does_not_exist_is_the_trilogy_case() -> None:
    tool, _ = make_tool({"/search/collection": {"results": [], "total_results": 0}})

    result = run(tool, {"operation": "collection_details", "name": "Vengeance Trilogy"})

    assert result["outcome"]["status"] == "error"
    assert result[RESULT_FOLLOW_UP]["available"] and "«Vengeance Trilogy»" in result[RESULT_FOLLOW_UP]["summary"]


def test_a_partial_result_keeps_its_data_and_still_offers_the_missing_part() -> None:
    tool, _ = make_tool({f"/movie/{MOVIE_ID}": movie_payload()})

    result = run(tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID}, {"operation": "movie_details", "tmdb_id": 404})

    assert len(result["chunks"]) == 1
    follow_up = result[RESULT_FOLLOW_UP]
    assert follow_up["reasons"] == ["not_found"] and "Richieste risolte: 1" in follow_up["summary"]


def test_a_successful_run_has_no_follow_up_and_an_unrelated_error_has_none_either() -> None:
    ok_tool, _ = make_tool({f"/movie/{MOVIE_ID}": movie_payload()})
    down_tool, _ = make_tool({"/movie/1": (503, {}, {})})

    ok = run(ok_tool, {"operation": "movie_details", "tmdb_id": MOVIE_ID})
    down = run(down_tool, {"operation": "movie_details", "tmdb_id": 1})

    assert RESULT_FOLLOW_UP not in ok
    assert down["outcome"]["status"] == "error" and RESULT_FOLLOW_UP not in down  # nothing elsewhere would fix a 503


def test_the_orchestrator_asks_the_planner_and_a_second_tool_can_answer() -> None:
    import json

    from orchestrator import LLMOrchestrator
    from stream_support import reply

    class Client:
        def __init__(self) -> None:
            self.texts = [
                json.dumps({"standalone_query": "q", "tool_name": "tmdb_search", "confidence": 0.9, "arguments": {"requests": [{"operation": "movie_details", "tmdb_id": 404}]}}),
                json.dumps({"tool_name": "other_tool", "confidence": 0.9, "arguments": {}}),
                '{"done": true}',
                "ok",
            ]
            self.calls: list[dict] = []
            self.responses = self

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return reply(self.texts.pop(0), kwargs)

    class Other:
        name, description, input_schema = "other_tool", "x", {}
        ran = 0

        def run(self, *, query, params=None, conversation_history=None):
            Other.ran += 1
            return {"query": query, "chunks": [], "metadata": {}}

    tmdb, _ = make_tool({})
    client = Client()
    orch = LLMOrchestrator(config={"orchestrator": {"fallback_tool": "tmdb_search"}}, tools=[tmdb, Other()], client=client)

    decision = orch.run(query="la trilogia", conversation_history=[])

    assert decision["tools"] == ["tmdb_search", "other_tool"] and Other.ran == 1
    second_plan = client.calls[1]["input"][-1]["content"]
    assert "può dare altro (not_found)" in second_plan and "TMDb non ha trovato dati per" in second_plan
