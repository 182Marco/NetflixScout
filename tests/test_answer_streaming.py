"""The final answer is ONE streamed call; its text reaches the observer as it is written."""
from __future__ import annotations

import json
from typing import Any

import pytest
import stream_support as sse
from openai.types.responses import ResponseTextDeltaEvent

from answer_stream import AnswerFieldStream
from orchestrator import LLMOrchestrator
from web_lists import final_output as make_final_output

PLAN = {"standalone_query": "q", "tool_name": "rag_search", "confidence": 0.9}
ANSWER = 'Ti consiglio "Alien" (1979).\n\nÈ un classico 🎬'


class _Tool:
    name = "rag_search"
    description = "fake"
    input_schema: dict = {}

    def run(self, *, query, params=None, conversation_history=None):
        return {"query": query, "chunks": [{"title": "Alien", "testo": "Trama di Alien"}], "metadata": {}}


class _Client:
    """The planner call answers `PLAN`; the final call returns `final` (events, a `Stream`, or raises)."""

    def __init__(self, final: Any) -> None:
        self.final = final
        self.calls: list[dict] = []
        self.responses = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not kwargs.get("stream"):
            return type("Response", (), {"output_text": json.dumps(PLAN)})()
        if isinstance(self.final, Exception):
            raise self.final
        return self.final if isinstance(self.final, sse.Stream) else sse.Stream(self.final)


class _Observer:
    def __init__(self) -> None:
        self.deltas: list[str] = []
        self.log: list[str] = []

    def step(self, step) -> None:
        self.log.append(step.kind)

    def status(self, stage) -> None:
        self.log.append(f"status:{stage}")

    def answer_delta(self, text) -> None:
        self.log.append("delta")
        self.deltas.append(text)


def _run(final: Any, *, structured: bool = False, observer: Any = None):
    client = _Client(final)
    orch = LLMOrchestrator(config={"orchestrator": {"fallback_tool": "rag_search"}}, tools=[_Tool()], client=client)
    kwargs = {"final_output": make_final_output()} if structured else {}
    decision = orch.run(query="q", conversation_history=[], observer=observer or _Observer(), **kwargs)
    return decision, client


def _json(answer: str, lists: list | None = None) -> str:
    return json.dumps({"answer": answer, "lists": lists or []}, ensure_ascii=False)


# --- plain text (terminal) ----------------------------------------------------------------------


def test_plain_answer_streams_deltas_and_makes_one_final_call() -> None:
    observer = _Observer()
    decision, client = _run(sse.text_events(ANSWER, 5), observer=observer)

    assert len(observer.deltas) > 1 and "".join(observer.deltas) == ANSWER
    assert decision["final_answer"] == ANSWER
    assert [c.get("stream") for c in client.calls] == [None, True]  # planner, then ONE streamed call
    assert "planning" not in observer.log  # a clean turn has no planning step


def test_the_answer_comes_after_the_answering_status() -> None:
    observer = _Observer()
    _run(sse.text_events("ciao ", 2), observer=observer)

    assert observer.log.index("status:answering") < observer.log.index("delta")


def test_empty_completed_answer_gets_the_no_information_text() -> None:
    observer = _Observer()
    decision, _ = _run(sse.text_events("", 1), observer=observer)

    assert decision["final_answer"] == "Non ho abbastanza informazioni per rispondere."
    assert "".join(observer.deltas) == decision["final_answer"]


# --- failures: SDK events and exceptions (plain) --------------------------------------------------


@pytest.mark.parametrize(
    "ending",
    [sse.incomplete(), sse.failed(), sse.error_event()],
    ids=["incomplete", "failed", "error-event"],
)
def test_an_abnormal_end_before_any_delta_shows_the_fallback_once(ending) -> None:
    observer = _Observer()
    decision, client = _run([ending], observer=observer)

    assert decision["final_answer"] == "Trama di Alien"  # the existing chunk fallback
    assert observer.deltas == ["Trama di Alien"]
    assert decision["planning"]["fallbacks"] == ["answer_failed"]
    assert len(client.calls) == 2  # no second final call


