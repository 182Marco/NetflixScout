"""`web_api/contracts/chat_stream.md` describes what the code does: events, routes and example payloads."""
from __future__ import annotations

import json
import re
from pathlib import Path

from web_api.routes.endpoints import router
from web_api.routes.errors import CODE_IN_PROGRESS, CODE_INVALID, CODE_NOT_FOUND, CODE_TOO_LONG
from web_api.schemas.events import EVENT_MODELS
from web_api.settings import (
    ENV_CONVERSATION_TTL,
    ENV_CORS_ORIGINS,
    ENV_HEARTBEAT,
    ENV_MAX_CONVERSATIONS,
    ENV_MAX_MESSAGE_CHARS,
)

DOC = (Path(__file__).resolve().parents[2] / "web_api" / "contracts" / "chat_stream.md").read_text(encoding="utf-8")
EXAMPLE = re.compile(r"```json event=(\w+)\n(.*?)\n```", re.S)


def test_every_event_is_documented_with_a_valid_example() -> None:
    examples = {name: json.loads(body) for name, body in EXAMPLE.findall(DOC)}

    assert set(examples) == set(EVENT_MODELS)
    for name, payload in examples.items():
        EVENT_MODELS[name].model_validate(payload)


def test_every_route_and_error_code_is_documented() -> None:
    for route in router.routes:
        method = sorted(route.methods - {"HEAD", "OPTIONS"})[0]
        assert f"{method} {route.path.replace('{conversation_id}', '{id}')}" in DOC, route.path
    for code in (CODE_NOT_FOUND, CODE_IN_PROGRESS, CODE_INVALID, CODE_TOO_LONG):
        assert f"`{code}`" in DOC


def test_every_setting_is_documented() -> None:
    for name in (ENV_CORS_ORIGINS, ENV_CONVERSATION_TTL, ENV_MAX_CONVERSATIONS, ENV_MAX_MESSAGE_CHARS, ENV_HEARTBEAT):
        assert f"`{name}`" in DOC


STEP_EXAMPLE = re.compile(r"```json step=(\w+)\n(.*?)\n```", re.S)


def test_every_tool_step_kind_is_named_in_the_contract_and_its_calls_are_described() -> None:
    from presenters.web.payload import STEP_SERIALIZERS

    for kind in STEP_SERIALIZERS:
        assert f"`{kind}`" in DOC, kind
    section = DOC[DOC.index("#### Le chiamate HTTP dei tool"):]
    for text in ("`{\"method\",\"url\"}`", "ogni", "nell'ordine", "`***`", "più eventi"):
        assert text in section.split("\n### ")[0], text


def test_the_documented_omdb_step_is_what_the_serializer_produces_and_its_calls_are_masked() -> None:
    from omdb_support import doc_step
    from presenters.web.payload import serialize_step

    examples = {kind: json.loads(body) for kind, body in STEP_EXAMPLE.findall(DOC)}
    documented = examples["omdb_calls"]

    assert documented == json.loads(json.dumps(serialize_step(doc_step(), "it")))
    assert len(documented["calls"]) == 2 and all(set(call) == {"method", "url"} for call in documented["calls"])
    assert all(call["url"].startswith("https://") and "apikey=***" in call["url"] for call in documented["calls"])


def test_the_documented_tvmaze_step_is_what_the_serializer_produces_with_its_attribution_links() -> None:
    from presenters.web.payload import serialize_step
    from tvmaze_support import doc_step

    documented = {kind: json.loads(body) for kind, body in STEP_EXAMPLE.findall(DOC)}["tvmaze_calls"]

    assert documented == json.loads(json.dumps(serialize_step(doc_step(), "it")))
    assert len(documented["calls"]) == 2 and all(set(call) == {"method", "url"} for call in documented["calls"])
    assert documented["show"]["url"].startswith("https://www.tvmaze.com/")
    assert documented["license"] == {"name": "CC BY-SA 4.0", "url": "https://creativecommons.org/licenses/by-sa/4.0/"}
    assert "CC BY-SA 4.0" in documented["source"]


def test_every_documented_step_example_keeps_credentials_masked() -> None:
    for _, body in STEP_EXAMPLE.findall(DOC) + EXAMPLE.findall(DOC):
        for url in re.findall(r'"url":"([^"]+)"', body):
            assert not re.search(r"(?i)(api_?key|key|token|secret|password)=(?!\*\*\*)", url), url


def test_the_blocked_turn_contract_lists_only_the_necessary_events() -> None:
    section = DOC[DOC.index("`blocked: true`"):]
    sentence = section[: section.index("### `lists`")]

    for event in ("turn_start", "answer_delta", "answer_end", "lists", "done"):
        assert event in sentence
    assert "mai `status`, `story` né `step`" in sentence
