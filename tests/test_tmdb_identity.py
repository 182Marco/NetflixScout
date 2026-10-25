"""Identity of movies and series: no attribution without a verified title and year.

Offline: fake transport, no `.env`. Regression for "The Sinner" (1950, West Germany),
once matched to "The Sinners" / "Au royaume des cieux" (1949, Duvivier).
"""
from __future__ import annotations

import pytest
from tmdb_support import make_tool, run, tmdb_meta

from tool.tmdb.enrich import ENRICHMENT_KEY, TmdbRagEnricher, titles_match, years_match
from tool.tmdb.models.results import Entity
from tool.tmdb.normalize.common import positive_minutes, strict_name
from tool.tmdb.normalize.entities import FacetOptions, movie, tv

SEARCH = "/search/movie"


def _result(movie_id, title, year, original=None, popularity=10):
    return {"id": movie_id, "title": title, "original_title": original or title,
            "release_date": f"{year}-03-01" if year else "", "popularity": popularity}


def _details(movie_id, title, year, director, *, original=None, runtime=100):
    return {
        "id": movie_id, "title": title, "original_title": original or title, "original_language": "en",
        "release_date": f"{year}-03-01", "runtime": runtime, "overview": f"Trama di {title}.",
        "vote_average": 6.0, "vote_count": 10, "translations": {"translations": []},
        "credits": {"cast": [{"name": f"Cast di {title}", "character": "x", "order": 0}],
                    "crew": [{"name": director, "job": "Director"}]},
    }


def _enrich(chunks, search_results, details):
    routes = {f"/movie/{d['id']}": d for d in details}
    routes[SEARCH] = lambda params: {"results": search_results.get(params["query"], [])}
    tool, transport = make_tool(routes)
    rag_result = {"query": "q", "chunks": chunks, "metadata": {}, "trace": []}
    result = TmdbRagEnricher(tool=tool, max_candidates=3).enrich(tool_result=rag_result)
    return result["metadata"][ENRICHMENT_KEY]["candidates"], transport


def _chunk(title, year):
    return {"id": title, "testo": "plot", "score": 0.5, "title": title, "release_year": str(year) if year else None}


SINNERS = _result(147801, "The Sinners", 1949, original="Au royaume des cieux", popularity=50)


def test_the_sinner_is_not_matched_to_the_sinners() -> None:
    rows, transport = _enrich(
        [_chunk("The Sinner", 1950)],
        {"The Sinner": [SINNERS]},
        [_details(147801, "The Sinners", 1949, "Julien Duvivier", original="Au royaume des cieux")],
    )

    assert rows[0]["status"] == "unverified" and rows[0]["reason"] == "title_mismatch"
    assert "tmdb" not in rows[0]
    # One details call checks the work's alternative titles; "The Sinner" is not among them.
    assert transport.paths.count("/movie/147801") == 1


def test_containment_never_matches_a_title() -> None:
    entity = Entity(kind="movie", tmdb_id=1, title="The Sinners", original_title="Au royaume des cieux", year=1949)

    assert not titles_match("The Sinner", entity)
    assert titles_match("the  sinners!", entity)  # case, spaces and punctuation are ignored
    assert titles_match("Au Royaume des Cieux", entity)


def test_accents_are_a_difference_when_an_accented_title_exists() -> None:
    assert strict_name("Dűne") != strict_name("Dune")
    assert strict_name("  Amélie!  ") == strict_name("amélie")


def test_same_title_with_a_different_year_is_not_attributed() -> None:
    rows, _ = _enrich(
        [_chunk("Dune", 1984)],
        {"Dune": [_result(438631, "Dune", 2021, popularity=99)]},
        [_details(438631, "Dune", 2021, "Denis Villeneuve")],
    )

    assert rows[0]["status"] == "unverified" and rows[0]["reason"] == "year_mismatch"
    assert "tmdb" not in rows[0]


def test_original_title_is_a_valid_match() -> None:
    rows, _ = _enrich(
        [_chunk("Rocco e i suoi fratelli", 1960)],
        {"Rocco e i suoi fratelli": [_result(8422, "Rocco and His Brothers", 1960, original="Rocco e i suoi fratelli")]},
        [_details(8422, "Rocco and His Brothers", 1960, "Luchino Visconti", original="Rocco e i suoi fratelli")],
    )

    assert rows[0]["status"] == "matched" and rows[0]["tmdb"]["directors"] == ["Luchino Visconti"]