@pytest.mark.parametrize(
    "ending",
    [sse.incomplete(), sse.failed(), sse.error_event()],
    ids=["incomplete", "failed", "error-event"],
)
def test_an_abnormal_end_after_deltas_keeps_what_was_shown(ending) -> None:
    observer = _Observer()
    events = [sse.delta("Ti consiglio "), sse.delta("Alien"), ending]
    decision, client = _run(events, observer=observer)

    assert decision["final_answer"] == "Ti consiglio Alien"
    assert "".join(observer.deltas) == "Ti consiglio Alien"  # nothing added after the failure
    assert decision["planning"]["fallbacks"] == ["answer_failed"]
    assert len(client.calls) == 2


def test_a_dropped_connection_after_deltas_keeps_what_was_shown() -> None:
    observer = _Observer()
    stream = sse.Stream([sse.delta("Ti consiglio ")], then=ConnectionError("reset"))
    decision, _ = _run(stream, observer=observer)

    assert decision["final_answer"] == "Ti consiglio" and stream.closed
    assert decision["planning"]["fallbacks"] == ["answer_failed"]


def test_an_exception_before_the_first_delta_and_on_create_use_the_fallback() -> None:
    for final in (sse.Stream([], then=RuntimeError("down")), RuntimeError("down")):
        observer = _Observer()
        decision, _ = _run(final, observer=observer)
        assert decision["final_answer"] == "Trama di Alien" and observer.deltas == ["Trama di Alien"]


def test_a_stream_without_a_final_event_is_a_failure() -> None:
    decision, _ = _run([sse.delta("Ti consiglio")])

    assert decision["final_answer"] == "Ti consiglio"
    assert decision["planning"]["fallbacks"] == ["answer_failed"]


def test_a_refusal_is_never_shown_as_the_answer() -> None:
    observer = _Observer()
    decision, _ = _run([sse.refusal_delta("Non posso"), sse.refusal_done("Non posso"), sse.completed()], observer=observer)

    assert "Non posso" not in "".join(observer.deltas) and decision["final_answer"] == "Trama di Alien"
    assert decision["planning"]["fallbacks"] == ["answer_failed"]


def test_unknown_and_interleaved_events_are_ignored() -> None:
    other = sse.refusal_delta("x").model_copy(update={"type": "response.created"})
    events = [other, sse.delta("ciao"), other, sse.text_done("zzz"), sse.completed()]
    decision, _ = _run(events)

    assert decision["final_answer"] == "ciao"  # the accumulated deltas win over output_text.done


def test_the_answer_failure_step_comes_after_the_text_and_only_it() -> None:
    steps = []

    class _Keep(_Observer):
        def step(self, step) -> None:
            steps.append(step)
            super().step(step)

    keep = _Keep()
    _run([sse.delta("Ti"), sse.incomplete()], observer=keep)

    assert steps[-1].kind == "planning" and steps[-1].data["fallbacks"] == ["answer_failed"]
    assert steps[-1].data["pending"] == [] and keep.log.index("delta") < keep.log.index("planning")


# --- structured output (web) ----------------------------------------------------------------------


def test_structured_answer_streams_only_the_decoded_answer_text() -> None:
    observer = _Observer()
    lists = [{"list_id": "a", "title": "A", "kind": "movies", "items": []}]
    decision, client = _run(sse.text_events(_json(ANSWER, lists), 6), structured=True, observer=observer)

    assert "".join(observer.deltas) == ANSWER
    assert all(not {"{", "\\", '"lists"'} & set(d) for d in observer.deltas)
    assert decision["final_answer"] == ANSWER and decision["final_lists"] == lists
    assert [c.get("stream") for c in client.calls] == [None, True]
    assert client.calls[1]["text"]["format"]["strict"] is True


@pytest.mark.parametrize("size", [1, 2, 3, 5, 11])
def test_structured_deltas_match_the_final_answer_for_any_chunking(size: int) -> None:
    observer = _Observer()
    text = json.dumps({"answer": ANSWER, "lists": []})  # ASCII: \u escapes and a surrogate pair
    decision, _ = _run(sse.text_events(text, size), structured=True, observer=observer)

    assert "".join(observer.deltas) == ANSWER == decision["final_answer"]
    assert not any("�" in d for d in observer.deltas)


def test_structured_json_truncated_after_some_text_keeps_the_text_and_no_lists() -> None:
    observer = _Observer()
    events = [sse.delta('{"answer": "Ti consi'), sse.delta('glio Alien'), sse.incomplete()]
    decision, _ = _run(events, structured=True, observer=observer)

    assert decision["final_answer"] == "Ti consiglio Alien" and decision["final_lists"] == []
    assert "".join(observer.deltas) == "Ti consiglio Alien"
    assert decision["planning"]["fallbacks"] == ["answer_failed"]


