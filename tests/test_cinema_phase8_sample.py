"""The phase 8 final sample is independent of the development questions and covers the required kinds of request."""
from __future__ import annotations

import re

from cinema_db.harness.tool_eval.run_live7 import questions
from cinema_db.harness.tool_eval.sample_phase8 import SAMPLE


GENERIC = {"oscar", "italia", "rotten", "tomatoes", "metascore", "imdb", "quali", "quanti", "chi", "dove", "dimmi", "mostrami", "elencami", "con", "who", "which", "wer", "film", "interviste",
           "punteggio", "parlami", "quando", "intendevo", "distingui", "esiste", "qual", "da", "il", "la", "le", "lo", "un", "una", "i", "gli", "di", "the", "of", "a", "and"}


def _entities(text: str) -> set[str]:
    """Capitalised words that are not the first of the sentence: the films, people and series a question is about."""
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", text)
    return {w.lower() for w in words[1:] if (w[0].isupper() or w[0].isdigit()) and w.lower() not in GENERIC}


def test_twenty_distinct_questions_with_keys() -> None:
    assert len(SAMPLE) == 20
    assert len({s.key for s in SAMPLE}) == 20 and len({s.text for s in SAMPLE}) == 20


def test_no_question_shares_a_film_or_person_with_the_development_questions() -> None:
    dev = [t for q in questions() for t in q.turns]
    assert not {s.text for s in SAMPLE} & set(dev)
    seen = set().union(*(_entities(d) for d in dev))
    for s in SAMPLE:
        assert not _entities(s.text) & seen, (s.key, _entities(s.text) & seen)


def test_the_sample_covers_the_required_kinds() -> None:
    covers = " | ".join(s.covers for s in SAMPLE).lower()
    for kind in ("film", "filmografia", "cast", "collaborazioni", "premi", "relazioni", "disambiguazione", "dato mancante", "esterna", "locale"):
        assert kind in covers, kind


def test_mechanical_floor_is_well_formed() -> None:
    for s in SAMPLE:
        assert all(group and all(w.strip() for w in group) for group in s.must), s.key
        assert s.expected_route and s.watch
