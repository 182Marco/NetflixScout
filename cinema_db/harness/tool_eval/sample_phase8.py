"""Phase 8: the FINAL evaluation sample (20 questions), written before any optimisation and independent of the questions used so far.

Rules that keep it honest:
- None of these questions, films or people appears in the 55 questions of `run_live7` (checked by `tests/test_cinema_phase8_sample.py`), so no correction was built on them.
- The sample is run ONCE per variant at the end (baseline = code before the phase, candidate = code after each accepted intervention); it is never used to decide an
  intervention and a failing question is never fixed by a rule written for it. The questions used to develop and regress the interventions are the 55 of `run_live7`.
- `must` groups are alternatives (a fact is present if one word of the group is in the answer): a mechanical floor, NOT the verdict. The verdict is the rubric below, read by hand
  and by the blind pairwise judge only when credits exist.

Rubric (per answer, each 0-2): CORRECTNESS (no false fact, no invented name/date/number); COMPLETENESS (everything the question asks, or the gap said aloud);
PRUDENCE (says "not found / not in my data" instead of guessing; asks which one on a homonym; does not call a partial list complete); SOURCES (uses the local database
for what it holds and an external tool only for what it lacks; no external step that a local verified answer made useless; no source named in the text).
Efficiency is measured, never judged: planner calls, steps, HTTP requests, SQL queries, seconds (`timings`).
`expected_route` is what a good plan looks like (informational, to read the sequences by hand); it is not a pass/fail condition.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Sample:
    key: str
    text: str
    covers: str
    must: tuple[tuple[str, ...], ...]
    expected_route: str
    watch: str


SAMPLE: tuple[Sample, ...] = (
    Sample("F01", "Chi ha diretto Il silenzio degli innocenti?", "ricerca film, regista", (("Demme",),), "cinema_sql", "una risposta locale verificata non va ricontrollata altrove"),
    Sample("F02", "Quali film ha diretto Greta Gerwig?", "filmografia", (("Lady Bird",), ("Barbie",), ("Piccole donne", "Little Women")), "cinema_sql", "elenco locale: dichiarare se incompleto"),
    Sample("F03", "Chi ha recitato in Taxi Driver?", "cast completo", (("De Niro",), ("Foster",)), "cinema_sql", "nessun ordine di rilievo chiesto: il cast locale basta"),
    Sample("F04", "Con quali attori ha lavorato di più Martin Scorsese?", "collaborazioni", (("De Niro",), ("DiCaprio",)), "cinema_sql", "classifica locale"),
    Sample("F05", "Quanti Oscar ha vinto Titanic?", "premi di un'opera", (("11", "undici"),), "cinema_sql", "conteggio per premio, non per destinatario"),
    Sample("F06", "Chi ha vinto l'Oscar come miglior regista nel 2010?", "premi per categoria e anno", (("Bigelow",),), "cinema_sql", "anno = anno della cerimonia"),
    Sample("F07", "Da quale libro è tratto Shining?", "relazioni tra opere", (("King",),), "cinema_sql (+ un passo se l'autore manca)", "il campo opera d'origine può avere solo il titolo"),
    Sample("F08", "Quali film fanno parte della saga di Matrix?", "franchise", (("Reloaded",), ("Revolutions",)), "cinema_sql", "un franchise può essere una lista"),
    Sample("F09", "Chi ha diretto Psycho?", "disambiguazione", (("Hitchcock",), ("Van Sant",)), "cinema_sql", "due film omonimi: chiedere quale o dare entrambi, non scegliere"),
    Sample("F10", "Chi ha diretto il film Vexlor Mandrake del 1987?", "dato mancante (titolo inesistente)", (), "cinema_sql poi al massimo un passo esterno", "nessuna invenzione; «non l'ho trovato» senza dedurre che non esista"),
    Sample("F11", "Dove posso vedere Barbie in streaming in Italia?", "fonte esterna richiesta", (("Barbie",),), "tmdb_search", "il database non ha lo streaming: nessun passo locale inutile"),
    Sample("F12", "Mostrami interviste a Greta Gerwig su Barbie", "fonte esterna (video)", (("Gerwig",),), "youtube_search", "video verificati o da verificare, mai inventati"),
    Sample("F13", "Che Metascore ha Il silenzio degli innocenti?", "punteggi (esterno, titolo identificato)", (("85",),), "omdb_search", "nessuna media, nessuna conversione di scala"),
    Sample("F14", "Quali film sono usciti di recente con Zendaya?", "novità (catalogo incompleto dopo il 2019)", (("Zendaya",),), "tmdb_search", "film non ancora usciti esclusi"),
    Sample("F15", "Quando è iniziata e quando è finita la serie The Wire?", "serie, dati strutturati", (("2002",), ("2008",)), "tvmaze_search o cinema_sql", "date della serie, non dei singoli episodi"),
    Sample("F16", "Chi ha composto la colonna sonora di Interstellar e quanti Oscar ha vinto il film?", "composta locale+locale", (("Zimmer",), ("1", "uno", "un solo")), "cinema_sql (due parti nello stesso passo, se possibile)", "raggruppare operazioni compatibili"),
    Sample("F17", "Chi ha diretto Titanic, chi ha scritto la sceneggiatura e che punteggio Rotten Tomatoes ha?", "locale + esterno (punteggio)", (("Cameron",), ("Rotten", "%")), "cinema_sql poi omdb_search", "il passo OMDb non dipende dal risultato locale"),
    Sample("F18", "Con quali film hanno lavorato insieme Tom Hanks e Meg Ryan?", "collaborazioni tra due persone", (("Sleepless", "Insonnia d'amore"), ("C'è post@ per te", "You've Got Mail")), "cinema_sql", "opere in comune di due persone"),
    Sample("F19", "Quanti episodi ha la prima stagione di Lost?", "serie, conteggi inaffidabili in locale", (("25",),), "cinema_sql poi tvmaze_search", "conteggio dichiarato incerto se le righe sono parziali"),
    Sample("F20", "Who wrote the screenplay for Casablanca?", "lingua inglese, crediti writer", (("Epstein",), ("Koch",)), "cinema_sql", "risposta in inglese; il ruolo writer può includere gli autori della fonte"),
)
