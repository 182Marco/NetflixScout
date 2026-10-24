from __future__ import annotations

import ast
from pathlib import Path

from presenters.web.payload import to_payload
from web_lists import attach_lists
from web_lists_support import MOVIE_REF, TV_REF, VIDEO_REF, make_turn, raw_list

ROOT = Path(__file__).resolve().parents[2]


def test_lists_are_added_and_the_rest_of_the_payload_is_unchanged() -> None:
    turn = make_turn()
    payload = to_payload(turn)
    result = attach_lists(payload, turn)
    assert {key: value for key, value in result.items() if key != "lists"} == payload
    assert [item["media_type"] for item in result["lists"][0]["items"]] == ["movie", "tv", "video"]
    assert "lists" not in payload


def test_resources_not_cited_in_the_answer_never_enter_the_lists() -> None:
    answer = "Ti consiglio Breaking Bad: la serie sulla chimica."
    turn = make_turn(answer=answer)  # the index also holds Interstellar and the video
    (web_list,) = attach_lists({}, turn)["lists"]
    assert [item["id"] for item in web_list["items"]] == [1396]


def test_resource_cited_without_a_reference_stays_out() -> None:
    turn = make_turn([raw_list(TV_REF)])
    (web_list,) = attach_lists({}, turn)["lists"]
    assert [item["id"] for item in web_list["items"]] == [1396]


def test_no_refs_blocked_turn_or_no_results_give_empty_lists() -> None:
    assert attach_lists({}, make_turn([]))["lists"] == []
    assert attach_lists({}, make_turn(blocked=True))["lists"] == []
    assert attach_lists({}, make_turn(steps=[]))["lists"] == []


def test_malformed_refs_give_empty_lists_and_keep_the_payload() -> None:
    turn = make_turn([{"list_id": "x"}])
    assert attach_lists({"answer": "a"}, turn) == {"answer": "a", "lists": []}
    turn = make_turn([raw_list({**MOVIE_REF, "extra": 1})])
    assert attach_lists({"answer": "a"}, turn)["lists"] == []


def test_an_internal_error_is_contained(monkeypatch) -> None:
    import sys

    # `web_lists.attach_lists` as an attribute is the function; the module is in sys.modules.
    monkeypatch.setattr(sys.modules["web_lists.attach_lists"], "index_steps", lambda steps: 1 / 0)
    assert attach_lists({"answer": "a"}, make_turn()) == {"answer": "a", "lists": []}


def test_no_network_or_llm_client_is_reachable_from_web_lists() -> None:
    banned = ("openai", "urllib.request", "requests", "httpx", "http.client", "socket", "tmdb", "youtube")
    for path in (ROOT / "web_lists").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not any(name == b or name.startswith(b + ".") for name in names for b in banned), path


def test_the_core_and_the_terminal_do_not_import_web_lists() -> None:
    files = [ROOT / "app.py", ROOT / "orchestrator.py", ROOT / "turn.py", *(ROOT / "presenters").rglob("*.py")]
    for path in files:
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [getattr(node, "module", "") or ""]
            assert not any(name.split(".")[0] == "web_lists" for name in names), path
