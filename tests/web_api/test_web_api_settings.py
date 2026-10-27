"""The settings over HTTP: the public schema, the optional `preferences` of a message, the fallbacks,
the log, and the contract document `web_api/contracts/settings.md` (all offline, fake bot)."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import app as app_module
import pytest
from web_api_support import FakeOrchestrator, make_client, parse_sse

from preferences import behavior, public_schema

DOC = (Path(__file__).resolve().parents[2] / "web_api" / "contracts" / "settings.md").read_text(encoding="utf-8")
DEFAULTS = {
    "spoiler_plot": False,
    "response_length": "medium",
    "response_tone": "technician",
    "approach": "alternatives comparison",
    "content_type": "both",
    "preferred_sources": "official information",
}


@pytest.fixture(autouse=True)
def cinema(monkeypatch):
    monkeypatch.setattr(app_module, "classify_query_domain", lambda q, history=None: {"is_cinema": True, "language": "it"})


def _send(client, body: dict, conversation_id: str | None = None):
    conversation_id = conversation_id or client.post("/conversations").json()["conversation_id"]
    response = client.post(f"/conversations/{conversation_id}/messages", json=body)
    return response, (parse_sse(response.text) if response.status_code == 200 else [])


def _start(events) -> dict:
    return next(data for _, name, data in events if name == "turn_start")


def test_the_settings_endpoint_serves_exactly_the_public_definition() -> None:
    with make_client(FakeOrchestrator()) as client:
        response = client.get("/settings")

    assert response.status_code == 200 and response.json() == public_schema()
    text = json.dumps(response.json(), ensure_ascii=False)
    assert not any(fragment[:30] in text for fragment in behavior.TONE.values())


def test_a_client_without_preferences_gets_every_default() -> None:
    orchestrator = FakeOrchestrator()
    with make_client(orchestrator) as client:
        response, events = _send(client, {"content": "film di Nolan"})

    assert response.status_code == 200
    assert _start(events)["preferences"] == DEFAULTS and _start(events)["ignored_preferences"] == []
    parts = orchestrator.calls[0]["prompt_parts"]
    assert parts and parts["answer"] and parts["planner"]


def test_valid_preferences_are_applied_to_that_turn_and_the_next_one_can_differ() -> None:
    orchestrator = FakeOrchestrator()
    with make_client(orchestrator) as client:
        conversation = client.post("/conversations").json()["conversation_id"]
        _, first = _send(client, {"content": "uno", "preferences": {"response_tone": "Homie"}}, conversation)
        _, second = _send(client, {"content": "due", "preferences": {"response_tone": "technician", "response_length": "short"}}, conversation)

    assert _start(first)["preferences"]["response_tone"] == "Homie"
    assert _start(second)["preferences"]["response_tone"] == "technician"
    assert behavior.TONE["Homie"] in orchestrator.calls[0]["prompt_parts"]["answer"]
    assert behavior.TONE["Homie"] not in orchestrator.calls[1]["prompt_parts"]["answer"]
    assert behavior.LENGTH["short"] in orchestrator.calls[1]["prompt_parts"]["answer"]


@pytest.mark.parametrize("preferences", ["Homie", 5, ["x"], {"response_tone": "loud"}, {"spoiler_plot": "true"}, {"foo": 1}])
def test_bad_preferences_never_fail_the_request(preferences) -> None:
    with make_client(FakeOrchestrator()) as client:
        response, events = _send(client, {"content": "film", "preferences": preferences})

    assert response.status_code == 200
    assert [name for _, name, _ in events][-1] == "done"
    assert _start(events)["preferences"] == DEFAULTS


def test_only_the_wrong_field_falls_back_and_it_is_reported_and_logged(caplog) -> None:
    body = {"content": "film", "preferences": {"response_tone": "Homie", "approach": "nope", "content_type": "series"}}
    with caplog.at_level(logging.WARNING, logger="web_api.preferences"):
        with make_client(FakeOrchestrator()) as client:
            _, events = _send(client, body)

    start = _start(events)
    assert start["preferences"]["response_tone"] == "Homie" and start["preferences"]["content_type"] == "series"
    assert start["preferences"]["approach"] == DEFAULTS["approach"]
    assert start["ignored_preferences"] == ["approach"]
    assert any("field=approach" in record.getMessage() and "unknown_value" in record.getMessage() for record in caplog.records)


def test_structural_errors_stay_http_errors() -> None:
    with make_client(FakeOrchestrator()) as client:
        blank, _ = _send(client, {"content": "  ", "preferences": {}})
        extra, _ = _send(client, {"content": "ok", "unknown": 1})

    assert blank.status_code == 422 and blank.json()["error"]["code"] == "invalid_request"
    assert extra.status_code == 422


def test_the_settings_document_matches_the_public_definition() -> None:
    block = re.search(r"```json settings\n(.*?)\n```", DOC, re.S)
    assert block, "the document needs a ```json settings example"
    example = json.loads(block.group(1))
    real = {field["id"]: field for field in public_schema()["fields"]}

    assert example["version"] == public_schema()["version"]
    for field in example["fields"]:
        assert field == real[field["id"]]
    for definition in real.values():
        assert f"`{definition['id']}`" in DOC
        for option in definition.get("options", []):
            assert f"`{option['value']}`" in DOC


LABEL_LANGUAGES = {"en", "it", "es", "de", "fr"}
FIELD_ORDER = ["spoiler_plot", "response_length", "response_tone", "approach", "content_type", "preferred_sources"]
OPTION_VALUES = {
    "response_length": ["in-depth", "medium", "short"],
    "response_tone": ["technician", "Homie"],
    "approach": ["direct advice", "alternatives comparison"],
    "content_type": ["film", "series", "both"],
    "preferred_sources": ["reviews", "interviews", "official information", "user ratings"],
}


def test_every_label_has_exactly_the_five_languages_and_the_contract_is_unchanged() -> None:
    with make_client(FakeOrchestrator()) as client:
        body = client.get("/settings").json()

    assert body["version"] == 1 and [f["id"] for f in body["fields"]] == FIELD_ORDER
    for field in body["fields"]:
        labels = [field["label"], *(o["label"] for o in field.get("options", []))]
        for label in labels:
            assert set(label) == LABEL_LANGUAGES and all(isinstance(v, str) and v.strip() for v in label.values())
        assert field["default"] == DEFAULTS[field["id"]]
        assert [o["value"] for o in field.get("options", [])] == OPTION_VALUES.get(field["id"], [])


def test_the_homie_tone_labels_change_but_its_value_does_not() -> None:
    from preferences import resolve_preferences

    tone = next(f for f in public_schema()["fields"] if f["id"] == "response_tone")
    homie = next(o for o in tone["options"] if o["value"] == "Homie")

    assert homie["label"] == {"en": "Homie", "it": "Bro", "es": "Tío", "de": "Digga", "fr": "Gars"}
    assert resolve_preferences({"response_tone": "Homie"}).preferences.as_dict()["response_tone"] == "Homie"
    assert resolve_preferences({"response_tone": "homie"}).preferences.as_dict()["response_tone"] == "technician"