def test_structured_malformed_json_after_text_keeps_the_text_and_never_repairs() -> None:
    observer = _Observer()
    events = [sse.delta('{"answer": "Ciao \\q mondo"'), sse.completed()]
    decision, _ = _run(events, structured=True, observer=observer)

    assert decision["final_answer"] == "Ciao" and "".join(observer.deltas) == "Ciao "
    assert decision["final_lists"] == [] and decision["planning"]["fallbacks"] == ["answer_failed"]


def test_structured_json_without_an_answer_after_completion_is_a_fallback() -> None:
    observer = _Observer()
    decision, _ = _run(sse.text_events('{"lists": []}', 4), structured=True, observer=observer)

    assert decision["final_answer"] == "Trama di Alien" and decision["final_lists"] == []
    assert "".join(observer.deltas) == "Trama di Alien"


def test_structured_refusal_shows_the_fallback() -> None:
    observer = _Observer()
    decision, _ = _run([sse.refusal_delta("No"), sse.completed()], structured=True, observer=observer)

    assert decision["final_answer"] == "Trama di Alien" and decision["final_lists"] == []


def test_valid_json_wins_over_a_decoder_that_stopped_early() -> None:
    """Defence: the authoritative parse at the end is the answer, whatever was streamed."""
    observer = _Observer()
    events = sse.text_events(_json("  Risposta intera  "), 4)
    decision, _ = _run(events, structured=True, observer=observer)

    assert decision["final_answer"] == "Risposta intera"
    assert "".join(observer.deltas).strip() == "Risposta intera"


# --- the other ways an answer reaches the observer ------------------------------------------------------


def test_a_clarification_question_arrives_as_a_delta() -> None:
    observer = _Observer()
    plan = {"needs_clarification": True, "clarification_question": "Di quale film parli?", "confidence": 0.9}
    client = _Client([])
    client.create = lambda **kw: type("Response", (), {"output_text": json.dumps(plan)})()  # type: ignore[method-assign]
    orch = LLMOrchestrator(config={"orchestrator": {"fallback_tool": "rag_search"}}, tools=[_Tool()], client=client)

    decision = orch.run(query="quel film", conversation_history=[], observer=observer)

    assert observer.deltas == ["Di quale film parli?"] == [decision["final_answer"]]


def test_an_observer_without_answer_delta_or_that_raises_does_not_break_the_turn() -> None:
    class _NoDelta:
        def step(self, step) -> None: ...
        def status(self, stage) -> None: ...

    class _Raises(_NoDelta):
        def answer_delta(self, text) -> None:
            raise RuntimeError("broken channel")

    for observer in (_NoDelta(), _Raises()):
        decision, _ = _run(sse.text_events(ANSWER, 5), observer=observer)
        assert decision["final_answer"] == ANSWER


# --- contract with the pinned SDK ---------------------------------------------------------------------


def test_the_event_types_the_orchestrator_reads_exist_in_the_sdk() -> None:
    for event_type, cls in sse.HANDLED_EVENT_CLASSES.items():
        assert cls.model_fields["type"].annotation.__args__ == (event_type,)


def test_the_helper_events_are_validated_sdk_objects() -> None:
    event = sse.delta("x")
    assert isinstance(event, ResponseTextDeltaEvent) and event.type == "response.output_text.delta"


def test_the_strict_schema_asks_for_the_answer_first() -> None:
    schema = make_final_output()["text_format"]["schema"]
    assert list(schema["properties"])[0] == "answer" and make_final_output()["answer_field"] == "answer"
    assert isinstance(AnswerFieldStream("answer"), AnswerFieldStream)


# --- planning comes before the answer, the answer failure after ------------------------------------------


def test_planning_lines_come_before_the_text_when_the_turn_went_on_with_less_than_planned() -> None:
    class _BadPlanner(_Client):
        def create(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("stream"):
                return sse.Stream(sse.text_events("Risposta.", 4))
            return type("Response", (), {"output_text": "not json"})()  # planner_failed fallback

    observer = _Observer()
    orch = LLMOrchestrator(config={"orchestrator": {"fallback_tool": "rag_search"}}, tools=[_Tool()], client=_BadPlanner([]))
    orch.run(query="q", conversation_history=[], observer=observer)

    assert observer.log.count("planning") == 1
    assert observer.log.index("planning") < observer.log.index("status:answering") < observer.log.index("delta")
