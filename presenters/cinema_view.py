"""Channel-neutral view of a `cinema_sql_calls` step, shared by the terminal and web presenters.

What the user is told about a turn that read the local cinema database: which operation, which work or person it identified (with the links to its public
Wikipedia and Wikidata pages), how many results, the limits of the data that apply, and the SOURCES of the data with their licences. The provenance is that of
the DATA (Wikipedia, CC BY-SA 4.0, and Wikidata, CC0 1.0), never "a database": the SQL, the views, the internal ids and the identifiers of other sites are not shown.
Reads only `step.data`; imports nothing but `turn`: no `cinema_db` package, no tool logic. The links are built here from two identifiers the database records
(a Wikipedia page title, a Wikidata item id), validated, on fixed hosts: nothing is invented.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, Field

from turn import TraceStep, label_language

LABELS = {
    "it": {
        "title": "ARCHIVIO LOCALE",
        "source": "Fonte: Wikipedia ({wikipedia}) e Wikidata ({wikidata}), dati di un archivio locale riformulati dall'assistente",
        "no_network": "Nessuna richiesta di rete: i dati vengono dall'archivio locale",
        "local": "{n} ricerche locali, {ms} ms",
        "operation": "Ricerca",
        "wikipedia": "Pagina Wikipedia",
        "wikidata": "Elemento Wikidata",
        "candidates": "Alternative",
        "shown": "Mostrati {shown} di {total}",
        "notes": "Limiti dei dati",
        "license": "Licenze",
        "ok": "Dati trovati nell'archivio locale",
        "empty": "Nessun dato nell'archivio locale",
        "ambiguous": "Più corrispondenze: nessun dato assegnato",
        "unverified": "Solo nomi simili: nessun dato assegnato",
        "not_found": "Non trovato nell'archivio locale",
        "error": "Errore",
        "more": "altre non mostrate",
    },
    "en": {
        "title": "LOCAL ARCHIVE",
        "source": "Source: Wikipedia ({wikipedia}) and Wikidata ({wikidata}), data from a local archive reworded by the assistant",
        "no_network": "No network request: the data comes from the local archive",
        "local": "{n} local lookups, {ms} ms",
        "operation": "Lookup",
        "wikipedia": "Wikipedia page",
        "wikidata": "Wikidata item",
        "candidates": "Alternatives",
        "shown": "Showing {shown} of {total}",
        "notes": "Limits of the data",
        "license": "Licences",
        "ok": "Data found in the local archive",
        "empty": "No data in the local archive",
        "ambiguous": "Several matches: no data assigned",
        "unverified": "Only similar names: no data assigned",
        "not_found": "Not found in the local archive",
        "error": "Error",
        "more": "more not shown",
    },
    "de": {
        "title": "LOKALES ARCHIV",
        "source": "Quelle: Wikipedia ({wikipedia}) und Wikidata ({wikidata}), Daten aus einem lokalen Archiv, vom Assistenten umformuliert",
        "no_network": "Keine Netzwerkanfrage: Die Daten stammen aus dem lokalen Archiv",
        "local": "{n} lokale Abfragen, {ms} ms",
        "operation": "Abfrage",
        "wikipedia": "Wikipedia-Seite",
        "wikidata": "Wikidata-Element",
        "candidates": "Alternativen",
        "shown": "{shown} von {total} angezeigt",
        "notes": "Grenzen der Daten",
        "license": "Lizenzen",
        "ok": "Daten im lokalen Archiv gefunden",
        "empty": "Keine Daten im lokalen Archiv",
        "ambiguous": "Mehrere Treffer: keine Daten zugeordnet",
        "unverified": "Nur ähnliche Namen: keine Daten zugeordnet",
        "not_found": "Im lokalen Archiv nicht gefunden",
        "error": "Fehler",
        "more": "weitere nicht angezeigt",
    },
}

OPERATIONS = {
    "it": {"find_work": "Identificazione di un titolo", "work_card": "Scheda di un titolo", "find_person": "Identificazione di una persona", "filmography": "Filmografia",
           "cast": "Cast", "crew": "Troupe", "collaborations": "Collaborazioni", "awards": "Premi e candidature", "series": "Stagioni ed episodi", "companies": "Società",
           "franchise": "Saga o franchise", "relations": "Relazioni tra opere", "sql": "Interrogazione libera"},
    "en": {"find_work": "Title identification", "work_card": "Title card", "find_person": "Person identification", "filmography": "Filmography", "cast": "Cast",
           "crew": "Crew", "collaborations": "Collaborations", "awards": "Awards and nominations", "series": "Seasons and episodes", "companies": "Companies",
           "franchise": "Saga or franchise", "relations": "Relations between works", "sql": "Free query"},
    "de": {"find_work": "Titelidentifikation", "work_card": "Titelkarte", "find_person": "Personenidentifikation", "filmography": "Filmografie", "cast": "Besetzung",
           "crew": "Stab", "collaborations": "Zusammenarbeit", "awards": "Preise und Nominierungen", "series": "Staffeln und Episoden", "companies": "Firmen",
           "franchise": "Reihe oder Franchise", "relations": "Beziehungen zwischen Werken", "sql": "Freie Abfrage"},
}

KINDS = {
    "it": {"film": "film", "short": "cortometraggio", "tv_film": "film TV", "series": "serie", "miniseries": "miniserie", "person": "persona", "company": "società", "franchise": "saga"},
    "en": {"film": "film", "short": "short film", "tv_film": "TV film", "series": "series", "miniseries": "miniseries", "person": "person", "company": "company", "franchise": "saga"},
    "de": {"film": "Film", "short": "Kurzfilm", "tv_film": "Fernsehfilm", "series": "Serie", "miniseries": "Miniserie", "person": "Person", "company": "Firma", "franchise": "Reihe"},
}

# Codes of the data-limit notes the tool attaches to a result (cinema_db/constants.py:NOTES); a code the view does not know is not shown.
NOTES = {
    "it": {
        "coverage": "L'archivio contiene film e serie con una pagina Wikipedia; le opere recenti (dopo il 2019) sono incomplete: ciò che manca non prova che non esista.",
        "cast_order": "Il cast non ha un ordine di rilievo e può essere parziale.",
        "filmography": "Sono elencate solo le opere dell'archivio, con crediti da Wikidata: l'elenco può essere incompleto.",
        "awards": "I premi sono registrati solo per una parte delle opere: nessun premio trovato non prova che non ce ne siano.",
        "awards_person_scope": "I premi di una persona sono solo quelli in cui è registrata: un premio registrato solo sul film non compare qui.",
        "relations": "«Basato su» comprende remake, adattamenti e opere solo ispirate; «segue» è l'ordine in una serie.",
        "series": "Stagioni ed episodi esistono solo dove l'archivio li ha: i conteggi possono essere più bassi dei reali.",
        "episode_duplicates": "I conteggi degli episodi non sono affidabili e la numerazione può mancare.",
        "crew": "I crediti sono dichiarazioni di Wikidata: tra gli sceneggiatori possono comparire anche gli autori dell'opera d'origine o i creatori di un personaggio.",
        "companies": "Le società sono quelle registrate come produzione, distribuzione o rete: l'elenco può essere parziale.",
        "franchise": "«Parte della serie» può essere anche una lista o una raccolta, non solo una saga.",
        "person": "Gli anni di nascita e morte ci sono solo dove la data è univoca.",
        "money": "Gli importi sono nella valuta registrata, mai convertiti.",
        "limit": "L'elenco è stato troncato al limite mostrato.",
        "unverified": "Sono state trovate solo alternative simili, non il nome esatto.",
        "no_ids": "Per questa opera non c'è alcun identificativo esterno.",
        "ids_partial": "Solo le prime opere dell'elenco hanno gli identificativi esterni.",
    },
    "en": {
        "coverage": "The archive holds films and series that have a Wikipedia page; recent works (after 2019) are incomplete: what is missing does not prove it does not exist.",
        "cast_order": "The cast has no billing order and may be partial.",
        "filmography": "Only works of the archive are listed, with credits from Wikidata: the list may be incomplete.",
        "awards": "Awards are recorded for only some works: no award found does not prove none was given.",
        "awards_person_scope": "A person's awards are only those where they are recorded: a prize recorded only on the film does not appear here.",
        "relations": "'Based on' covers remakes, adaptations and works that only inspired another; 'follows' is the order in a series.",
        "series": "Seasons and episodes exist only where the archive has them: counts can be lower than the real ones.",
        "episode_duplicates": "Episode counts are not reliable and numbering may be missing.",
        "crew": "Credits are Wikidata statements: the writers can also include the authors of the source material or the creators of a character.",
        "companies": "Companies are those recorded as production, distribution or network: the list may be partial.",
        "franchise": "'Part of the series' can also be a list or a collection, not only a saga.",
        "person": "Birth and death years exist only where the date is unambiguous.",
        "money": "Amounts are in the recorded currency, never converted.",
        "limit": "The list was cut at the limit shown.",
        "unverified": "Only similar alternatives were found, not the exact name.",
        "no_ids": "This work has no external identifier.",
        "ids_partial": "Only the first works of the list carry their external identifiers.",
    },
    "de": {
        "coverage": "Das Archiv enthält Filme und Serien mit einer Wikipedia-Seite; neuere Werke (nach 2019) sind unvollständig: Was fehlt, beweist nicht, dass es nicht existiert.",
        "cast_order": "Die Besetzung hat keine Reihenfolge nach Bedeutung und kann unvollständig sein.",
        "filmography": "Es sind nur Werke des Archivs aufgeführt, mit Credits aus Wikidata: Die Liste kann unvollständig sein.",
        "awards": "Preise sind nur für einen Teil der Werke erfasst: Kein gefundener Preis beweist nicht, dass es keinen gab.",
        "awards_person_scope": "Die Preise einer Person sind nur die, bei denen sie erfasst ist: Ein nur beim Film erfasster Preis erscheint hier nicht.",
        "relations": "„Basiert auf“ umfasst Remakes, Adaptionen und nur inspirierte Werke; „folgt“ ist die Reihenfolge in einer Serie.",
        "series": "Staffeln und Episoden gibt es nur, wo das Archiv sie hat: Die Zahlen können niedriger sein als die echten.",
        "episode_duplicates": "Episodenzahlen sind nicht verlässlich, die Nummerierung kann fehlen.",
        "crew": "Credits sind Wikidata-Angaben: Unter den Drehbuchautoren können auch die Autoren der Vorlage oder die Schöpfer einer Figur stehen.",
        "companies": "Firmen sind die als Produktion, Vertrieb oder Sender erfassten: Die Liste kann unvollständig sein.",
        "franchise": "„Teil der Reihe“ kann auch eine Liste oder Sammlung sein, nicht nur eine Reihe.",
        "person": "Geburts- und Sterbejahre gibt es nur bei eindeutigem Datum.",
        "money": "Beträge stehen in der erfassten Währung, nie umgerechnet.",
        "limit": "Die Liste wurde an der angezeigten Grenze gekürzt.",
        "unverified": "Es wurden nur ähnliche Alternativen gefunden, nicht der genaue Name.",
        "no_ids": "Für dieses Werk gibt es keine externe Kennung.",
        "ids_partial": "Nur die ersten Werke der Liste haben ihre externen Kennungen.",
    },
}

CODE_LABELS = {
    "it": {"title_unknown": "nessun titolo con questo nome", "name_unknown": "nessuna persona con questo nome", "id_unknown": "identificativo sconosciuto", "ids_disagree": "gli identificativi indicano opere diverse",
           "similar_names_only": "solo nomi simili", "filters_not_matched": "il nome esiste ma non con quell'anno o regista", "db_missing": "archivio locale non disponibile",
           "turn_limit": "limite di ricerche per turno", "timeout": "tempo scaduto", "invalid_request": "richiesta non valida", "not_a_series": "non è una serie",
           "no_credits_in_catalogue": "nessun credito nell'archivio", "no_cast_in_catalogue": "nessun cast nell'archivio", "no_relation_recorded": "nessuna relazione registrata",
           "no_award_results_recorded": "nessun premio registrato", "no_franchise_recorded": "nessuna saga registrata", "no_company_recorded": "nessuna società registrata"},
    "en": {"title_unknown": "no title with this name", "name_unknown": "no person with this name", "id_unknown": "unknown identifier", "ids_disagree": "the identifiers point at different works",
           "similar_names_only": "only similar names", "filters_not_matched": "the name exists but not with that year or director", "db_missing": "local archive unavailable",
           "turn_limit": "per-turn lookup limit", "timeout": "timed out", "invalid_request": "invalid request", "not_a_series": "not a series",
           "no_credits_in_catalogue": "no credit in the archive", "no_cast_in_catalogue": "no cast in the archive", "no_relation_recorded": "no relation recorded",
           "no_award_results_recorded": "no award recorded", "no_franchise_recorded": "no saga recorded", "no_company_recorded": "no company recorded"},
    "de": {"title_unknown": "kein Titel mit diesem Namen", "name_unknown": "keine Person mit diesem Namen", "id_unknown": "unbekannte Kennung", "ids_disagree": "die Kennungen weisen auf verschiedene Werke",
           "similar_names_only": "nur ähnliche Namen", "filters_not_matched": "der Name existiert, aber nicht mit diesem Jahr oder Regisseur", "db_missing": "lokales Archiv nicht verfügbar",
           "turn_limit": "Abfragelimit pro Durchgang", "timeout": "Zeitüberschreitung", "invalid_request": "ungültige Anfrage", "not_a_series": "keine Serie",
           "no_credits_in_catalogue": "kein Credit im Archiv", "no_cast_in_catalogue": "keine Besetzung im Archiv", "no_relation_recorded": "keine Beziehung erfasst",
           "no_award_results_recorded": "kein Preis erfasst", "no_franchise_recorded": "keine Reihe erfasst", "no_company_recorded": "keine Firma erfasst"},
}

LICENSES = (("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/"), ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/"))
_QID = re.compile(r"^Q[1-9]\d{0,11}$")
_WHITESPACE_CONTROLS = {"\t", "\n", "\r", "\x0b", "\x0c", "\x85"}


def printable(value: Any) -> str:
    """Display copy without C0/C1 control characters; printable text is unchanged."""
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    out = []
    for char in text:
        code = ord(char)
        if code < 0x20 or code == 0x7F or 0x80 <= code <= 0x9F:
            if char in _WHITESPACE_CONTROLS:
                out.append(" ")
            continue
        out.append(char)
    return "".join(out)


def labels(language: str | None) -> dict[str, str]:
    return LABELS[label_language(language)]


class LinkView(BaseModel):
    label: str
    url: str


class SubjectView(BaseModel):
    name: str
    summary: str = ""
    links: list[LinkView] = Field(default_factory=list)


class LicenseView(BaseModel):
    name: str
    url: str


class CinemaCallsView(BaseModel):
    title: str
    source: str
    labels: dict[str, str]
    no_network: str
    local: str
    operation: str | None = None
    operation_label: str | None = None
    status: str
    status_label: str
    reason: str | None = None
    subject: SubjectView | None = None
    candidates: list[str] = Field(default_factory=list)
    partial: bool = False
    counts: str | None = None
    notes: list[str] = Field(default_factory=list)
    licenses: list[LicenseView] = Field(default_factory=list)


def wikipedia_url(title: Any) -> str | None:
    """Public Wikipedia (it) page of a recorded page title: fixed host, percent-encoded title, no control characters; None when there is none."""
    if not isinstance(title, str) or not title.strip() or any(ord(c) < 0x20 or ord(c) == 0x7F for c in title):
        return None
    return "https://it.wikipedia.org/wiki/" + quote(title.strip().replace(" ", "_"), safe="/_()',:!~*")


def wikidata_url(qid: Any) -> str | None:
    return f"https://www.wikidata.org/wiki/{qid}" if isinstance(qid, str) and _QID.match(qid) else None


def _name(row: dict[str, Any]) -> str:
    return printable(row.get("title") or row.get("name"))


def _years(row: dict[str, Any]) -> str:
    start, end = row.get("year"), row.get("end_year")
    if isinstance(start, int) and isinstance(end, int) and end != start:
        return f"{start}–{end}"
    if isinstance(start, int):
        return str(start)
    born = row.get("birth_year")
    return f"*{born}" if isinstance(born, int) else ""


def _subject(raw: Any, language: str | None) -> SubjectView | None:
    if not isinstance(raw, dict) or not _name(raw):
        return None
    text = labels(language)
    kinds = KINDS[label_language(language)]
    kind = kinds.get(raw.get("kind"), "") if isinstance(raw.get("kind"), str) else ""
    links = []
    for label, url in ((text["wikipedia"], wikipedia_url(raw.get("wikipedia_it"))), (text["wikidata"], wikidata_url(raw.get("wikidata_id")))):
        if url:
            links.append(LinkView(label=label, url=url))
    years = _years(raw)
    return SubjectView(name=f"{_name(raw)} ({years})" if years else _name(raw), summary=kind, links=links)


def _candidate(row: dict[str, Any], language: str | None) -> str:
    kinds = KINDS[label_language(language)]
    directors = row.get("directors") if isinstance(row.get("directors"), list) else []
    details = ", ".join(part for part in (_years(row), kinds.get(row.get("kind"), "") if isinstance(row.get("kind"), str) else "", ", ".join(printable(d) for d in directors[:2])) if part)
    return f"{_name(row)} ({details})" if details else _name(row)


def cinema_calls_view(step: TraceStep, language: str | None) -> CinemaCallsView:
    data = step.data
    lang = label_language(language)
    text = LABELS[lang]
    status = data.get("status") if data.get("status") in text else "error"
    reason = data.get("reason")
    operation = data.get("operation") if isinstance(data.get("operation"), str) else None
    candidates = [_candidate(row, language) for row in data.get("candidates") or [] if isinstance(row, dict)]
    omitted = data.get("candidates_omitted")
    if candidates and isinstance(omitted, int) and not isinstance(omitted, bool) and omitted > 0:
        candidates.append(f"+{omitted} {text['more']}")
    shown, total = data.get("rows"), data.get("total")
    counts = text["shown"].format(shown=shown, total=total) if isinstance(shown, int) and isinstance(total, int) and total > shown else None
    queries = data.get("queries_count") if isinstance(data.get("queries_count"), int) else len(data.get("queries") or [])
    elapsed = data.get("elapsed_ms") if isinstance(data.get("elapsed_ms"), int) else 0
    known = NOTES[lang]
    return CinemaCallsView(
        title=text["title"],
        source=text["source"].format(wikipedia=LICENSES[0][0], wikidata=LICENSES[1][0]),
        labels=text,
        no_network=text["no_network"],
        local=text["local"].format(n=queries, ms=elapsed),
        operation=operation,
        operation_label=OPERATIONS[lang].get(operation) if operation else None,
        status=status,
        status_label=text[status],
        reason=CODE_LABELS[lang].get(reason, printable(reason)) if isinstance(reason, str) and status != "ok" else None,
        subject=_subject(data.get("subject"), language),
        candidates=candidates,
        partial=bool(candidates) and isinstance(omitted, int) and omitted > 0,
        counts=counts,
        notes=[known[code] for code in data.get("notes") or [] if isinstance(code, str) and code in known],
        licenses=[LicenseView(name=name, url=url) for name, url in LICENSES],
    )
