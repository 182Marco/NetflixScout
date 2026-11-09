"""Builds a tiny pages-articles dump (bz2) for the tests; page texts come from small snippets."""
from __future__ import annotations

import bz2
from xml.sax.saxutils import escape

NS = "http://www.mediawiki.org/xml/export-0.11/"
PLOT = "== Trama ==\n" + " ".join(f"Frase narrativa numero {i} con Anna e Mario a Roma." for i in range(30)) + "\n"
FILM = "{{Film\n|titolo originale = Original %s\n|anno uscita = 1999\n|durata = 100 min\n|regista = [[Anna Bianchi]]\n|genere = Drammatico\n}}\n"

PAGES = [
    (1, 0, "Film Uno", FILM % "Uno" + "Intro.\n" + PLOT + "[[Categoria:Film del 1999]]", False),
    (2, 0, "Rinvio", "#REDIRECT [[Film Uno]]", True),
    (3, 0, "Film (disambigua)", "{{Disambigua}}\n* [[Film Uno]]", False),
    (4, 0, "Filmografia di Anna Bianchi", FILM % "X" + PLOT, False),
    (5, 0, "Film Senza Trama", FILM % "Y" + "Intro.\n== Produzione ==\nTesto.", False),
    (6, 0, "Una città", "{{Divisione amministrativa|nome=Roma}}\n" + PLOT, False),
    (7, 1, "Discussione:Film Uno", FILM % "Z" + PLOT, False),
    (8, 0, "Film Due", FILM % "Due" + "Intro.\n" + PLOT, False),
    (9, 0, "Senza Infobox", "Testo.\n" + PLOT + "[[Categoria:Film d'animazione]]", False),
]


def build_xml(pages=PAGES) -> bytes:
    out = [f'<mediawiki xmlns="{NS}" version="0.11"><siteinfo><sitename>Wikipedia</sitename></siteinfo>']
    for page_id, ns, title, text, redirect in pages:
        out.append(
            f"<page><title>{escape(title)}</title><ns>{ns}</ns><id>{page_id}</id>"
            + ('<redirect title="Film Uno" />' if redirect else "")
            + f'<revision><id>{page_id * 100}</id><timestamp>2026-10-01T10:00:00Z</timestamp>'
            f'<text xml:space="preserve">{escape(text)}</text></revision></page>'
        )
    out.append("</mediawiki>")
    return "".join(out).encode("utf-8")


def write_dump(path, pages=PAGES) -> None:
    path.write_bytes(bz2.compress(build_xml(pages)))
