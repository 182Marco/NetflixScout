"""How the streamed answer reaches each channel: terminal printing, web events, `handle_query`."""
from __future__ import annotations

import app as app_module
from presenters import OutputChannel, present
from presenters.terminal import TerminalObserver
from presenters.web import WebObserver, to_payload
from presenters.web.observer import EVENT_ANSWER_DELTA, EVENT_STATUS, EVENT_STEP, EVENT_STORY
from test_presenter_parity import STEPS
from turn import STAGE_ANSWERING, TraceStep, TurnResult
from turn_support import stream_decision


def _turn(answer: str = "Risposta.", **kwargs) -> TurnResult:
    return TurnResult(query="q", language="it", blocked=False, answer=answer, steps=STEPS, **kwargs)


# --- terminal -------------------------------------------------------------------------------------------


def test_the_terminal_prints_the_header_once_and_the_deltas_in_order(capsys) -> None:
    observer = TerminalObserver()
    for piece in ("Ti ", "consiglio ", "Alien."):
        observer.answer_delta(piece)
    out = capsys.readouterr().out

    assert out.count("RISPOSTA FINALE") == 1 and out.endswith("\nTi consiglio Alien.")


def test_leading_blank_text_is_not_printed(capsys) -> None:
    observer = TerminalObserver()
    observer.answer_delta("\n ")
    assert capsys.readouterr().out == ""  # nothing yet: no header for an empty answer start

    observer.answer_delta("\n Ciao ")
    observer.answer_delta(" mondo")
    out = capsys.readouterr().out
    assert out.endswith("\nCiao  mondo") and out.count("RISPOSTA FINALE") == 1


def test_a_streamed_turn_ends_without_printing_the_answer_again(capsys) -> None:
    present(_turn(history_compacted=True), OutputChannel.terminal, streamed=True)
    out = capsys.readouterr().out

    assert "Risposta." not in out and "RISPOSTA FINALE" not in out and "history compattata" in out


def test_the_replay_of_a_finished_turn_is_unchanged(capsys) -> None:
    present(_turn(), OutputChannel.terminal)
    out = capsys.readouterr().out

    assert out.count("RISPOSTA FINALE") == 1 and "Risposta." in out


# --- web ----------------------------------------------------------------------------------------------


def _record() -> tuple[WebObserver, list[tuple[str, dict]]]:
    events: list[tuple[str, dict]] = []
    return WebObserver(lambda name, data: events.append((name, data))), events


def test_the_web_observer_sends_the_same_story_and_steps_as_the_payload() -> None:
    observer, events = _record()
    for step in STEPS:
        observer.step(step)
    payload = to_payload(_turn())

    assert [d for n, d in events if n == EVENT_STORY] == payload["story"]
    assert [d for n, d in events if n == EVENT_STEP] == payload["steps"]


def test_the_web_observer_sends_status_with_its_story_line_and_the_deltas() -> None:
    observer, events = _record()
    observer.status(STAGE_ANSWERING)
    observer.answer_delta("Ciao")
    observer.answer_delta("")

    assert events[0] == (EVENT_STATUS, {"stage": STAGE_ANSWERING})
    assert events[1][0] == EVENT_STORY and events[1][1]["level"] == "progress"
    assert events[2:] == [(EVENT_ANSWER_DELTA, {"text": "Ciao"})]


def test_the_web_observer_learns_the_language_from_the_classification() -> None:
    observer, events = _record()
    observer.step(TraceStep(kind="classification", title="c", data={"language": "en"}))
    observer.status(STAGE_ANSWERING)

    english = events[1][1]["text"]
    other, other_events = _record()
    other.status(STAGE_ANSWERING)
    assert english != other_events[1][1]["text"]


# --- handle_query ---------------------------------------------------------------------------------------


class _Orchestrator:
    def run(self, *, query, conversation_history=None, tool_overrides=None, observer=None, final_output=None):
        decision = {
            "tool": "rag_search", "tools": ["rag_search"], "standalone_query": query,
            "calls": [{"tool": "rag_search", "arguments": {}, "result": {"trace": []}}],
            "result": {"trace": []}, "final_answer": "Ecco.",
        }
        stream_decision(observer, query, decision)
        return decision


def _app(**orchestrator) -> dict:
    return {"config": app_module.build_runtime_config(), "orchestrator": _Orchestrator()}


class _Deltas:
    def __init__(self) -> None:
        self.deltas: list[str] = []

    def step(self, step) -> None: ...
    def status(self, stage) -> None: ...

    def answer_delta(self, text) -> None:
        self.deltas.append(text)


def test_a_blocked_turn_delivers_its_message_as_a_delta(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": False, "is_italian": False})
    observer = _Deltas()

    turn = app_module.handle_query(_app(), "Who won the election?", history=[], observer=observer)

    assert turn.blocked and observer.deltas == [turn.answer] and turn.history == []


def test_a_failing_compaction_keeps_the_whole_history(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "is_italian": True})

    def boom(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(app_module, "_compact_history", boom)
    history = [{"role": "user", "content": f"m{i}"} for i in range(20)]

    turn = app_module.handle_query(_app(), "ciao", history=history, openai_client=object())

    assert turn.answer == "Ecco." and not turn.history_compacted
    assert turn.history == [*history, {"role": "user", "content": "ciao"}, {"role": "assistant", "content": "Ecco."}]
    assert len(history) == 20  # the caller's list is not touched


def test_the_answer_of_a_real_turn_is_delivered_through_the_observer(monkeypatch) -> None:
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "is_italian": True})
    observer = _Deltas()

    turn = app_module.handle_query(_app(), "ciao", history=[], observer=observer)

    assert "".join(observer.deltas) == turn.answer