def test_ambiguous_exact_titles_without_a_year_are_refused_in_the_enrichment() -> None:
    rows, transport = _enrich(
        [_chunk("Parasite", None)],
        {"Parasite": [_result(496243, "Parasite", 2019, popularity=99), _result(291545, "Parasite", 2004, popularity=3)]},
        [_details(496243, "Parasite", 2019, "Bong Joon-ho"), _details(291545, "Parasite", 2004, "Altro")],
    )

    assert rows[0]["status"] == "unverified" and rows[0]["reason"] == "ambiguous"
    assert not any(path.startswith("/movie/") for path in transport.paths)


def test_metadata_of_one_candidate_never_reaches_another() -> None:
    rows, _ = _enrich(
        [_chunk("The Sinner", 1950), _chunk("Arrival", 2016)],
        {"The Sinner": [SINNERS], "Arrival": [_result(329865, "Arrival", 2016)]},
        [_details(147801, "The Sinners", 1949, "Julien Duvivier"), _details(329865, "Arrival", 2016, "Denis Villeneuve")],
    )

    assert "tmdb" not in rows[0]
    assert rows[1]["tmdb"]["directors"] == ["Denis Villeneuve"]
    assert "Julien Duvivier" not in str(rows)


def test_year_is_verified_only_with_data_that_exists() -> None:
    assert years_match(None, 1990) and years_match(1950, 1951)
    assert not years_match(1950, 1948)
    assert not years_match(1950, None)  # a known RAG year cannot be confirmed by a missing TMDb year


# --- tmdb_search: same rules, alternatives reported, localized titles kept ----------------


def test_a_title_that_does_not_match_is_not_attributed() -> None:
    tool, transport = make_tool({SEARCH: {"results": [_result(157336, "Interstellar", 2014, popularity=100)]}})

    result = run(tool, {"operation": "movie_details", "title": "Il Mistero del Faro Capovolto"}, language="it")

    request = tmdb_meta(result)["requests"][0]
    assert request["error"] == "unverified_match" and request["notes"] == ["title_mismatch"]
    assert request["candidates"] == [{"tmdb_id": 157336, "title": "Interstellar", "year": 2014}]
    assert result["chunks"] == []
    # Nothing exact in Italian or English: the lone result is checked once, no data attributed.
    assert transport.paths == [SEARCH, SEARCH, "/movie/157336"] and transport.calls[1][1]["language"] == "en-US"


def test_localized_title_is_matched_in_the_turn_language() -> None:
    amelie = _result(194, "Il favoloso mondo di Amélie", 2001, original="Le Fabuleux Destin d'Amélie Poulain")
    tool, transport = make_tool({SEARCH: {"results": [amelie]},
                                 "/movie/194": _details(194, "Il favoloso mondo di Amélie", 2001, "Jean-Pierre Jeunet")})

    result = run(tool, {"operation": "movie_details", "title": "Il favoloso mondo di Amelie"}, language="it")

    assert result["chunks"][0]["tmdb_id"] == 194
    assert transport.paths == [SEARCH, "/movie/194"]


def test_english_title_in_an_italian_turn_is_verified_with_an_english_search() -> None:
    def search(params):
        if params["language"] == "it-IT":
            return {"results": [_result(129, "La città incantata", 2001, original="千と千尋の神隠し")]}
        return {"results": [_result(129, "Spirited Away", 2001, original="千と千尋の神隠し")]}

    tool, transport = make_tool({SEARCH: search, "/movie/129": _details(129, "La città incantata", 2001, "Hayao Miyazaki")})

    result = run(tool, {"operation": "movie_details", "title": "Spirited Away"}, language="it")

    assert result["chunks"][0]["tmdb_id"] == 129
    assert transport.paths == [SEARCH, SEARCH, "/movie/129"]


