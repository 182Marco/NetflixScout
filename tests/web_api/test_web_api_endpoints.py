"""The HTTP contract, end to end on a fake bot (the real `handle_query`, no API call)."""
from __future__ import annotations

import app as app_module
import pytest
from web_api_support import FakeOrchestrator, make_client, names, parse_sse, streamed_text
from web_lists_support import ANSWER


@pytest.fixture(autouse=True)
def cinema(monkeypatch):
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})


def _open(client) -> str:
    response = client.post("/conversations")
    assert response.status_code == 201
    return response.json()["conversation_id"]


def _send(client, conversation_id: str, content: str = "film di Nolan") -> list:
    response = client.post(f"/conversations/{conversation_id}/messages", json={"content": content})
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    return parse_sse(response.text)


def test_health_and_a_new_conversation() -> None:
    with make_client(FakeOrchestrator()) as client:
        assert client.get("/health").json() == {"status": "ok"}
        created = client.post("/conversations").json()
        info = client.get(f"/conversations/{created['conversation_id']}").json()

    assert info == {"conversation_id": created["conversation_id"], "busy": False, "turns_completed": 0}


def test_a_turn_streams_progress_then_the_text_then_the_lists() -> None:
    with make_client(FakeOrchestrator()) as client:
        events = _send(client, _open(client))

    ids = [event_id for event_id, _, _ in events]
    assert ids == list(range(1, len(events) + 1))
    order = names(events)
    assert order[0] == "turn_start" and order[-3:] == ["answer_end", "lists", "done"]
    first_delta = order.index("answer_delta")
    assert {"story", "step"} <= set(order[:first_delta])  # progress first
    assert set(order[first_delta:-3]) <= {"answer_delta", "story"}
    assert order.count("answer_delta") > 1 and streamed_text(events).strip() == ANSWER.strip()


def test_the_closing_events_carry_the_metadata_and_the_structured_lists() -> None:
    with make_client(FakeOrchestrator()) as client:
        events = _send(client, _open(client))

    end = next(data for _, name, data in events if name == "answer_end")
    lists = next(data for _, name, data in events if name == "lists")["lists"]
    assert end == {"blocked": False, "language": "it", "tool": "tmdb_search", "tools": ["tmdb_search"],
                   "history_compacted": False, "replace": None}
    assert [item["id"] for item in lists[0]["items"]] == [157336, 1396]
    assert "answer" not in str(lists)  # the text is not repeated in the lists


def test_steps_are_the_serialised_tool_steps_and_never_flow_steps() -> None:
    with make_client(FakeOrchestrator()) as client:
        events = _send(client, _open(client))

    kinds = [data["kind"] for _, name, data in events if name == "step"]
    assert kinds == ["tmdb_calls", "youtube_calls"]


def test_the_web_call_asks_for_lists_and_the_history_grows_between_messages() -> None:
    orchestrator = FakeOrchestrator("Prima.")
    with make_client(orchestrator) as client:
        conversation_id = _open(client)
        _send(client, conversation_id, "uno")
        _send(client, conversation_id, "due")
        info = client.get(f"/conversations/{conversation_id}").json()

    assert orchestrator.calls[0]["history"] == []
    assert orchestrator.calls[1]["history"] == [
        {"role": "user", "content": "uno"}, {"role": "assistant", "content": "Prima."},
    ]
    assert all(call["final_output"]["answer_field"] == "answer" for call in orchestrator.calls)
    assert info["turns_completed"] == 2 and info["busy"] is False


def test_conversations_do_not_share_history() -> None:
    orchestrator = FakeOrchestrator("Ok.")
    with make_client(orchestrator) as client:
        first, second = _open(client), _open(client)
        _send(client, first, "solo nella prima")
        _send(client, second, "nella seconda")

    assert orchestrator.calls[1]["history"] == []


