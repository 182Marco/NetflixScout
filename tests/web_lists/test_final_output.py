from __future__ import annotations

import json

from web_lists import final_output
from web_lists.json_schema import json_schema


def test_final_output_is_plain_data_for_the_core() -> None:
    value = final_output()
    assert set(value) == {"text_format", "instructions", "answer_field"}
    json.dumps(value)  # serializable as is
    assert value["text_format"]["strict"] is True and value["instructions"]


def test_root_has_answer_first_then_lists() -> None:
    assert list(json_schema()["schema"]["properties"]) == ["answer", "lists"]


def test_schema_is_strict_everywhere() -> None:
    def walk(node):
        if isinstance(node, dict):
            if "properties" in node:
                assert node["additionalProperties"] is False
                assert node["required"] == list(node["properties"])
            assert "const" not in node and "default" not in node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(json_schema()["schema"])


def test_refs_ask_for_a_quote() -> None:
    defs = json_schema()["schema"]["$defs"]
    assert "quote" in defs["TmdbRef"]["properties"] and "quote" in defs["YoutubeRef"]["properties"]