def test_requested_year_without_a_matching_version_is_not_replaced() -> None:
    solaris_2002 = _details(1, "Solaris", 2002, "Steven Soderbergh")
    solaris_2002["release_dates"] = {"results": [{"iso_3166_1": "US", "release_dates": [{"release_date": "2002-11-27T00:00:00.000Z"}]}]}
    tool, transport = make_tool({SEARCH: {"results": [_result(1, "Solaris", 2002, popularity=90)]}, "/movie/1": solaris_2002})

    result = run(tool, {"operation": "movie_details", "title": "Solaris", "year": 1972})

    request = tmdb_meta(result)["requests"][0]
    assert request["error"] == "unverified_match" and request["notes"] == ["year_mismatch"]
    assert result["chunks"] == []
    # One details call checks the recorded release dates: none is 1972 ±1.
    assert transport.paths.count("/movie/1") == 1


def test_explicit_versions_still_pick_one_and_report_the_others() -> None:
    results = [_result(438631, "Dune", 2021, popularity=99), _result(841, "Dune", 1984, popularity=20),
               _result(697620, "Dűne", 2020, popularity=1)]
    tool, _ = make_tool({SEARCH: {"results": results}, "/movie/438631": _details(438631, "Dune", 2021, "Denis Villeneuve")})

    result = run(tool, {"operation": "movie_details", "title": "Dune"})

    request = tmdb_meta(result)["requests"][0]
    assert result["chunks"][0]["tmdb_id"] == 438631
    # "Dűne" is a different title once an exact "Dune" exists.
    assert request["candidates"] == [{"tmdb_id": 841, "title": "Dune", "year": 1984}]


# --- runtimes (D9) and series details (D10) -------------------------------------------


@pytest.mark.parametrize(("value", "expected"), [(0, None), (None, None), ("", None), ("120", None),
                                                  (True, None), (-5, None), (120, 120), (89.0, 89)])
def test_positive_minutes(value, expected) -> None:
    assert positive_minutes(value) == expected


OPTIONS = FacetOptions(facets=(), region="IT", api_language="it-IT", limit=5)


@pytest.mark.parametrize("runtime", [0, None, ""])
def test_unknown_runtime_never_reaches_the_model(runtime) -> None:
    entity = movie(_details(1, "Exit", 2010, "X", runtime=runtime), OPTIONS)
    rows, _ = _enrich([_chunk("Exit", 2010)], {"Exit": [_result(1, "Exit", 2010)]}, [_details(1, "Exit", 2010, "X", runtime=runtime)])

    assert "runtime_minutes" not in entity.essentials
    assert "runtime_minutes" not in rows[0]["tmdb"]


def test_positive_runtime_is_kept() -> None:
    rows, _ = _enrich([_chunk("Exit", 2010)], {"Exit": [_result(1, "Exit", 2010)]}, [_details(1, "Exit", 2010, "X", runtime=95)])

    assert rows[0]["tmdb"]["runtime_minutes"] == 95


def _series(**extra):
    return {"id": 68595, "name": "Planet Earth II", "original_name": "Planet Earth II", "original_language": "en",
            "first_air_date": "2016-11-06", "number_of_seasons": 1, "number_of_episodes": 6, **extra}


def test_series_episode_runtime_only_when_tmdb_lists_it() -> None:
    assert "episode_runtime_minutes" not in tv(_series(episode_run_time=[]), OPTIONS).essentials
    assert "episode_runtime_minutes" not in tv(_series(), OPTIONS).essentials
    assert tv(_series(episode_run_time=[50, 0]), OPTIONS).essentials["episode_runtime_minutes"] == [50]
    assert "directors" not in tv(_series(), OPTIONS).essentials  # never invented for a series


# --- alternative and translated titles of the same work (D1 false negatives) ----------------


def _three(cast=("Kelly Brook", "Billy Zane"), alternative=("Survival Island",), year=2005, movie_id=9753, title="Three"):
    """Shape of the real TMDb record of "Three" (2005), released in the US as "Survival Island"."""
    payload = _details(movie_id, title, year, "Stewart Raffill")
    payload["credits"]["cast"] = [{"name": name, "character": "x", "order": i} for i, name in enumerate(cast)]
    payload["alternative_titles"] = {"titles": [{"iso_3166_1": "US", "title": t} for t in alternative]}
    payload["translations"] = {"translations": [
        {"iso_639_1": "it", "data": {"title": "L'isola dei sopravvissuti"}},
        {"iso_639_1": "de", "data": {"title": "Gestrandet im Paradies"}},
    ]}
    return payload


