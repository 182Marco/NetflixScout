"""Offline tests of the YouTube tool input (`tool/youtube/models.py`) and the search queries
(`tool/youtube/queries.py`)."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tool.youtube.models import (
    MAX_ALTERNATIVE_TITLES,
    VideoKind,
    YoutubeToolInput,
    describe_validation_errors,
    normalize_text,
)
from tool.youtube.queries import EXCLUDED_TERMS, KIND_TERMS, build_q, build_search_params, people_group, person_group, phrase

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
    assert "copied verbatim from the user's request or from earlier messages" in alternative["description"]
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
    # Multi-word title: the director stays an OR alternative (unchanged by fix 4).
    payload = request(title="Dune: Part Two", director="Denis Villeneuve", kinds=["director_interview", "making_of"])

    assert build_q(payload, VideoKind.director_interview) == (
        '"Dune: Part Two" interview|intervista|director|regista|"Denis Villeneuve" -reaction -parody'
    )
    assert "Villeneuve" not in build_q(payload, VideoKind.making_of)


# --- fix 4: one-word titles with a known person -------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (VideoKind.making_of, '"Her" "Spike Jonze"|"Jonze" "making of"|"making-of"|"come è stato girato" -reaction -parody'),
        (
            VideoKind.behind_the_scenes,
            '"Her" "Spike Jonze"|"Jonze" "behind the scenes"|"dietro le quinte"|backstage|featurette|"on set" -reaction -parody',
        ),
        # Interviews: the person is required, so it is no longer repeated among the kind terms.
        (VideoKind.director_interview, '"Her" "Spike Jonze"|"Jonze" interview|intervista|director|regista -reaction -parody'),
    ],
)
def test_one_word_title_with_known_director_requires_the_person(kind, expected) -> None:
    assert build_q(request(title="Her", director="Spike Jonze", kinds=[kind.value]), kind) == expected


def test_articles_do_not_count_as_words() -> None:
    q = build_q(request(title="The Heat", director="Paul Feig"), VideoKind.making_of)

    # "The Heat" is one significant word: the person is required ("Feig" has 4 letters).
    assert q.startswith('"The Heat" "Paul Feig"|"Feig" "making of"')


def test_one_word_title_without_a_person_keeps_the_current_query() -> None:
    assert build_q(request(title="Barbie"), VideoKind.behind_the_scenes) == (
        '"Barbie" "behind the scenes"|"dietro le quinte"|backstage|featurette|"on set" -reaction -parody'
    )
    # A blank director is no person: nothing is invented.
    assert build_q(request(title="Barbie", director="  "), VideoKind.making_of).startswith('"Barbie" "making of"')


@pytest.mark.parametrize("title", ["Dune: Part Two", "Mad Max: Fury Road", "La grande bellezza", "Blade Runner 2049"])
def test_multi_word_titles_never_require_the_person(title) -> None:
    q = build_q(request(title=title, director="Some Director"), VideoKind.making_of)

    assert "Director" not in q
    assert q.startswith(f'"{title}" "making of"')


def test_a_longer_alternative_title_keeps_the_person_optional() -> None:
    # "Barbie: The Movie" has several words: the OR group already contains a precise title.
    payload = request(title="Barbie", alternative_titles=["Barbie: The Movie"], director="Greta Gerwig")

    assert build_q(payload, VideoKind.making_of) == '"Barbie"|"Barbie: The Movie" "making of"|"making-of"|"come è stato girato" -reaction -parody'


def test_one_word_alternatives_still_require_the_person() -> None:
    payload = request(title="Her", alternative_titles=["Lei"], director="Spike Jonze")

    assert build_q(payload, VideoKind.making_of).startswith('"Her"|"Lei" "Spike Jonze"|"Jonze" "making of"')


@pytest.mark.parametrize(
    ("name", "group"),
    [
        ("Spike Jonze", '"Spike Jonze"|"Jonze"'),
        ("Bong Joon-ho", '"Bong Joon-ho"'),  # normalized surname "ho": too short, as in the filter
        ("Alejandro Amenábar", '"Alejandro Amenábar"|"Amenábar"'),
        ("Ang Lee", '"Ang Lee"'),  # surname too short to be distinctive
        ("Madonna", '"Madonna"'),  # one-word name
        ('Spike "Jonze" | x', '"Spike Jonze x"'),  # operators removed, last word "x" too short
        (None, None),
        ("   ", None),
    ],
)
def test_person_group(name, group) -> None:
    assert person_group(name) == group


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
        tree = ast.parse((ROOT / "tool" / "youtube" / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                assert node.module.split(".")[0] not in {"tool", "urllib", "http", "socket"}, (name, node.module)


# --- fix 3: cast_interview and the `cast` field -------------------------------------------------


def test_cast_field_schema_tells_the_planner_never_to_add_names() -> None:
    schema = YoutubeToolInput.model_json_schema()
    cast = schema["properties"]["cast"]

    assert cast["maxItems"] == 5 and "cast" not in schema["required"]
    assert "appear verbatim in the user's request or in the" in cast["description"]
    assert "Never add a name yourself" in cast["description"]
    kinds = schema["properties"]["kinds"]["description"]
    assert "director_interview (interviews with the director)" in kinds
    assert "cast_interview (interviews with the actors or the cast)" in kinds
    assert "cast_interview" in json.dumps(schema["$defs"]["VideoKind"])


def test_cast_is_optional_trimmed_deduplicated_and_capped() -> None:
    assert request().cast == []
    payload = request(director="Christopher Nolan", cast=[" Cillian  Murphy ", "cillian murphy", "", "Christopher Nolan", "Emily Blunt"])
    assert payload.cast == ["Cillian Murphy", "Emily Blunt"]  # duplicates and the director dropped
    assert payload.people == ["Christopher Nolan", "Cillian Murphy", "Emily Blunt"]
    with pytest.raises(ValidationError):
        request(cast=["A", "B", "C", "D", "E", "F"])
    with pytest.raises(ValidationError):
        request(cast="Cillian Murphy")


def test_cast_interview_query_with_names_as_alternatives() -> None:
    payload = request(title="Oppenheimer: the film", cast=["Cillian Murphy", "Emily Blunt"], kinds=["cast_interview"])

    assert build_q(payload, VideoKind.cast_interview) == (
        '"Oppenheimer: the film" interview|intervista|cast|"red carpet"|junket|"press conference"'
        '|"Cillian Murphy"|"Emily Blunt" -reaction -parody'
    )


def test_cast_interview_query_without_names_invents_nothing() -> None:
    q = build_q(request(title="Oppenheimer", kinds=["cast_interview"]), VideoKind.cast_interview)

    assert q == '"Oppenheimer" interview|intervista|cast|"red carpet"|junket|"press conference" -reaction -parody'


def test_one_word_title_requires_the_known_people_director_or_cast() -> None:
    """Oppenheimer: a one-word title; with a cast name the people are required (fix 4 extended)."""
    with_cast = request(title="Oppenheimer", cast=["Cillian Murphy"], kinds=["cast_interview"])
    both = request(title="Oppenheimer", director="Christopher Nolan", cast=["Cillian Murphy"], kinds=["cast_interview"])

    assert build_q(with_cast, VideoKind.cast_interview).startswith(
        '"Oppenheimer" "Cillian Murphy"|"Murphy" interview|intervista|cast|'
    )
    assert build_q(both, VideoKind.making_of).startswith(
        '"Oppenheimer" "Christopher Nolan"|"Nolan"|"Cillian Murphy"|"Murphy" "making of"'
    )


def test_director_interviews_do_not_list_the_cast_and_vice_versa() -> None:
    payload = request(title="Dune: Part Two", director="Denis Villeneuve", cast=["Zendaya"], kinds=["director_interview"])

    director_q = build_q(payload, VideoKind.director_interview)
    cast_q = build_q(payload, VideoKind.cast_interview)

    assert '"Denis Villeneuve"' in director_q and "Zendaya" not in director_q
    assert '"Zendaya"' in cast_q and "Villeneuve" not in cast_q


def test_without_cast_the_queries_of_the_previous_fixes_are_unchanged() -> None:
    assert build_q(request(title="Her", director="Spike Jonze"), VideoKind.making_of) == (
        '"Her" "Spike Jonze"|"Jonze" "making of"|"making-of"|"come è stato girato" -reaction -parody'
    )


def test_people_group() -> None:
    assert people_group(["Christopher Nolan", "Cillian Murphy"]) == '"Christopher Nolan"|"Nolan"|"Cillian Murphy"|"Murphy"'
    assert people_group(["Ang Lee", "Ang Lee"]) == '"Ang Lee"'
    assert people_group([]) is None and people_group(["  "]) is None


# --- fix 5: alternative and original titles only from the conversation --------------------------


def test_alternative_titles_description_forbids_deducing_and_covers_localized_titles() -> None:
    description = YoutubeToolInput.model_json_schema()["properties"]["alternative_titles"]["description"]

    assert "a title the user wrote in parentheses, or one given in a previous answer" in description
    assert "never deduce one from your own knowledge, not even a well-known original title" in description
    assert "If the user gives only a localized title" in description and "leave this empty" in description


def test_a_localized_title_alone_gets_no_alternatives() -> None:
    """Live run 15: only the Italian title was given; nothing is derived from it."""
    payload = request(title="Il favoloso mondo di Amélie")

    assert payload.alternative_titles == []
    q = build_q(payload, VideoKind.making_of)
    assert q.startswith('"Il favoloso mondo di Amélie" "making of"')
    assert '"Amélie"' not in q and "|" not in q.split('"making of"')[0]


def test_the_tool_never_adds_titles_of_its_own() -> None:
    # Only the given titles reach the query: no short form, no subtitle split, no translation.
    payload = request(title="Dune: Parte Due", alternative_titles=["Dune: Part Two"])

    assert build_q(payload, VideoKind.making_of).startswith('"Dune: Parte Due"|"Dune: Part Two" "making of"')
