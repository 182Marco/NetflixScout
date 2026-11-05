"""Classification of TV-movie candidates (FictionTV `tipo fiction` = film TV), pure functions.

`tv_movie` is an autonomous work type (never linked to seasons or episodes). A candidate is kept as
narrative only on positive evidence; documentaries, shows, concerts and the like are excluded with a
reason, and everything the data cannot decide is `uncertain` (kept apart, never forced).
"""
from __future__ import annotations

import re

NARRATIVE = "tv_movie"
NON_NARRATIVE = "non_narrative"
UNCERTAIN = "uncertain"

# Genre words (infobox `genere`, `genere 2`, `genere 3`) that mean "not a fictional narrative".
NON_NARRATIVE_GENRES = (
    "documentar", "talk", "varietà", "varieta", "concerto", "spettacolo", "reality", "quiz",
    "rubrica", "cabaret", "stand-up", "stand up", "intrattenimento", "mockumentary", "docufiction",
    "telegiornale", "cerimonia",
)
# Exact genre values (substring matching would catch "musicale", "sportivo", "televisivo"): musical and
# sports films are narrative.
NON_NARRATIVE_EXACT = ("musica", "sport", "televisivo", "show", "speciale")
# Wikipedia categories that settle the case without reading the text.
NON_NARRATIVE_CATEGORIES = (
    "film documentari", "documentari", "spettacoli teatrali", "film concerto", "film-concerto",
    "programmi televisivi", "concerti", "speciali televisivi", "cerimonie",
)
NARRATIVE_CATEGORY_HINTS = (
    "per la televisione", "film drammatici", "film commedia", "film thriller", "film horror",
    "film di fantascienza", "film sentimentali", "film basati su", "film d'azione", "film gialli",
)
CATEGORY_RE = re.compile(r"\[\[\s*categoria\s*:\s*([^\]|]+)", re.I)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
LINK_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")


def clean_param(value: str | None) -> str:
    """Infobox value without comments and wiki links (`[[a|b]]` -> `b`)."""
    return " ".join(LINK_RE.sub(r"\1", COMMENT_RE.sub("", value or "")).split())


def genres_of(params: dict[str, str]) -> list[str]:
    out = []
    for key in ("genere", "genere 2", "genere 3"):
        value = clean_param(params.get(key)).lower()
        if value:
            out.append(value)
    return out


def categories_of(text: str) -> list[str]:
    return [c.strip().lower() for c in CATEGORY_RE.findall(text)]


def classify(params: dict[str, str], text: str, *, plot_chars: int, plot_words: int, lead_chars: int) -> dict:
    """Returns {class, reasons, evidence}. `class` is tv_movie | non_narrative | uncertain."""
    genres = genres_of(params)
    cats = categories_of(text)
    director = bool(clean_param(params.get("regista")))
    cast = bool(clean_param(params.get("attori")))
    writer = bool(clean_param(params.get("sceneggiatore")))
    has_plot = plot_chars >= 400 and plot_words >= 60
    reasons: list[str] = []
    bad_genre = [g for g in genres if g in NON_NARRATIVE_EXACT or any(w in g for w in NON_NARRATIVE_GENRES)]
    bad_cat = [c for c in cats if any(c == w or c.startswith(w) for w in NON_NARRATIVE_CATEGORIES)]
    good_cat = [c for c in cats if any(h in c for h in NARRATIVE_CATEGORY_HINTS)]
    evidence = {"genres": genres, "director": director, "cast": cast, "writer": writer,
                "plot": has_plot, "narrative_categories": len(good_cat), "bad_genre": bad_genre,
                "bad_categories": bad_cat[:3]}
    if bad_genre or bad_cat:
        # a narrative genre next to a documentary one (e.g. "drammatico" + "documentario") is a docudrama
        narrative_genres = [g for g in genres if g not in bad_genre]
        documentary_only = all("documentar" in g or "docufiction" in g for g in bad_genre) and not bad_cat
        if narrative_genres and (director and cast) and documentary_only:
            return {"class": UNCERTAIN, "reasons": ["docudrama_mixed_genre"], "evidence": evidence}
        return {"class": NON_NARRATIVE, "reasons": (["genre:" + g for g in bad_genre] + ["category:" + c for c in bad_cat[:2]]),
                "evidence": evidence}
    if (director and cast) or has_plot or (cast and good_cat):
        if has_plot:
            reasons.append("plot")
        if director and cast:
            reasons.append("director_and_cast")
        if good_cat:
            reasons.append("narrative_category")
        return {"class": NARRATIVE, "reasons": reasons, "evidence": evidence}
    return {"class": UNCERTAIN, "reasons": ["insufficient_evidence"], "evidence": evidence}