SURVIVAL = {"cast": "Kelly Brook; Juan Pablo Di Pace; Billy Zane", **_chunk("Survival Island", 2006)}


def test_survival_island_is_recovered_through_the_same_works_alternative_title() -> None:
    rows, transport = _enrich([SURVIVAL], {"Survival Island": [_result(9753, "Three", 2005)]}, [_three()])

    assert rows[0]["status"] == "matched" and rows[0]["matched_by"] == "alternative_title"
    assert rows[0]["tmdb"]["title"] == "Three" and rows[0]["tmdb"]["directors"] == ["Stewart Raffill"]
    # The verification call is the details call: no second request for the same work.
    assert transport.paths == [SEARCH, "/movie/9753"]


def test_alternative_title_with_a_different_cast_is_refused() -> None:
    rows, _ = _enrich([SURVIVAL], {"Survival Island": [_result(9753, "Three", 2005)]}, [_three(cast=("Altro Attore",))])

    assert rows[0]["status"] == "unverified" and rows[0]["reason"] == "cast_mismatch" and "tmdb" not in rows[0]


def test_alternative_title_outside_the_year_range_is_not_checked() -> None:
    rows, transport = _enrich([SURVIVAL], {"Survival Island": [_result(9753, "Three", 2010)]}, [_three(year=2010)])

    assert rows[0]["status"] == "unverified" and rows[0]["reason"] == "title_mismatch"
    assert "/movie/9753" not in transport.paths


def test_two_works_with_the_same_alternative_title_are_ambiguous() -> None:
    rows, _ = _enrich(
        [SURVIVAL],
        {"Survival Island": [_result(9753, "Three", 2005), _result(1, "Island", 2006)]},
        [_three(), _three(movie_id=1, title="Island", year=2006)],
    )

    assert rows[0]["status"] == "unverified" and rows[0]["reason"] == "ambiguous" and "tmdb" not in rows[0]


def test_follow_up_in_italian_finds_the_movie_by_its_english_alternative_title() -> None:
    """Case 14 follow-up: "Survival Island (2006)" asked in an Italian turn."""
    def search(params):
        title = "L'isola dei sopravvissuti" if params["language"] == "it-IT" else "Three"
        return {"results": [_result(9753, title, 2005)]}

    tool, transport = make_tool({SEARCH: search, "/movie/9753": _three()})

    result = run(tool, {"operation": "movie_details", "title": "Survival Island", "year": 2006}, language="it")

    request = tmdb_meta(result)["requests"][0]
    assert result["chunks"][0]["tmdb_id"] == 9753
    assert request["notes"] == ["alternative_title_match"]
    assert request["entities"]["movie:9753"]["essentials"]["directors"] == ["Stewart Raffill"]
    assert transport.paths == [SEARCH, SEARCH, "/movie/9753"]


def test_translated_title_of_the_same_work_is_accepted() -> None:
    tool, _ = make_tool({SEARCH: {"results": [_result(9753, "Three", 2005)]}, "/movie/9753": _three()})

    result = run(tool, {"operation": "movie_details", "title": "Gestrandet im Paradies"})

    assert result["chunks"][0]["tmdb_id"] == 9753


def test_the_sinners_record_does_not_list_the_sinner() -> None:
    """Real TMDb data of movie 147801: alternative title 'Woman Hunt', translations 'The Sinners'."""
    sinners = _details(147801, "The Sinners", 1949, "Julien Duvivier", original="Au royaume des cieux")
    sinners["alternative_titles"] = {"titles": [{"iso_3166_1": "US", "title": "Woman Hunt"}]}
    sinners["translations"] = {"translations": [{"iso_639_1": "en", "data": {"title": "The Sinners"}},
                                                {"iso_639_1": "de", "data": {"title": "Eine Heilige unter Sünderinnen"}}]}
    rows, _ = _enrich([_chunk("The Sinner", 1950)], {"The Sinner": [SINNERS]}, [sinners])

    assert rows[0]["status"] == "unverified" and "tmdb" not in rows[0]


# --- variants backed by TMDb data: secondary release dates, leading article, "&" ------------


