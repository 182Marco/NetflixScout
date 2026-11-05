from __future__ import annotations

from tool.RAGWikipediaSeries import tv_movies as tm


def _run(params, text="", plot=0, words=0, lead=0):
    return tm.classify(params, text, plot_chars=plot, plot_words=words, lead_chars=lead)


FULL = {"regista": "[[X]]", "attori": "* [[Y]]: Z", "genere": "drammatico"}


def test_narrative_needs_positive_evidence():
    assert _run(FULL)["class"] == tm.NARRATIVE
    assert _run({"genere": "drammatico"})["class"] == tm.UNCERTAIN  # nothing to decide on
    assert _run({"genere": "drammatico"}, plot=900, words=150)["class"] == tm.NARRATIVE


def test_documentary_and_shows_are_excluded_with_reason():
    out = _run({**FULL, "genere": "documentario"})
    assert out["class"] == tm.NON_NARRATIVE and out["reasons"][0] == "genre:documentario"
    out = _run(FULL, text="[[Categoria:Film documentari italiani]]")
    assert out["class"] == tm.NON_NARRATIVE


def test_musical_and_sport_are_narrative_not_shows():
    assert _run({**FULL, "genere": "musicale"})["class"] == tm.NARRATIVE
    assert _run({**FULL, "genere": "sportivo"})["class"] == tm.NARRATIVE
    assert _run({**FULL, "genere": "musica"})["class"] == tm.NON_NARRATIVE


def test_docudrama_mixed_genre_is_uncertain_never_forced():
    out = _run({**FULL, "genere": "documentario", "genere 2": "drammatico"})
    assert out["class"] == tm.UNCERTAIN and out["reasons"] == ["docudrama_mixed_genre"]


def test_html_comments_in_template_placeholders_do_not_count():
    params = {"regista": "<!--regista-->", "attori": "<!--cast-->", "genere": "drammatico"}
    assert _run(params)["class"] == tm.UNCERTAIN
