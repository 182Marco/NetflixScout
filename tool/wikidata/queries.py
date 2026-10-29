"""Requests of the tool as constant fragments. Pure: no I/O.

Nothing here is written by the model. A SPARQL text is made of constant fragments and of values that
passed a strict pattern (`Q` ids, an IMDb title id, a TMDb integer); the user's title appears only as
the `search` parameter of the entity search and, in `label_request`, inside one escaped string literal
(`sparql_literal`), which cannot be closed from inside. Every query is bound to given
entities (or to an exact external id) so that it does not scan the whole graph.

Wikidata items and properties used (ids as in Wikidata):
  classes   Q11424 film, Q5398426 television series, Q18011172 film project (announced, not released),
            Q7725634 literary work, Q7889 video game, Q1004 comics
  relations P144 based on, P4969 derivative work, P155 follows, P156 followed by,
            P179 part of the series, P8345 media franchise
  dates     P577 publication date, P580 start time
  people    P57 director
  ids       P345 IMDb ID, P4947 TMDB movie ID, P4983 TMDB TV series ID
"""
from __future__ import annotations

import re

from .models import IMDB_TITLE_ID
from .settings import SEARCH_LIMIT, SPARQL_ROW_LIMIT

# (endpoint, params): the endpoint is "api" (entity search) or "sparql".
Request = tuple[str, tuple[tuple[str, str], ...]]

QID = re.compile(r"^Q[1-9]\d{0,12}$")

CLASS_FILM = "Q11424"
CLASS_SERIES = "Q5398426"
CLASS_PROJECT = "Q18011172"
CLASS_LITERARY = "Q7725634"
CLASS_GAME = "Q7889"
CLASS_COMICS = "Q1004"

_FLAGS = (
    ("film", CLASS_FILM),
    ("series", CLASS_SERIES),
    ("project", CLASS_PROJECT),
    ("literary", CLASS_LITERARY),
    ("game", CLASS_GAME),
    ("comics", CLASS_COMICS),
)


def _compact(text: str) -> str:
    return " ".join(text.split())


def _qid(value: str) -> str:
    if not QID.match(value):
        raise ValueError("not a Wikidata item id")
    return value


def _flags(variable: str, names: tuple[str, ...]) -> str:
    """`BIND(EXISTS{...} AS ?name)` for the classes in `names`: is the item an instance of the class or of a subclass."""
    classes = dict(_FLAGS)
    return " ".join(
        f"BIND(EXISTS{{{variable} wdt:P31/wdt:P279* wd:{classes[name]}}} AS ?{name})" for name in names
    )


def sparql_request(text: str) -> Request:
    return "sparql", (("query", _compact(text)), ("format", "json"))


def search_request(title: str, language: str) -> Request:
    return "api", (
        ("action", "wbsearchentities"),
        ("search", title),
        ("language", language),
        ("type", "item"),
        ("limit", str(SEARCH_LIMIT)),
        ("format", "json"),
    )


def _details(binding: str, only_screen_works: bool = False) -> Request:
    # A search by label can match thousands of items of any kind: keep only films and series before the OPTIONALs.
    keep = "FILTER(?film || ?series)" if only_screen_works else ""
    return sparql_request(
        f"""
        SELECT ?w ?wLabel ?wDescription ?film ?series ?project ?pub ?start ?dirLabel ?imdb ?tmdbMovie ?tmdbTv
        WHERE {{
          {binding}
          {_flags("?w", ("film", "series", "project"))}
          {keep}
          OPTIONAL {{ ?w wdt:P577 ?pub }} OPTIONAL {{ ?w wdt:P580 ?start }}
          OPTIONAL {{ ?w wdt:P57 ?dir }}
          OPTIONAL {{ ?w wdt:P345 ?imdb }} OPTIONAL {{ ?w wdt:P4947 ?tmdbMovie }} OPTIONAL {{ ?w wdt:P4983 ?tmdbTv }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }} LIMIT {SPARQL_ROW_LIMIT}
        """
    )


_LANGUAGE = re.compile(r"^[a-z]{2,3}$")
_CONTROLS = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def sparql_literal(text: str) -> str:
    """`text` as a SPARQL string literal: control characters become spaces, backslash and double quote are escaped.

    The only place where words of the user enter a SPARQL text, always inside this literal: it cannot be closed
    from inside, so it cannot add a pattern to the query.
    """
    cleaned = _CONTROLS.sub(" ", text).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{cleaned}"'


def label_request(title: str, language: str) -> Request:
    """Films and series whose label in `language` is exactly the title: every work of that name, not the
    ten best known entities of any kind that a text search returns."""
    if not _LANGUAGE.match(language):
        raise ValueError("not a language code")
    return _details(f"?w rdfs:label {sparql_literal(title)}@{language} .", only_screen_works=True)


def details_request(ids: list[str]) -> Request:
    """Year, director and external ids of the items a search returned."""
    values = " ".join(f"wd:{_qid(item)}" for item in ids)
    return _details(f"VALUES ?w {{ {values} }}")


def imdb_request(imdb_id: str) -> Request:
    if not IMDB_TITLE_ID.match(imdb_id):
        raise ValueError("not an IMDb title id")
    return _details(f'?w wdt:P345 "{imdb_id}" .')


def tmdb_request(tmdb_id: int, media: str) -> Request:
    prop = {"movie": "P4947", "tv": "P4983"}[media]
    return _details(f'?w wdt:{prop} "{int(tmdb_id)}" .')


def relations_request(subject: str) -> Request:
    """Works linked to the subject by one of the relations, in either direction, with class flags and dates."""
    s = f"wd:{_qid(subject)}"
    unions = " UNION ".join(
        f'{{ {pattern} BIND("{tag}" AS ?rel) }}'
        for pattern, tag in (
            (f"{s} wdt:P144 ?o", "source"),
            (f"?o wdt:P4969 {s}", "source"),
            (f"?o wdt:P144 {s}", "derived"),
            (f"{s} wdt:P4969 ?o", "derived"),
            (f"{s} wdt:P155 ?o", "previous"),
            (f"?o wdt:P156 {s}", "previous"),
            (f"{s} wdt:P156 ?o", "next"),
            (f"?o wdt:P155 {s}", "next"),
            (f"{s} wdt:P179 ?o", "container"),
            (f"{s} wdt:P8345 ?o", "container"),
        )
    )
    return sparql_request(
        f"""
        SELECT ?rel ?o ?oLabel ?oDescription ?film ?series ?project ?literary ?game ?comics ?pub ?start
        WHERE {{
          {unions}
          FILTER(?o != {s})
          {_flags("?o", tuple(name for name, _ in _FLAGS))}
          OPTIONAL {{ ?o wdt:P577 ?pub }} OPTIONAL {{ ?o wdt:P580 ?start }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }} LIMIT {SPARQL_ROW_LIMIT}
        """
    )


def members_request(containers: list[str]) -> Request:
    """Works that declare themselves part of one of the franchises or series, in one request."""
    values = " ".join(f"wd:{_qid(item)}" for item in containers)
    return sparql_request(
        f"""
        SELECT ?f ?o ?oLabel ?oDescription ?film ?series ?project ?literary ?game ?comics ?pub ?start
        WHERE {{
          VALUES ?f {{ {values} }}
          {{ ?o wdt:P8345 ?f }} UNION {{ ?o wdt:P179 ?f }}
          {_flags("?o", tuple(name for name, _ in _FLAGS))}
          OPTIONAL {{ ?o wdt:P577 ?pub }} OPTIONAL {{ ?o wdt:P580 ?start }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
        }} LIMIT {SPARQL_ROW_LIMIT}
        """
    )
