"""Offline tests of the Phase 0 scanner with invented wikitext (no dump, no network)."""
from __future__ import annotations

import io
import json

import pytest

from tool.RAGWikipediaSeries.common import Page
from tool.RAGWikipediaSeries.phase0 import scan_dump as sd


def page(title, text, *, ns=0, redirect=False, pid=1):
    return Page(page_id=pid, title=title, namespace=ns, redirect=redirect, revision_id="9", timestamp="t", text=text)


SERIES = """{{Fictiontv
|titoloitaliano=Serie Finta
|stagioni=2
}}
La serie finta racconta [[Mario Rossi]] e [[Anna Neri]].
== Trama ==
Una trama inventata.
=== Prima stagione ===
Dettagli.
== Episodi ==
{| class="wikitable"
|-
| 1 || Pilota
|-
| 2 || Secondo
|}
[[Categoria:Serie televisive italiane]]
[[Categoria:Film del 1999]]
"""


def test_series_page_yields_signals():
    row = sd.page_row(page("Serie finta", SERIES))
    assert row["tpl_kw"] == ["fictiontv"]
    assert row["params"]["stagioni"] == "2"
    assert row["cats_kw"] == ["Serie televisive italiane"]
    assert row["cats_n"] == 2
    assert row["table_rows"] == 2
    assert row["lead_links"][:2] == ["Mario Rossi", "Anna Neri"]
    sizes = {title: size for _, title, size in row["sections"]}
    assert sizes["Trama"] > sizes["Prima stagione"] > 0


def test_plain_article_has_no_row():
    assert sd.page_row(page("Roma", "{{Divisione amministrativa}} Capitale. [[Categoria:Comuni del Lazio]]")) is None


def test_title_patterns_alone_are_a_signal():
    row = sd.page_row(page("Lista degli episodi di X", "Testo senza template."))
    assert "episodes_of" in row["title_sig"]


def test_disambiguation_flag_and_first_templates():
    row = sd.page_row(page("Ponte (serie televisiva)", "{{Disambigua}}\n{{Fictiontv}}\n"))
    assert row["has_disambig"] is True
    assert row["tpl_first"][:2] == ["disambigua", "fictiontv"]


def test_redirect_row_requires_signal():
    assert sd.redirect_row(page("Foo", "#REDIRECT [[Bar]]", redirect=True)) is None
    row = sd.redirect_row(page("Foo", "#REDIRECT [[Bar (serie televisiva)]]", redirect=True))
    assert row["target"] == "Bar (serie televisiva)"


def test_other_namespaces():
    name, row = sd.other_namespace_row(page("Template:Episodio serie TV", "{{documentazione}}", ns=10))
    assert name == "templates" and row["title"].endswith("serie TV")
    name, row = sd.other_namespace_row(page("Categoria:Episodi di Serie Finta", "[[Categoria:Episodi di serie televisive]]", ns=14))
    assert name == "categories" and row["parents"] == ["Episodi di serie televisive"]
    assert sd.other_namespace_row(page("Template:Navbox", "x", ns=10)) is None


def test_scan_writes_atomically_and_counts(tmp_path):
    pages = iter([
        page("Serie finta", SERIES, pid=1),
        page("Roma", "Capitale.", pid=2),
        page("Foo", "#REDIRECT [[Serie finta (serie televisiva)]]", redirect=True, pid=3),
        page("Template:Episodio serie TV", "x", ns=10, pid=4),
    ])
    summary = sd.scan(pages, tmp_path)
    assert summary["pages_seen"] == 4 and summary["ns0_articles"] == 2 and summary["redirects"] == 1
    assert summary["rows"] == {"pages": 1, "redirects": 1, "templates": 1}
    assert not list(tmp_path.glob("*.part"))
    rows = [json.loads(line) for line in (tmp_path / "scan_pages.jsonl").read_text().splitlines()]
    assert rows[0]["title"] == "Serie finta"
    assert summary["kw_template_pages"] == {"fictiontv": 1}