def _harrow(cast=("Russ Harvey", "Helen Hogan", "Eunice Grey"), years=("1962", "1964")):
    """Real TMDb record 37522: primary date 1964, a release date in 1962; no alternative titles."""
    payload = _details(37522, "The Dungeon of Harrow", 1964, "Pat Boyette")
    payload["release_date"] = "1964-02-01"
    payload["credits"]["cast"] = [{"name": name, "character": "x", "order": i} for i, name in enumerate(cast)]
    payload["alternative_titles"] = {"titles": []}
    payload["release_dates"] = {"results": [{"iso_3166_1": "US", "release_dates": [{"release_date": f"{y}-01-01T00:00:00.000Z"} for y in years]}]}
    return payload


HARROW_CHUNK = {"cast": "Russ Harvey; Helen Hogan; Lee Morgan; Eunice Grey", **_chunk("Dungeon of Harrow", 1962)}


def test_leading_article_and_secondary_release_year_identify_the_same_work() -> None:
    rows, transport = _enrich([HARROW_CHUNK], {"Dungeon of Harrow": [_result(37522, "The Dungeon of Harrow", 1964)]}, [_harrow()])

    assert rows[0]["status"] == "matched" and rows[0]["matched_by"] == "alternative_title"
    assert rows[0]["year_note"] == "release_date" and rows[0]["tmdb"]["directors"] == ["Pat Boyette"]
    assert transport.paths == [SEARCH, "/movie/37522"]


def test_leading_article_without_a_recorded_compatible_year_stays_unverified() -> None:
    rows, _ = _enrich([HARROW_CHUNK], {"Dungeon of Harrow": [_result(37522, "The Dungeon of Harrow", 1964)]},
                      [_harrow(years=("1964",))])

    assert rows[0]["status"] == "unverified" and "tmdb" not in rows[0]


def test_leading_article_with_a_different_cast_stays_unverified() -> None:
    rows, _ = _enrich([HARROW_CHUNK], {"Dungeon of Harrow": [_result(37522, "The Dungeon of Harrow", 1964)]},
                      [_harrow(cast=("Altri", "Attori"))])

    assert rows[0]["status"] == "unverified" and rows[0]["reason"] == "cast_mismatch"


def test_ampersand_reads_and_but_a_different_word_does_not_match() -> None:
    mars = _details(177117, "Mars and April", 2012, "Martin Villeneuve", original="Mars et Avril")
    mars["credits"]["cast"] = [{"name": "Caroline Dhavernas", "character": "x", "order": 0}]
    mars["alternative_titles"] = {"titles": [{"iso_3166_1": "CA", "title": "Mars & Avril"}]}
    chunk = {"cast": "Paul Ahmarani; Caroline Dhavernas", **_chunk("Mars and Avril", 2012)}

    rows, _ = _enrich([chunk], {"Mars and Avril": [_result(177117, "Mars and April", 2012, original="Mars et Avril")]}, [mars])
    april = Entity(kind="movie", tmdb_id=1, title="Mars and April", original_title="Mars et Avril", year=2012)

    assert rows[0]["status"] == "matched" and rows[0]["tmdb"]["directors"] == ["Martin Villeneuve"]
    assert not titles_match("Mars and Avril", april)  # "April" is not "Avril"


def test_article_rule_never_turns_into_containment() -> None:
    """"The Sinner" vs "The Sinners": still different after dropping the article."""
    from tool.tmdb.normalize.common import article_free_name

    assert article_free_name("The Sinner") != article_free_name("The Sinners")
    assert article_free_name("The") == "the"  # a one-word title keeps its only word



def test_without_a_year_unrelated_titles_are_not_checked() -> None:
    """Real case 2 (v4): tv "Dune" checked "Dune: Prophecy" and "I figli di Dune" for nothing."""
    tool, transport = make_tool({"/search/tv": {"results": [
        {"id": 90228, "name": "Dune: Prophecy", "original_name": "Dune: Prophecy", "first_air_date": "2024-11-17"},
        {"id": 9156, "name": "I figli di Dune", "original_name": "Children of Dune", "first_air_date": "2003-03-16"},
    ]}})

    result = run(tool, {"operation": "tv_details", "title": "Dune"}, language="it")

    assert tmdb_meta(result)["requests"][0]["error"] == "unverified_match"
    assert not any(path.startswith("/tv/") for path in transport.paths)
    assert transport.paths == ["/search/tv", "/search/tv"]
