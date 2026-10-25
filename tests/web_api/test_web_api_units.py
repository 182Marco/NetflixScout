"""web_api modules in isolation: wire format, store, settings, closing events."""
from __future__ import annotations

import asyncio

import pytest
from web_lists_support import ANSWER, make_turn

from turn import TurnResult
from web_api.conversations.store import (
    ConversationNotFound,
    ConversationStore,
    TurnInProgress,
    begin_turn,
    create_conversation,
    delete_conversation,
    evict,
    finish_turn,
    get_conversation,
)
from web_api.schemas.events import END, EVENT_MODELS, SseEvent
from web_api.settings import DEFAULT_CORS_ORIGINS, load_settings
from web_api.streaming.events import final_events, replacement
from web_api.streaming.sse import HEARTBEAT, drain, format_sse


# --- sse ----------------------------------------------------------------------------------------------


def test_format_sse_has_id_event_and_one_line_of_json() -> None:
    text = format_sse(SseEvent(3, "answer_delta", {"text": 'riga 1\nriga "2" è 🎬'}))

    assert text == 'id: 3\nevent: answer_delta\ndata: {"text":"riga 1\\nriga \\"2\\" è 🎬"}\n\n'
    assert text.count("\n") == 4  # the newline of the text is escaped: one `data` line


def test_drain_yields_events_in_order_until_the_end() -> None:
    async def scenario() -> list[str]:
        queue: asyncio.Queue = asyncio.Queue()
        for number in (1, 2):
            queue.put_nowait(SseEvent(number, "status", {"stage": "x"}))
        queue.put_nowait(END)
        return [text async for text in drain(queue, 5)]

    assert [text.split("\n")[0] for text in asyncio.run(scenario())] == ["id: 1", "id: 2"]


def test_drain_sends_a_comment_line_after_each_silent_interval() -> None:
    async def scenario() -> list[str]:
        queue: asyncio.Queue = asyncio.Queue()
        out: list[str] = []

        async def read() -> None:
            async for text in drain(queue, 0.01):
                out.append(text)

        reader = asyncio.create_task(read())
        await asyncio.sleep(0.05)
        queue.put_nowait(SseEvent(1, "done", {}))
        queue.put_nowait(END)
        await reader
        return out

    out = asyncio.run(scenario())
    assert out[0] == HEARTBEAT and out[-1].startswith("id: 1") and HEARTBEAT.startswith(":")


# --- store --------------------------------------------------------------------------------------------


def _store(ttl: float = 100, size: int = 3) -> ConversationStore:
    return ConversationStore(ttl_seconds=ttl, max_conversations=size)


def test_create_get_and_unknown_conversation() -> None:
    store = _store()
    conv = create_conversation(store, 0.0, "t")

    assert get_conversation(store, conv.id) is conv and conv.history == [] and not conv.busy
    with pytest.raises(ConversationNotFound):
        get_conversation(store, "missing")


def test_a_second_turn_is_refused_until_the_first_is_finished() -> None:
    conv = create_conversation(_store(), 0.0, "t")

    assert begin_turn(conv, 1.0) == 1
    with pytest.raises(TurnInProgress):
        begin_turn(conv, 2.0)
    finish_turn(conv, [{"role": "user", "content": "a"}], 3.0)
    assert begin_turn(conv, 4.0) == 2 and conv.turns_completed == 1


def test_finish_turn_without_history_keeps_it_and_frees_the_conversation() -> None:
    conv = create_conversation(_store(), 0.0, "t")
    conv.history = [{"role": "user", "content": "old"}]
    begin_turn(conv, 1.0)

    finish_turn(conv, None, 2.0)

    assert conv.history == [{"role": "user", "content": "old"}] and not conv.busy and conv.turns_completed == 0


def test_expired_idle_conversations_are_dropped_but_a_busy_one_never() -> None:
    store = _store(ttl=10)
    old, busy = create_conversation(store, 0.0, "t"), create_conversation(store, 0.0, "t")
    begin_turn(busy, 0.0)

    evict(store, 50.0)

    assert old.id not in store.conversations and busy.id in store.conversations


def test_over_the_size_the_least_recently_used_idle_conversation_goes() -> None:
    store = _store(size=2)
    first, second = create_conversation(store, 1.0, "t"), create_conversation(store, 2.0, "t")
    third = create_conversation(store, 3.0, "t")

    assert set(store.conversations) == {second.id, third.id} and first.id not in store.conversations


def test_delete_refuses_a_running_turn() -> None:
    store = _store()
    conv = create_conversation(store, 0.0, "t")
    begin_turn(conv, 1.0)
    with pytest.raises(TurnInProgress):
        delete_conversation(store, conv.id)
    finish_turn(conv, None, 2.0)
    delete_conversation(store, conv.id)
    assert conv.id not in store.conversations


# --- settings -----------------------------------------------------------------------------------------


def test_default_settings() -> None:
    settings = load_settings({})

    assert settings.cors_origins == DEFAULT_CORS_ORIGINS and settings.max_message_chars == 2000
    assert (settings.conversation_ttl_seconds, settings.max_conversations, settings.heartbeat_seconds) == (3600, 200, 15)


def test_settings_from_the_environment() -> None:
    settings = load_settings({
        "WEB_API_CORS_ORIGINS": " https://a.example , https://b.example,",
        "WEB_API_CONVERSATION_TTL_SECONDS": "60",
        "WEB_API_MAX_CONVERSATIONS": "5",
        "WEB_API_MAX_MESSAGE_CHARS": "300",
        "WEB_API_HEARTBEAT_SECONDS": "2.5",
    })

    assert settings.cors_origins == ("https://a.example", "https://b.example")
    assert (settings.conversation_ttl_seconds, settings.max_conversations) == (60, 5)
    assert (settings.max_message_chars, settings.heartbeat_seconds) == (300, 2.5)


def test_invalid_settings_fail_at_startup() -> None:
    with pytest.raises(ValueError):
        load_settings({"WEB_API_MAX_MESSAGE_CHARS": "0"})


# --- closing events -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("streamed", "final", "expected"),
    [
        ("Ciao mondo", "Ciao mondo", None),
        ("  Ciao mondo\n", "Ciao mondo", None),  # edges only: nothing to replace
        ("Ciao mondo", "\nCiao mondo  ", None),
        ("Ciao  mondo", "Ciao mondo", "Ciao mondo"),  # inner whitespace is content
        ("Ciao\nmondo", "Ciao mondo", "Ciao mondo"),
        ("Ciao", "Ciao mondo", "Ciao mondo"),
        ("", "Trama.", "Trama."),
        ("x", " Risposta intera \n", "Risposta intera"),  # replaced by the whole stripped text
        ("", "", None),
    ],
)
def test_replacement_compares_without_edge_whitespace_only(streamed, final, expected) -> None:
    assert replacement(streamed, final) == expected


def test_closing_events_are_answer_end_lists_done_and_do_not_repeat_the_text() -> None:
    from web_lists_support import MOVIE_REF, raw_list

    turn = make_turn([raw_list(MOVIE_REF)])
    events = final_events(turn, ANSWER)

    assert [name for name, _ in events] == ["answer_end", "lists", "done"]
    assert events[0][1]["replace"] is None and "answer" not in events[0][1]
    assert [item["id"] for item in events[1][1]["lists"][0]["items"]] == [157336]


def test_every_event_has_a_payload_model() -> None:
    assert set(EVENT_MODELS) == {
        "turn_start", "status", "story", "step", "answer_delta", "answer_end", "lists", "done", "error",
    }
    assert isinstance(make_turn(), TurnResult)
