"""Constraint statuses of the final RAG chunks (D5): offline, built from real cases 11, 12, 20."""
from __future__ import annotations

from tool.rag.FromQueryEmbeddingToRes.constraints import constraint_report
from tool.rag.FromQueryEmbeddingToRes.models import QuerySignals


def _chunk(title, year, genres, plot):
    return {"title": title, "release_year": str(year) if year else None, "genres": genres, "testo": plot}


def _statuses(report):
    return {(check["constraint"], title): result["status"]
            for check in report["checks"] for title, result in check["results"].items()}


# Case 11: euthanasia, delicate tone, without science fiction (texts from the corpus).
EXIT = _chunk("Exit: una storia personale", None, "Drama",
              "Marco asks his brother to take him to Holland for assisted suicide; euthanasia is legal there.")
REACH = _chunk("Reach for Me", 2009, "Drama; Comedy", "Alvin makes life hell for everyone in his hospice.")
CASE_11 = QuerySignals(positive_signals=["euthanasia", "delicate tone"], excluded_genres=["Science Fiction"])


def test_case_11_genre_exclusion_is_verified_and_tone_is_never_claimed() -> None:
    statuses = _statuses(constraint_report(CASE_11, [EXIT, REACH]))

    assert statuses[("Science Fiction", "Exit: una storia personale (?)")] == "verified"
    assert statuses[("euthanasia", "Exit: una storia personale (?)")] == "probable"
    # No mention of euthanasia is not proof of the opposite, and a tone is never verifiable.
    assert statuses[("euthanasia", "Reach for Me (2009)")] == "not_verifiable"
    assert statuses[("delicate tone", "Exit: una storia personale (?)")] == "not_verifiable"


# Case 12: like The Godfather, but with a non-tragic ending.
PUBLIC_ENEMY = _chunk("The Public Enemy", 1931, "Crime Fiction; Gangster Film",
                      "Tom rises from petty crime to bootlegging; rival gangsters kill his friend Matt.")
TRAGIC = _chunk("Tragedia", 1950, "Drama", "Everything ends in a tragic ending for the family.")
CASE_12 = QuerySignals(positive_signals=["non-tragic ending", "organized crime"], negative_signals=["tragic ending"])


def test_case_12_ending_is_not_verifiable_unless_the_plot_says_so() -> None:
    report = constraint_report(CASE_12, [PUBLIC_ENEMY, TRAGIC])
    statuses = _statuses(report)

    # Without information on the ending the film is kept and nothing is claimed.
    assert statuses[("non-tragic ending", "The Public Enemy (1931)")] == "not_verifiable"
    assert statuses[("tragic ending", "The Public Enemy (1931)")] == "not_verifiable"
    # An explicit phrase in the plot contradicts the request.
    assert statuses[("tragic ending", "Tragedia (1950)")] == "contradicted"
    assert statuses[("non-tragic ending", "Tragedia (1950)")] == "contradicted"
    assert "probable" not in {s for (c, _), s in statuses.items() if "ending" in c}


# Case 20: Japanese 1950s science fiction comedy set on Mars, open ending.
CONQUEST = _chunk("Conquest of Space", 1955, "Science Fiction; Drama; Adventure",
                  "The first manned mission to Mars leaves the space station.")
JUST_IMAGINE = _chunk("Just Imagine", 1930, "Musical; Science Fiction; Comedy", "New York in 1980.")
CASE_20 = QuerySignals(positive_signals=["1950s", "set on Mars", "open ending"], genres=["Science Fiction", "Comedy"])


def test_case_20_metadata_verifies_or_contradicts_and_endings_stay_unverifiable() -> None:
    statuses = _statuses(constraint_report(CASE_20, [CONQUEST, JUST_IMAGINE]))

    assert statuses[("1950s", "Conquest of Space (1955)")] == "verified"
    assert statuses[("1950s", "Just Imagine (1930)")] == "contradicted"
    assert statuses[("set on Mars", "Conquest of Space (1955)")] == "probable"
    assert statuses[("set on Mars", "Just Imagine (1930)")] == "not_verifiable"
    assert statuses[("Comedy", "Conquest of Space (1955)")] == "contradicted"
    assert statuses[("Comedy", "Just Imagine (1930)")] == "verified"
    assert statuses[("open ending", "Conquest of Space (1955)")] == "not_verifiable"


def test_missing_metadata_is_not_verifiable_and_no_signals_means_no_report() -> None:
    bare = _chunk("Senza dati", None, "", "")
    statuses = _statuses(constraint_report(QuerySignals(positive_signals=["1950s"], genres=["Comedy"]), [bare]))

    assert set(statuses.values()) == {"not_verifiable"}
    assert constraint_report(QuerySignals(), [bare]) == {}


def test_case_20_a_japanese_character_does_not_make_a_japanese_film() -> None:
    """Real run: Conquest of Space (USA) has a Japanese crew member in its plot."""
    conquest = _chunk("Conquest of Space", 1955, "Science Fiction", "Sergeant Imoto, the Japanese crewman, prays.")
    statuses = _statuses(constraint_report(QuerySignals(positive_signals=["Japanese"]), [conquest]))

    assert statuses[("Japanese", "Conquest of Space (1955)")] == "not_verifiable"


def test_case_13_the_cited_title_is_excluded_by_title_not_by_plot() -> None:
    """Real run: 'Mare dentro' as a hard exclusion was reported as a plot constraint."""
    mother = _chunk("Mother and Son", 1997, "Drama", "A son cares for his dying mother.")
    sea = _chunk("Mare dentro", 2004, "Drama", "Ramón fights for the right to die.")
    report = constraint_report(QuerySignals(hard_exclusions=["Mare dentro"]), [mother, sea])

    [check] = report["checks"]
    assert check["type"] == "title_exclusion"
    assert check["results"]["Mother and Son (1997)"]["status"] == "verified"
    assert check["results"]["Mare dentro (2004)"]["status"] == "contradicted"


def test_case_20_a_signal_repeating_a_genre_gets_no_second_status() -> None:
    """Real case 20 (v4): "comedy" as signal and "Comedy" as genre gave two conflicting lines."""
    conquest = _chunk("Conquest of Space", 1955, "Science Fiction; Drama", "The first mission to Mars.")
    signals = QuerySignals(positive_signals=["comedy", "science fiction", "set on Mars"], genres=["Science Fiction", "Comedy"])

    checks = constraint_report(signals, [conquest])["checks"]

    assert [(c["type"], c["constraint"]) for c in checks] == [
        ("genre", "Science Fiction"), ("genre", "Comedy"), ("plot_require", "set on Mars")]
    assert checks[1]["results"]["Conquest of Space (1955)"]["status"] == "contradicted"
