from pathlib import Path

from tool.RAGWikipediaFilm.clean_plot import clean_wikitext, extract_plot, normalize_heading

FIX = Path(__file__).parent / "fixtures"
HEADINGS = ["trama", "plot", "sinossi"]


def _plot(text, min_chars=20, min_words=5):
    return extract_plot(text, headings=HEADINGS, min_chars=min_chars, min_words=min_words)


def test_markup_is_removed_but_narrative_parentheses_survive():
    result = _plot((FIX / "plot_markup.wiki").read_text(encoding="utf-8"))
    assert result.reason == "ok" and result.heading == "Trama"
    text = result.text
    assert "(interpretato da un attore sconosciuto)" in text  # narrative parenthesis kept
    for junk in ("<ref", "Cita libro", "Senza fonte", "commento nascosto", "File:", "thumb", "wikitable",
                 "cella", "citazione da scartare", "[[", "]]", "{{", "''", "Cinecittà", "&nbsp;", "()"):
        assert junk not in text, junk
    assert "il giovane Mario (interpretato da un attore sconosciuto) arriva a Roma. Incontra" in text  # piped link, ref gone
    assert "di campagna" in text  # inline template text kept
    assert "la città partenopea" in text
    assert "Alla fine ritorna a casa sua, dove lo aspetta Anna." in text  # subsection kept, spacing fixed


def test_paragraph_split_and_order_preserved():
    text = _plot((FIX / "plot_markup.wiki").read_text(encoding="utf-8")).text
    paragraphs = text.split("\n\n")
    assert len(paragraphs) >= 3
    assert text.index("Anna, che lo ospita") < text.index("padre") < text.index("Alla fine")


def test_real_article_fixture():
    wikitext = (FIX / "il_padrino.wiki").read_text(encoding="utf-8")
    result = _plot(wikitext, min_chars=400, min_words=60)
    assert result.reason == "ok"
    assert "New York, 1945." in result.text and "Vito Corleone" in result.text
    assert "Testo di produzione" not in result.text and "Nota di prova" not in result.text


def test_missing_and_short_plots():
    assert _plot("Solo introduzione.\n== Produzione ==\nTesto.").reason == "no_plot_section"
    short = _plot("== Trama ==\nBreve.", min_chars=100, min_words=20)
    assert short.reason == "plot_too_short"


def test_heading_variants_and_multiple_sections():
    text = "== Plot ==\nTesto uno uno uno uno uno.\n== Altro ==\nx\n== Sinossi ==\nTesto due due due due due."
    result = _plot(text)
    assert result.heading == "Plot" and "multiple_plot_sections" in result.flags
    assert normalize_heading("  Trama: ") == "trama"


def test_clean_wikitext_is_idempotent_on_plain_text():
    assert clean_wikitext("Anna [[Roma|Roma]] parte.") == "Anna Roma parte."
    once = clean_wikitext("Anna   parte .")
    assert clean_wikitext(once) == once == "Anna parte."
