"""Fakes of the web_api tests: a bot whose orchestrator streams like the real one, an SSE parser."""
from __future__ import annotations

import json
import threading
from typing import Any

from fastapi.testclient import TestClient

import app as app_module
from turn_support import stream_decision
from web_api import create_app
from web_api.settings import WebApiSettings
from web_lists_support import ANSWER, MOVIE_REF, TMDB_STEP, TV_REF, YOUTUBE_STEP, raw_list


class FakeOrchestrator:
    """Streams steps and the answer in pieces, like `LLMOrchestrator.run`.

    `gate`: after the first piece of the answer the turn waits for `gate.set()`, so a test can act
    while it is running. `error`: raised before anything is streamed.
    """

    def __init__(
        self,
        answer: str = ANSWER,
        *,
        refs: list[Any] | None = None,
        piece: int = 11,
        gate: threading.Event | None = None,
        error: Exception | None = None,
    ) -> None:
        self.answer = answer
        self.refs = [raw_list(MOVIE_REF, TV_REF)] if refs is None else refs
        self.piece = piece
        self.gate = gate
        self.error = error
        self.calls: list[dict[str, Any]] = []
        self.started = threading.Event()

    def run(
        self, *, query, conversation_history=None, tool_overrides=None, observer=None, final_output=None, prompt_parts=None, answer_language=None
    ):
        self.calls.append(
            {
                "query": query,
                "history": list(conversation_history or []),
                "final_output": final_output,
                "prompt_parts": prompt_parts,
            }
        )
        self.started.set()
        if self.error:
            raise self.error
        trace = [step.model_dump() for step in (TMDB_STEP, YOUTUBE_STEP)]
        decision = {
            "tool": "tmdb_search",
            "tools": ["tmdb_search"],
            "calls": [{"tool": "tmdb_search", "arguments": {}, "result": {"trace": trace}}],
            "standalone_query": query,
            "result": {"trace": trace},
            "final_answer": self.answer,
            "final_lists": self.refs if final_output else [],
        }
        stream_decision(observer, query, {**decision, "final_answer": ""})
        pieces = [self.answer[i : i + self.piece] for i in range(0, len(self.answer), self.piece)]
        for number, text in enumerate(pieces):
            observer.answer_delta(text)
            if number == 0 and self.gate is not None:
                assert self.gate.wait(10), "the test never opened the gate"
        return decision


def bot_app(orchestrator: FakeOrchestrator) -> dict[str, Any]:
    return {"config": app_module.build_runtime_config(), "orchestrator": orchestrator}


def make_client(orchestrator: FakeOrchestrator, **settings: Any) -> TestClient:
    """A client of the real web_api app on a fake bot. Use it as a context manager (lifespan)."""
    app = create_app(WebApiSettings(**settings), bot_app(orchestrator), client=object())  # type: ignore[arg-type]
    return TestClient(app)


def parse_sse(text: str) -> list[tuple[int, str, dict[str, Any]]]:
    """`[(id, event, data)]` of a stream body; comment lines (heartbeats) are skipped."""
    events = []
    for block in text.split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line and not line.startswith(":"))
        if "event" in fields:
            events.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return events


def names(events: list[tuple[int, str, dict[str, Any]]]) -> list[str]:
    return [name for _, name, _ in events]


def streamed_text(events: list[tuple[int, str, dict[str, Any]]]) -> str:
    return "".join(data["text"] for _, name, data in events if name == "answer_delta")