def test_a_blocked_message_streams_one_delta_and_empty_lists(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": False, "language": "it"})
    with make_client(FakeOrchestrator()) as client:
        events = _send(client, _open(client), "chi vince le elezioni?")

    assert names(events)[-4:] == ["answer_delta", "answer_end", "lists", "done"]
    by_name = {name: data for _, name, data in events}
    assert by_name["lists"] == {"lists": []} and by_name["answer_end"]["blocked"] is True
    assert by_name["answer_end"]["replace"] is None


def test_an_error_before_the_answer_streams_error_and_keeps_the_history() -> None:
    orchestrator = FakeOrchestrator(error=RuntimeError("secret internal detail"))
    with make_client(orchestrator) as client:
        conversation_id = _open(client)
        events = _send(client, conversation_id)
        info = client.get(f"/conversations/{conversation_id}").json()

    assert names(events)[0] == "turn_start" and names(events)[-1] == "error"
    assert not {"answer_delta", "answer_end", "lists", "done"} & set(names(events))
    assert events[-1][2] == {"code": "turn_failed", "message": "The turn failed; try again."}
    assert "secret" not in str(events)
    assert info == {"conversation_id": conversation_id, "busy": False, "turns_completed": 0}


def test_a_failed_turn_can_be_sent_again() -> None:
    orchestrator = FakeOrchestrator(error=RuntimeError("x"))
    with make_client(orchestrator) as client:
        conversation_id = _open(client)
        _send(client, conversation_id)
        orchestrator.error = None
        events = _send(client, conversation_id)

    assert names(events)[-1] == "done" and orchestrator.calls[1]["history"] == []


def test_a_failing_compaction_still_commits_the_whole_turn(monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(app_module, "_compact_history", boom)
    orchestrator = FakeOrchestrator("Ok.")
    with make_client(orchestrator) as client:
        conversation_id = _open(client)
        for number in range(7):  # 14 messages: over the memory window
            events = _send(client, conversation_id, f"m{number}")
        info = client.get(f"/conversations/{conversation_id}").json()

    assert names(events)[-1] == "done" and info["turns_completed"] == 7
    assert len(orchestrator.calls[-1]["history"]) == 12


def test_compaction_is_reported_in_answer_end(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "_compact_history", lambda history, runtime, client: history[-2:])
    orchestrator = FakeOrchestrator("Ok.")
    with make_client(orchestrator) as client:
        conversation_id = _open(client)
        for number in range(6):
            events = _send(client, conversation_id, f"m{number}")

    assert next(d for _, n, d in events if n == "answer_end")["history_compacted"] is True


def test_http_errors_use_one_shape() -> None:
    with make_client(FakeOrchestrator(), max_message_chars=5) as client:
        conversation_id = _open(client)
        missing = client.post("/conversations/nope/messages", json={"content": "x"})
        blank = client.post(f"/conversations/{conversation_id}/messages", json={"content": "  "})
        extra = client.post(f"/conversations/{conversation_id}/messages", json={"content": "x", "a": 1})
        long = client.post(f"/conversations/{conversation_id}/messages", json={"content": "x" * 6})
        gone = client.get("/conversations/nope")
        deleted = client.delete(f"/conversations/{conversation_id}")

    assert (missing.status_code, missing.json()["error"]["code"]) == (404, "conversation_not_found")
    assert (blank.status_code, blank.json()["error"]["code"]) == (422, "invalid_request")
    assert extra.status_code == 422
    assert (long.status_code, long.json()["error"]["code"]) == (422, "message_too_long")
    assert gone.status_code == 404 and deleted.status_code == 204


def test_cors_allows_only_the_configured_origins() -> None:
    with make_client(FakeOrchestrator(), cors_origins=("http://localhost:5173",)) as client:
        allowed = client.options(
            "/conversations", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST"}
        )
        denied = client.options(
            "/conversations", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"}
        )

    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "access-control-allow-origin" not in denied.headers


def test_a_second_message_gets_409_while_the_first_runs_and_a_closed_stream_still_commits() -> None:
    import threading
    import time

    gate = threading.Event()
    orchestrator = FakeOrchestrator("Una risposta lunga abbastanza.", gate=gate)
    with make_client(orchestrator) as client:
        conversation_id = _open(client)
        url = f"/conversations/{conversation_id}/messages"
        with client.stream("POST", url, json={"content": "uno"}) as response:
            for line in response.iter_lines():
                if line == "event: answer_delta":
                    break
            busy = client.post(url, json={"content": "due"})
            assert client.get(f"/conversations/{conversation_id}").json()["busy"] is True
        # The stream is closed here; the turn is still running.
        gate.set()
        for _ in range(100):
            info = client.get(f"/conversations/{conversation_id}").json()
            if not info["busy"]:
                break
            time.sleep(0.05)

    assert busy.status_code == 409 and busy.json()["error"]["code"] == "turn_in_progress"
    assert info == {"conversation_id": conversation_id, "busy": False, "turns_completed": 1}
    assert len(orchestrator.calls) == 1


# --- the HTTP calls of the tools in the stream ---------------------------------------------------------------


def _steps_of(tool_run) -> list:
    from turn import TraceStep

    result, sent, secret = tool_run()
    return [TraceStep(**step) for step in result["trace"]], sent, secret


def test_every_http_call_of_every_tool_reaches_the_client_in_order_with_the_key_masked() -> None:
    import test_http_call_trace as calls

    from turn import mask_url

    builders = {"tmdb_calls": calls._tmdb, "youtube_calls": calls._youtube, "wikipedia_calls": calls._wikipedia, "omdb_calls": calls._omdb, "tvmaze_calls": calls._tvmaze}
    for kind, build in builders.items():
        steps, sent, secret = _steps_of(build)
        with make_client(FakeOrchestrator(steps=steps)) as client:
            response = client.post(f"/conversations/{_open(client)}/messages", json={"content": "q"})
        events = parse_sse(response.text)
        tool_steps = [data for _, name, data in events if name == "step" and data["kind"] == kind]

        assert len(tool_steps) == 1, kind
        received = tool_steps[0]["calls"]
        assert [(c["method"], c["url"]) for c in received] == [("GET", mask_url(url, [secret])) for url in sent], kind
        assert len(received) >= 2  # several calls in the same turn: none is lost
        assert not secret or secret not in response.text, kind


def test_a_tool_step_with_credentials_in_any_url_format_never_leaks_them_to_the_client() -> None:
    from turn import TraceStep

    leaky = TraceStep(
        kind="omdb_calls",
        title="OMDb",
        data={
            "calls": [
                {"method": "GET", "url": "https://h.test/?i=tt1&apikey=LEAK1"},
                {"method": "GET", "url": "https://h.test/?API_KEY=LEAK2&x=1&key=LEAK3"},
                {"method": "GET", "url": "https://user:LEAK4@h.test/p?access_token=LEAK5#frag"},
                "https://h.test/plain?token=LEAK6",
            ],
            "status": "ok",
        },
    )
    with make_client(FakeOrchestrator(steps=[leaky])) as client:
        response = client.post(f"/conversations/{_open(client)}/messages", json={"content": "q"})

    step = next(data for _, name, data in parse_sse(response.text) if name == "step")
    assert "LEAK" not in response.text
    assert [c["url"] for c in step["calls"]] == [
        "https://h.test/?i=tt1&apikey=***",
        "https://h.test/?API_KEY=***&x=1&key=***",
        "https://***@h.test/p?access_token=***#frag",
        "https://h.test/plain?token=***",
    ]


# --- a question the classifier says is not about cinema ---------------------------------------------------------


def test_a_blocked_turn_sends_only_the_events_the_chat_needs_and_runs_no_tool(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": False, "language": "it"})
    orchestrator = FakeOrchestrator()
    with make_client(orchestrator) as client:
        conversation = _open(client)
        events = _send(client, conversation, "chi vince le elezioni?")
        info = client.get(f"/conversations/{conversation}").json()

    assert names(events) == ["turn_start", "answer_delta", "answer_end", "lists", "done"]
    assert orchestrator.calls == []  # no planner, no tool, no HTTP call
    by_name = {name: data for _, name, data in events}
    assert by_name["answer_delta"]["text"] == "Non rispondo a domande non cinematografiche"
    assert by_name["answer_end"] == {"blocked": True, "language": "it", "tool": None, "tools": [],
                                     "history_compacted": False, "replace": None}
    assert by_name["lists"] == {"lists": []}
    assert "step" not in names(events) and "story" not in names(events) and "status" not in names(events)
    assert info["turns_completed"] == 1


def test_a_blocked_turn_leaves_the_history_alone_and_the_next_cinema_turn_is_normal(monkeypatch) -> None:
    verdicts = iter([False, True])
    monkeypatch.setattr(
        app_module,
        "classify_query_domain",
        lambda q, history=None: {"is_cinema": next(verdicts), "language": "it"},
    )
    orchestrator = FakeOrchestrator()
    with make_client(orchestrator) as client:
        conversation = _open(client)
        blocked = _send(client, conversation, "chi vince le elezioni?")
        normal = _send(client, conversation, "film di Nolan")

    assert "step" not in names(blocked)
    assert {"status", "story", "step"} <= set(names(normal))  # cinema turns keep their whole progress
    assert [call["history"] for call in orchestrator.calls] == [[]]  # the refusal is not in the history
