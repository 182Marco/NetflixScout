"""Offline tests of the YouTube tool input (`youtube/models.py`) and the search queries
(`youtube/queries.py`)."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from youtube.models import (
    MAX_ALTERNATIVE_TITLES,
    VideoKind,
    YoutubeToolInput,
    describe_validation_errors,
    normalize_text,
)
from youtube.queries import EXCLUDED_TERMS, KIND_TERMS, build_q, build_search_params, phrase

ROOT = Path(__file__).resolve().parents[1]


def request(**fields) -> YoutubeToolInput:
    return YoutubeToolInput.model_validate({"query": "domanda", "title": "Dune", "kinds": ["making_of"], **fields})


# --- model validation ---------------------------------------------------------------


def test_minimal_input_has_empty_optional_fields() -> None:
    payload = request()

    assert (payload.title, payload.alternative_titles, payload.year, payload.director) == ("Dune", [], None, None)
    assert payload.kinds == [VideoKind.making_of]


def test_text_fields_are_trimmed_and_blank_director_is_none() -> None:
    payload = request(title="  Dune:   Part Two ", director="   ")

    assert payload.title == "Dune: Part Two" and payload.director is None


@pytest.mark.parametrize(
    "fields",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"kinds": []},
        {"kinds": ["trailer", "making_of", "behind_the_scenes", "director_interview"]},
        {"kinds": ["bloopers"]},
        {"year": 1800},
        {"year": "nineteen"},
        {"director": "x" * 101},
        {"alternative_titles": ["A", "B", "C", "D"]},
        {"alternative_titles": "Mar adentro"},
        {"url": "https://example.com"},
        {"region_code": "IT"},
    ],
)
def test_invalid_inputs_are_rejected(fields) -> None:
    with pytest.raises(ValidationError):
        request(**fields)


def test_title_is_required() -> None:
    with pytest.raises(ValidationError):
        YoutubeToolInput.model_validate({"query": "q", "kinds": ["making_of"]})


def test_repeated_kinds_count_once_in_their_first_position() -> None:
    payload = request(kinds=["making_of", "trailer", "making_of"])

    assert payload.kinds == [VideoKind.making_of, VideoKind.trailer]


def test_alternative_titles_keep_order_and_drop_blanks_and_duplicates() -> None:
    payload = request(
        title="The Sea Inside",
        alternative_titles=["Mare dentro", "  ", "THE SEA INSIDE", "mare  dentro!"],
    )

    assert payload.alternative_titles == ["Mare dentro"]
    assert request(alternative_titles=["Mar adentro", "Mare dentro"]).alternative_titles == ["Mar adentro", "Mare dentro"]


def test_at_most_three_alternative_titles_before_deduplication() -> None:
    assert len(request(alternative_titles=["A", "B", "C"]).alternative_titles) == MAX_ALTERNATIVE_TITLES


def test_schema_tells_the_planner_never_to_invent_alternative_titles() -> None:
    schema = YoutubeToolInput.model_json_schema()
    alternative = schema["properties"]["alternative_titles"]

    assert alternative["maxItems"] == 3 and "alternative_titles" not in schema["required"]
    assert "verbatim in the conversation" in alternative["description"]
    assert "Never invent or translate" in alternative["description"]
    assert set(schema["required"]) == {"query", "title", "kinds"}
    assert schema["additionalProperties"] is False
    assert "only if the user explicitly asks for YouTube" in schema["properties"]["kinds"]["description"]
    json.dumps(schema)  # compact JSON in the planning catalog


def test_validation_errors_never_report_input_values() -> None:
    secret_like = "Titolo segreto dell'utente"
    with pytest.raises(ValidationError) as exc:
        YoutubeToolInput.model_validate(
            {"query": "q", "title": secret_like * 20, "kinds": ["bloopers"], "url": secret_like}
        )

    rows = describe_validation_errors(exc.value)

    assert {row["field"] for row in rows} == {"title", "kinds", "unknown_field"}
    assert secret_like not in json.dumps(rows)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Dune: Part Two", "dune part two"), ("Amélie", "amelie"), ("Mars & Avril", "mars and avril"), (None, "")],
)
def test_normalize_text(text, expected) -> None:
    assert normalize_text(text) == expected


# --- query building -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (VideoKind.trailer, '"Dune" trailer|teaser|"trailer ufficiale" -reaction -parody'),
        (VideoKind.director_interview, '"Dune" interview|intervista|director|regista -reaction -parody'),
        (VideoKind.making_of, '"Dune" "making of"|"making-of"|"come è stato girato" -reaction -parody'),
        (
            VideoKind.behind_the_scenes,
            '"Dune" "behind the scenes"|"dietro le quinte"|backstage|featurette|"on set" -reaction -parody',
        ),
        (
            VideoKind.author_commentary,
            '"Dune" commentary|"director explains"|explains|"commento del regista"|spiega -reaction -parody',
        ),
    ],
)
def test_each_kind_has_its_own_query(kind, expected) -> None:
    assert build_q(request(kinds=[kind.value]), kind) == expected


def test_every_kind_has_terms() -> None:
    assert set(KIND_TERMS) == set(VideoKind)


def test_alternative_titles_are_or_alternatives_of_the_title() -> None:
    payload = request(title="The Sea Inside", alternative_titles=["Mar adentro", "Mare dentro"])

    assert build_q(payload, VideoKind.making_of).startswith('"The Sea Inside"|"Mar adentro"|"Mare dentro" ')


def test_director_is_an_alternative_term_only_for_interviews() -> None:
    payload = request(director="Denis Villeneuve", kinds=["director_interview", "making_of"])

    assert build_q(payload, VideoKind.director_interview) == (
        '"Dune" interview|intervista|director|regista|"Denis Villeneuve" -reaction -parody'
    )
    assert "Villeneuve" not in build_q(payload, VideoKind.making_of)


def test_year_is_never_a_search_term() -> None:
    assert "2021" not in build_q(request(year=2021), VideoKind.making_of)


def test_only_two_exclusions_are_sent() -> None:
    assert EXCLUDED_TERMS == ("-reaction", "-parody")
    q = build_q(request(), VideoKind.director_interview)
    assert "-trailer" not in q and "-review" not in q


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ('Dune" -interview | "x', '"Dune -interview x"'),
        ("C'è ancora domani", '"C\'è ancora domani"'),
        ("Spider-Man: No Way Home", '"Spider-Man: No Way Home"'),
        ("Dune\x1b[31m\nPart\tTwo", '"Dune [31m Part Two"'),
        ('"|"', None),
    ],
)
def test_user_values_cannot_add_operators(title, expected) -> None:
    assert phrase(title) == expected


def test_a_title_made_only_of_operators_still_builds_a_query_from_the_others() -> None:
    payload = request(title="Dune", alternative_titles=['"|"'])

    assert build_q(payload, VideoKind.trailer).startswith('"Dune" trailer')


def test_search_params_have_no_geographic_or_language_restriction() -> None:
    params = build_search_params(request(), VideoKind.making_of, max_results=3)

    assert params == {
        "part": "snippet",
        "type": "video",
        "order": "relevance",
        "safeSearch": "moderate",
        "maxResults": "9",
        "q": build_q(request(), VideoKind.making_of),
    }
    assert "regionCode" not in params and "relevanceLanguage" not in params
    assert all(isinstance(value, str) for value in params.values())


def test_fetch_size_is_capped_by_the_api_maximum() -> None:
    assert build_search_params(request(), VideoKind.trailer, max_results=10)["maxResults"] == "30"
    assert build_search_params(request(), VideoKind.trailer, max_results=1)["maxResults"] == "3"


def test_queries_and_models_never_import_tmdb_or_do_io() -> None:
    for name in ("models.py", "queries.py"):
        tree = ast.parse((ROOT / "youtube" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module.split(".")[0] not in {"tmdb", "urllib", "http", "socket"}, (name, node.module)
