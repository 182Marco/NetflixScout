"""Offline tests of the pure functions of the Phase 0 analyses (invented wikitext)."""
from __future__ import annotations

import random

from pipelines.wikipedia_series.phase0 import analyze_seasons as seasons
from pipelines.wikipedia_series.phase0 import analyze_series as series
from pipelines.wikipedia_series.phase0 import bench_lexical as bench
from pipelines.wikipedia_series.phase0 import build_units as units
from pipelines.wikipedia_series.phase0 import harvest, wikidata_sample

SERIES_PAGE = "{{FictionTV\n|tipo fiction = miniserie tv <!-- scegliere -->\n|titolo = X\n}}\nLa serie X.\n== Trama ==\n" + "Una storia lunga. " * 40


def test_kind_of_reads_fiction_type_and_strips_comments():
    kind, params = series.kind_of(SERIES_PAGE)
    assert kind == "fiction:miniserie tv"
    assert params["titolo"] == "X"


def test_kind_of_animated_and_programme_and_other():
    anim = "{{Fumetto e animazione\n|tipo = anime\n|sottotipo = serie TV\n}}"
    assert series.kind_of(anim)[0] == "anim:anime/serie tv"
    assert series.kind_of("{{Programma\n|titolo=Q\n}}")[0] == "programma"
    assert series.kind_of("Testo semplice")[0] == "other"


def test_series_kinds_exclude_tv_films_and_manga():
    assert units.is_series_kind("fiction:serie tv") and units.is_series_kind("fiction:webserie")
    assert not units.is_series_kind("fiction:film tv")
    assert not units.is_series_kind("anim:manga/?")
    assert units.is_series_kind("anim:anime/oav") and units.is_series_kind("programma")


def test_season_number_from_italian_ordinals():
    assert units.season_number("prima stagione") == 1
    assert units.season_number("dodicesima stagione") == 12
    assert units.season_number("3 stagione") == 3
    assert units.season_number("stagione speciale") is None


SEASON = """{{torna a|Serie finta}}
La prima stagione.

{| class="wikitable"
! nº !! Titolo
|-
| 1 || A
|-
| 2 || B
|}

==A==
""" + "Trama dell'episodio A. " * 20 + """
==B==
breve
==Note==
Testo di note.
"""


def test_season_analysis_counts_rows_and_prose_sections():
    a = seasons.analyze(SEASON)
    assert a["rows"] == 2
    assert a["ep_sections"] == 2  # "Note" is boilerplate
    assert a["ep_sections_with_prose"] == 1


def test_season_title_and_backlink_patterns():
    assert seasons.SEASON_TITLE.match("Episodi di Colombo (prima stagione)")
    assert not seasons.SEASON_TITLE.match("Episodi di Naruto")
    assert units.BACK.search(SEASON).group(1) == "Serie finta"
    m = units.TITLE.match("Episodi di Poldark (serie televisiva 1975) (seconda stagione)")
    assert m.group(1) == "Poldark (serie televisiva 1975)" and m.group(2) == "seconda stagione"


def test_harvest_selection_rules():
    row = {"tpl_kw": ["fictiontv"], "cats_kw": [], "title_sig": []}
    assert harvest.reasons(row) == ["tpl"]
    assert harvest.reasons({"tpl_kw": ["stagione squadra"], "cats_kw": ["Stagioni NBA"], "title_sig": []}) == []
    assert harvest.reasons({"tpl_kw": [], "cats_kw": ["Liste di episodi di serie televisive"], "title_sig": ["episodes_of"]}) == ["cat", "title_ep"]


def test_query_builder_drops_proper_nouns_and_is_deterministic():
    text = "Mario Rossi scopre che la moglie nasconde un segreto terribile nella vecchia casa di campagna. Fine."
    q1 = bench.query_from(text, random.Random(1))
    assert q1 and "Mario" not in q1 and "Rossi" not in q1
    assert q1 == bench.query_from(text, random.Random(1))


def test_sparql_literal_is_escaped():
    assert wikidata_sample.lit('A "B" \\ C') == '"A \\"B\\" \\\\ C"@it'
