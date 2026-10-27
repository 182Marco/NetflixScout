"""User settings: public definition, validation, private behaviour and prompt composition (offline)."""
from __future__ import annotations

import json

import pytest

from app import CONFIG
from preferences import behavior, build_prompt_parts, defaults, public_schema, resolve_preferences
from preferences.public import FIELDS_PATH, field_definitions
from preferences.resolve import CODE_INVALID_TYPE, CODE_NOT_OBJECT, CODE_UNKNOWN_FIELD, CODE_UNKNOWN_VALUE

DEFAULTS = {
    "spoiler_plot": False,
    "response_length": "medium",
    "response_tone": "technician",
    "approach": "alternatives comparison",
    "content_type": "both",
    "preferred_sources": "official information",
}

VALID = {
    "spoiler_plot": True,
    "response_length": "short",
    "response_tone": "Homie",
    "approach": "direct advice",
    "content_type": "series",
    "preferred_sources": "reviews",
}


def test_the_defaults_are_the_documented_ones() -> None:
    assert defaults().as_dict() == DEFAULTS
    assert resolve_preferences(None).preferences.as_dict() == DEFAULTS
    assert resolve_preferences(None).issues == []


def test_valid_values_are_applied_and_an_empty_object_means_defaults() -> None:
    assert resolve_preferences(VALID).preferences.as_dict() == VALID
    assert resolve_preferences({}).preferences.as_dict() == DEFAULTS


@pytest.mark.parametrize("field_id", list(VALID))
@pytest.mark.parametrize("bad", ["???", 3, None, [], {}, "homie", "True"])
def test_an_invalid_field_falls_back_alone_and_keeps_the_others(field_id: str, bad) -> None:
    resolution = resolve_preferences({**VALID, field_id: bad})

    assert resolution.preferences[field_id] == DEFAULTS[field_id]
    for other in VALID:
        if other != field_id:
            assert resolution.preferences[other] == VALID[other]
    assert resolution.ignored == [field_id]
    assert resolution.issues[0].code in (CODE_INVALID_TYPE, CODE_UNKNOWN_VALUE)


def test_a_boolean_is_not_a_string_or_a_number() -> None:
    for bad in ("true", 1, 0, None):
        assert resolve_preferences({"spoiler_plot": bad}).preferences["spoiler_plot"] is False


@pytest.mark.parametrize("raw", ["Homie", ["Homie"], 7, True])
def test_preferences_that_are_not_an_object_mean_defaults(raw) -> None:
    resolution = resolve_preferences(raw)

    assert resolution.preferences.as_dict() == DEFAULTS
    assert resolution.issues[0].code == CODE_NOT_OBJECT and resolution.ignored == []


def test_unknown_keys_are_ignored_and_reported_without_hiding_the_valid_ones() -> None:
    resolution = resolve_preferences({"response_tone": "Homie", "font_size": 12})

    assert resolution.preferences["response_tone"] == "Homie"
    assert [i.code for i in resolution.issues] == [CODE_UNKNOWN_FIELD]
    assert resolution.ignored == []


def test_a_long_bad_value_is_shortened_in_the_report() -> None:
    issue = resolve_preferences({"response_tone": "x" * 500}).issues[0]

    assert len(issue.value) < 60


def test_every_public_option_has_a_private_fragment_and_the_default_is_an_option() -> None:
    tables = {
        "spoiler_plot": [behavior.SPOILER],
        "response_length": [behavior.LENGTH],
        "response_tone": [behavior.TONE],
        "approach": [behavior.APPROACH],
        "content_type": [behavior.CONTENT_ANSWER],
        "preferred_sources": [behavior.SOURCES_ANSWER, behavior.SOURCES_PLANNER],
    }
    assert set(tables) == {f["id"] for f in field_definitions()}
    for definition in field_definitions():
        values = [True, False] if definition["type"] == "boolean" else [o["value"] for o in definition["options"]]
        for table in tables[definition["id"]]:
            assert set(table) == set(values), definition["id"]
        assert definition["default"] in values


def test_the_public_schema_has_no_private_text() -> None:
    schema = json.dumps(public_schema(), ensure_ascii=False)
    private = [*behavior.TONE.values(), *behavior.SPOILER.values(), behavior.ANSWER_INTRO, behavior.PLANNER_INTRO]

    assert not any(text[:30] in schema for text in private)
    assert public_schema() == json.loads(FIELDS_PATH.read_text(encoding="utf-8"))
    public_schema()["fields"].clear()  # a caller changing its copy does not change the next one
    assert len(public_schema()["fields"]) == 6


def test_every_tool_of_the_app_declares_the_source_it_serves() -> None:
    allowed = CONFIG["orchestrator"]["allowed_tools"]
    options = {o["value"] for f in field_definitions() if f["id"] == "preferred_sources" for o in f["options"]}

    assert set(allowed) <= set(behavior.SOURCE_TOOLS)
    assert set(behavior.SOURCE_TOOLS.values()) <= options


def test_composition_is_deterministic_and_every_fragment_appears_once() -> None:
    prefs = resolve_preferences(VALID).preferences
    parts = build_prompt_parts(prefs)

    assert parts == build_prompt_parts(prefs)
    assert parts["answer"].count(behavior.TONE["Homie"]) == 1
    assert parts["answer"].count(behavior.SPOILER[True]) == 1
    assert behavior.TONE["technician"] not in parts["answer"]
    assert parts["answer"].count(behavior.ANSWER_INTRO) == 1


def test_the_planner_part_has_only_routing_settings_and_never_asks_for_a_call() -> None:
    parts = build_prompt_parts(resolve_preferences(VALID).preferences)

    assert behavior.CONTENT_PLANNER["series"] in parts["planner"]
    assert behavior.SOURCES_PLANNER["reviews"] in parts["planner"]
    for text in (*behavior.TONE.values(), *behavior.LENGTH.values(), *behavior.SPOILER.values()):
        assert text not in parts["planner"]
    assert "non aggiungono tool né passi" in parts["planner"]
    assert "youtube_search" not in parts["planner"]  # the reviews source adds no step


def test_only_the_interviews_source_adds_a_step_and_only_for_an_identified_title() -> None:
    steps = {
        value: build_prompt_parts(resolve_preferences({"preferred_sources": value}).preferences)["planner"]
        for value in behavior.SOURCES_PLANNER
    }

    assert [value for value, text in steps.items() if "youtube_search" in text] == ["interviews"]
    assert "more_steps true" in steps["interviews"] and "identificati da un titolo" in steps["interviews"]
    assert "NON classifiche" in steps["interviews"]
    assert "ONE declared" in behavior.__doc__


def test_a_contradicting_spoiler_request_is_never_answered_and_the_user_is_told() -> None:
    text = build_prompt_parts(defaults())["answer"]

    assert "non rivelarlo MAI" in text and "contraddice" in text


def test_the_tool_rules_no_longer_force_a_short_answer() -> None:
    rules = CONFIG["orchestrator"]["tool_final_instructions"]

    assert not any("Rispondi in modo conciso" in text for text in rules.values())
    assert "Rispondi in modo conciso" not in CONFIG["orchestrator"]["final_instructions"]


def test_answer_settings_never_ask_for_the_provenance_of_the_data() -> None:
    from preferences import behavior as b

    assert not any("dichiarando sempre la fonte" in t for t in b.SOURCES_ANSWER.values())
    assert "Non spiegare mai da dove vengono i dati" in b.ANSWER_INTRO
