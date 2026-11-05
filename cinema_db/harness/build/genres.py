"""Canonical genre vocabulary and the rules that map source labels to it. Pure: no I/O.

Source labels (Wikidata items in Italian/English, or plain catalogue text) are stored as they are in `genre_label`; this module
only decides which canonical genre(s) each one MEANS, with the kind of match and the rule, so every decision is auditable and a
label no rule recognises stays unmapped (still readable, never forced). Precision over recall: a rule is added only when its
reading is unambiguous. Kinds: exact (same concept), synonym (same concept, other wording), specific (narrower label, e.g.
"psychological thriller" -> thriller).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .common import normalize_name

# tokens dropped before comparing a label with a genre's exact/synonym forms ("film dell'orrore" -> "orrore")
_FILLER = frozenset("film cinema di d dell della del dei delle degli dello per a sul sui sulla the of genre movie movies".split())


@dataclass(frozen=True)
class Genre:
    code: str
    label_en: str
    label_it: str
    description: str
    parent: str | None = None
    exact: tuple[str, ...] = ()  # cores that mean exactly this genre
    synonyms: tuple[str, ...] = ()  # cores that mean the same in other words
    keywords: str = ""  # regex on the normalised label: a hit means "specific"


VOCABULARY: tuple[Genre, ...] = (
    Genre("action", "Action", "Azione", "Films driven by physical action, fights and chases.", exact=("azione", "action"), keywords=r"\baction\b|\bazione\b|d azione"),
    Genre("adventure", "Adventure", "Avventura", "Journeys, quests and exploits.", exact=("avventura", "adventure"), keywords=r"avventur|adventure|cappa e spada|swashbuckl|\bpirat|treasure|peplum|sword and sandal"),
    Genre("animation", "Animation", "Animazione", "Animated films and series.", exact=("animazione", "animation", "animated", "animato", "cartone animato", "animated cartoon"), keywords=r"animat|animazione|cartoon|cartone"),
    Genre("anime", "Anime", "Anime", "Japanese animation.", parent="animation", exact=("anime",), keywords=r"\banime\b|animazione giapponese|japanese animation"),
    Genre("biography", "Biography", "Biografico", "Films about the life of a real person.", exact=("biografico", "biographical", "biopic"), keywords=r"biograf|biopic"),
    Genre("comedy", "Comedy", "Commedia", "Films meant to amuse.", exact=("commedia", "comedy", "comico"), keywords=r"comm?edia|comedy|comico|umoristic|parodia|parody|satir"),
    Genre("black_comedy", "Black comedy", "Commedia nera", "Comedy about dark or taboo subjects.", parent="comedy", exact=("commedia nera", "black comedy"), keywords=r"commedia nera|black comedy"),
    Genre("romantic_comedy", "Romantic comedy", "Commedia romantica", "Comedy built around a love story.", parent="comedy", exact=("commedia romantica", "romantic comedy"), keywords=r"commedia romantica|romantic comedy|commedia sentimentale"),
    Genre("crime", "Crime", "Poliziesco", "Crime, investigation and the underworld.", exact=("poliziesco", "crime", "criminale"), synonyms=("giallo", "gangster"), keywords=r"poliziesc|\bcrime\b|giallo|gangster|heist|caper|detective"),
    Genre("documentary", "Documentary", "Documentario", "Non-fiction films.", exact=("documentario", "documentary"), keywords=r"document"),
    Genre("drama", "Drama", "Drammatico", "Serious narrative films.", exact=("drammatico", "drama", "dramma"), synonyms=("melodramma", "melodrama"), keywords=r"dramm|\bdrama\b|melodramm|melodrama"),
    Genre("family", "Family", "Per famiglie", "Films suitable for the whole family.", exact=("famiglie", "family", "famiglia"), keywords=r"famigli|\bfamily\b"),
    Genre("children", "Children's", "Per bambini", "Films aimed at children.", parent="family", exact=("bambini", "children s", "children", "kids"), keywords=r"bambin|children|infanzia"),
    Genre("fantasy", "Fantasy", "Fantasy", "Magic, myth and invented worlds.", exact=("fantasy", "fantastico"), keywords=r"fantasy|fantastic|fiaba|fairy tale|favol"),
    Genre("film_noir", "Film noir", "Film noir", "Dark, cynical crime stories in the noir tradition.", exact=("noir", "film noir", "neo noir"), keywords=r"\bnoir\b"),
    Genre("heist", "Heist", "Colpo grosso", "Stories of an organised robbery.", exact=("caper movie", "heist", "caper"), keywords=r"caper|heist"),
    Genre("historical", "Historical", "Storico", "Stories set in a real past.", exact=("storico", "historical", "historic"), keywords=r"storic|historic|medieval|medievale|period drama|d epoca"),
    Genre("horror", "Horror", "Horror", "Films meant to frighten.", exact=("horror", "orrore"), keywords=r"horror|orrore|splatter|slasher|zombie|vampir|fantasm|\bghost\b|satanic|monster|mostri|haunted|occult"),
    Genre("slasher", "Slasher", "Slasher", "A killer stalks and kills a group, in the horror tradition.", parent="horror", exact=("slasher",), keywords=r"slasher"),
    Genre("lgbtq", "LGBTQ-related", "Tematica LGBT", "Films about LGBTQ people or themes (a theme the sources list among genres).", exact=("lgbtq related", "tematica lgbt", "a tematica lgbt"), keywords=r"lgbt"),
    Genre("martial_arts", "Martial arts", "Arti marziali", "Fighting disciplines at the centre of the plot.", exact=("arti marziali", "martial arts"), keywords=r"arti marziali|martial arts|kung fu|wuxia"),
    Genre("musical", "Musical", "Musicale", "Songs and dance carry the story.", exact=("musicale", "musical"), keywords=r"musicale|\bmusical\b"),
    Genre("mystery", "Mystery", "Mistero", "A puzzle or enigma to solve.", exact=("mistero", "mystery"), synonyms=("giallo",), keywords=r"mister|mystery|giallo|detective|whodunit"),
    Genre("romance", "Romance", "Sentimentale", "Love stories.", exact=("sentimentale", "romance", "romantico", "romantic"), keywords=r"sentiment|romantic|romance|romantico"),
    Genre("science_fiction", "Science fiction", "Fantascienza", "Speculative science and technology.", exact=("fantascienza", "science fiction", "sci fi"), keywords=r"fantascienza|science fiction|sci fi|cyberpunk|distopic|dystopian|post apocalitt|post apocalypt|time travel|space opera"),
    Genre("silent", "Silent film", "Film muto", "Films without synchronised dialogue (a format the sources list among genres).", exact=("muto", "silent", "silent film"), keywords=r"\bmuto\b|\bsilent\b"),
    Genre("sport", "Sport", "Sportivo", "Sport at the centre of the story.", exact=("sport", "sportivo"), keywords=r"\bsport|calcio|football|pugilato|boxing|basket|baseball|wrestling"),
    Genre("spy", "Spy", "Spionaggio", "Espionage.", exact=("spionaggio", "spy"), keywords=r"spion|\bspy\b"),
    Genre("superhero", "Superhero", "Supereroi", "Heroes with extraordinary powers.", exact=("supereroi", "superhero"), keywords=r"supereroi|superhero"),
    Genre("thriller", "Thriller", "Thriller", "Suspense and tension.", exact=("thriller", "suspense"), keywords=r"thriller|suspense"),
    Genre("war", "War", "Guerra", "Armed conflict.", exact=("guerra", "war"), keywords=r"\bguerra\b|\bwar\b"),
    Genre("western", "Western", "Western", "The American frontier and its descendants.", exact=("western",), synonyms=("spaghetti western", "western all italiana"), keywords=r"western|spaghetti"),
    Genre("disaster", "Disaster", "Catastrofico", "Natural or man-made catastrophes.", exact=("catastrofico", "disaster"), keywords=r"catastrofic|disaster"),
    Genre("erotic", "Erotic", "Erotico", "Erotic content.", exact=("erotico", "erotic"), keywords=r"eroti|sexploitation"),
    Genre("pornographic", "Pornographic", "Pornografico", "Explicit sexual content.", parent="erotic", exact=("pornografico", "pornographic"), keywords=r"pornograf"),
    Genre("teen", "Teen", "Per ragazzi", "Films aimed at teenagers.", exact=("ragazzi", "teen", "teenage"), keywords=r"\bteen|per ragazzi|adolescen"),
    Genre("coming_of_age", "Coming-of-age", "Di formazione", "A young person's passage to adulthood.", exact=("formazione", "coming of age"), keywords=r"formazione|coming of age"),
    Genre("christmas", "Christmas", "Natalizio", "Set around Christmas.", exact=("natalizio", "christmas"), keywords=r"natalizi|christmas"),
)
BY_CODE = {g.code: g for g in VOCABULARY}
_COMPILED = {g.code: re.compile(g.keywords) for g in VOCABULARY if g.keywords}


def core(norm: str) -> str:
    """The label without filler words: 'film dell orrore' -> 'orrore'."""
    return " ".join(t for t in norm.split() if t not in _FILLER)


def map_label(label_it: str | None, label_en: str | None) -> list[tuple[str, str, str]]:
    """[(genre code, mapping kind, rule id)] for one source label, from its Italian and/or English text. Empty = unmapped."""
    norms = [n for n in (normalize_name(t) for t in (label_it, label_en) if t) if n]
    cores = {core(n) for n in norms} - {""}
    out: list[tuple[str, str, str]] = []
    for g in VOCABULARY:
        hit = cores & set(g.exact)
        if hit:
            out.append((g.code, "exact", f"exact:{sorted(hit)[0]}"))
            continue
        hit = cores & set(g.synonyms)
        if hit:
            out.append((g.code, "synonym", f"synonym:{sorted(hit)[0]}"))
            continue
        rx = _COMPILED.get(g.code)
        if rx:
            for n in norms:
                m = rx.search(n)
                if m:
                    out.append((g.code, "specific", f"keyword:{m.group(0).strip()}"))
                    break
    return out
