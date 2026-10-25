from __future__ import annotations

import threading

from wikipedia.budget import TurnRegistry, TurnState


def test_http_calls_are_counted_until_the_limit() -> None:
    state = TurnState()

    assert [state.try_reserve_http(2) for _ in range(3)] == [True, True, False]
    assert state.http_used == 2 and state.http_left(2) == 0 and state.http_left(5) == 3


def test_context_left_never_goes_negative() -> None:
    state = TurnState(context_used=45_000)

    assert state.context_left(40_000) == 0 and state.context_left(50_000) == 5_000


def test_runs_of_one_turn_share_the_state_and_other_turns_do_not() -> None:
    registry = TurnRegistry()
    first = registry.state("turn-1")
    first.try_reserve_http(6)
    first.delivered_for(("it", "Park Chan-wook")).add("carriera")

    assert registry.state("turn-1") is first
    assert registry.state("turn-1").delivered_for(("it", "Park Chan-wook")) == {"carriera"}
    assert registry.state("turn-2").http_used == 0


def test_a_run_without_turn_id_gets_a_fresh_state_each_time() -> None:
    registry = TurnRegistry()

    assert registry.state(None) is not registry.state(None)


def test_the_oldest_turns_are_forgotten() -> None:
    registry = TurnRegistry(max_turns=2)
    first = registry.state("a")
    registry.state("b")
    registry.state("a")  # "a" is now the most recent
    registry.state("c")  # forgets "b"

    assert registry.state("a") is first
    assert len(registry._turns) == 2 and "b" not in registry._turns


def test_concurrent_turns_do_not_reset_each_other() -> None:
    registry = TurnRegistry()
    results: dict[str, int] = {}

    def worker(turn: str) -> None:
        state = registry.state(turn)
        for _ in range(5):
            state.try_reserve_http(100)
            registry.state("other-%s" % turn)  # activity of other turns in between
        results[turn] = registry.state(turn).http_used

    threads = [threading.Thread(target=worker, args=(f"t{i}",)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results == {f"t{i}": 5 for i in range(8)}
