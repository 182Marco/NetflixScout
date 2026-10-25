"""The turn belongs to the server: disconnections, the busy state and the single commit."""
from __future__ import annotations

import asyncio
import threading

import app as app_module
import pytest
from web_api_support import FakeOrchestrator, bot_app

from web_api.conversations.store import ConversationStore, TurnInProgress, begin_turn, create_conversation
from web_api.schemas.events import END, SseEvent
from web_api.streaming import runner


@pytest.fixture(autouse=True)
def cinema(monkeypatch):
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "is_italian": True})


def _setup(orchestrator: FakeOrchestrator):
    store = ConversationStore(ttl_seconds=3600, max_conversations=10)
    conv = create_conversation(store, 0.0, "t")
    return store, conv, bot_app(orchestrator)


async def _read_until(gen, marker: str) -> list[str]:
    seen: list[str] = []
    async for text in gen:
        seen.append(text)
        if marker in text:
            break
    return seen


def test_the_turn_survives_a_client_that_leaves_and_commits_its_history() -> None:
    gate = threading.Event()
    orchestrator = FakeOrchestrator("Una risposta abbastanza lunga.", gate=gate)
    store, conv, app = _setup(orchestrator)

    async def scenario() -> None:
        sub = runner.launch_turn(store, conv, "domanda", app, object())  # type: ignore[arg-type]
        (task,) = store.tasks
        generator = runner.stream_events(sub, 5)
        await _read_until(generator, "event: answer_delta")
        await generator.aclose()  # the client closes the stream

        assert sub.closed and sub.queue.empty()
        assert conv.busy  # the work is not over
        with pytest.raises(TurnInProgress):
            begin_turn(conv, 1.0)

        gate.set()
        await task
        # Nothing piled up for the gone client, and the work finished and committed.
        assert sub.queue.empty() and not conv.busy and not store.tasks
        assert conv.turns_completed == 1
        assert conv.history == [
            {"role": "user", "content": "domanda"},
            {"role": "assistant", "content": "Una risposta abbastanza lunga."},
        ]

    asyncio.run(scenario())


def test_a_client_that_never_reads_does_not_stop_the_commit() -> None:
    orchestrator = FakeOrchestrator("Ok.")
    store, conv, app = _setup(orchestrator)

    async def scenario() -> None:
        sub = runner.launch_turn(store, conv, "q", app, object())  # type: ignore[arg-type]
        runner.close_subscription(sub)  # never connected
        await asyncio.gather(*store.tasks)
        assert conv.turns_completed == 1 and not conv.busy and sub.queue.empty()

    asyncio.run(scenario())


def test_the_queue_does_not_grow_after_the_subscription_is_closed() -> None:
    async def scenario() -> None:
        sub = runner.Subscription()
        runner.deliver(sub, "status", {"stage": "x"})
        runner.close_subscription(sub)
        for number in range(10_000):
            runner.deliver(sub, "answer_delta", {"text": str(number)})
        runner.deliver_end(sub)
        assert sub.queue.qsize() == 0

    asyncio.run(scenario())


def test_the_worker_does_not_even_schedule_work_for_a_closed_subscription() -> None:
    class _Loop:
        scheduled = 0

        def call_soon_threadsafe(self, *args) -> None:
            self.scheduled += 1

    async def scenario() -> None:
        sub, streamed, loop = runner.Subscription(), [], _Loop()
        emit = runner.thread_emitter(loop, sub, streamed)  # type: ignore[arg-type]
        emit("answer_delta", {"text": "a"})
        runner.close_subscription(sub)
        emit("answer_delta", {"text": "b"})
        assert loop.scheduled == 1 and streamed == ["a", "b"]  # the text is still collected for `replace`

    asyncio.run(scenario())


def test_an_error_commits_nothing_and_frees_the_conversation() -> None:
    store, conv, app = _setup(FakeOrchestrator(error=RuntimeError("down")))

    async def scenario() -> list[str]:
        sub = runner.launch_turn(store, conv, "q", app, object())  # type: ignore[arg-type]
        texts = [text async for text in runner.stream_events(sub, 5)]
        await asyncio.gather(*list(store.tasks) or [asyncio.sleep(0)])
        return texts

    texts = asyncio.run(scenario())
    assert "event: error" in texts[-1] and not conv.busy and conv.history == [] and conv.turns_completed == 0


def test_the_turn_is_committed_exactly_once(monkeypatch) -> None:
    commits = []
    real = runner.finish_turn
    monkeypatch.setattr(runner, "finish_turn", lambda conv, history, now: (commits.append(history), real(conv, history, now)))
    store, conv, app = _setup(FakeOrchestrator("Ok."))

    async def scenario() -> None:
        sub = runner.launch_turn(store, conv, "q", app, object())  # type: ignore[arg-type]
        _ = [text async for text in runner.stream_events(sub, 5)]
        await asyncio.gather(*list(store.tasks) or [asyncio.sleep(0)])

    asyncio.run(scenario())
    assert len(commits) == 1 and commits[0] is not None


def test_a_second_message_during_a_turn_is_refused_and_the_first_is_untouched() -> None:
    gate = threading.Event()
    store, conv, app = _setup(FakeOrchestrator("Ok.", gate=gate))

    async def scenario() -> None:
        sub = runner.launch_turn(store, conv, "uno", app, object())  # type: ignore[arg-type]
        with pytest.raises(TurnInProgress):
            runner.launch_turn(store, conv, "due", app, object())  # type: ignore[arg-type]
        gate.set()
        _ = [text async for text in runner.stream_events(sub, 5)]
        await asyncio.gather(*list(store.tasks) or [asyncio.sleep(0)])

    asyncio.run(scenario())
    assert conv.history[0] == {"role": "user", "content": "uno"} and conv.turns_completed == 1


def test_queue_items_are_events_or_the_end() -> None:
    async def scenario() -> None:
        sub = runner.Subscription()
        runner.deliver(sub, "done", {})
        runner.deliver_end(sub)
        assert isinstance(sub.queue.get_nowait(), SseEvent) and sub.queue.get_nowait() is END

    asyncio.run(scenario())
