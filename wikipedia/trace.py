"""Trace of a Wikipedia run and the summary the planner reads.

The trace is kept outside `metadata` (which goes into the LLM prompt): the presenters show the
page titles, URLs, languages and the licence exactly as the tool built them, never left to the
model. It holds no extract text, no User-Agent and no request parameters (`calls` are base URLs).
The planner summary is the part of the result the orchestrator shows the planner when it decides
whether to read more: what was read, what was left out, why more could help.
"""
from __future__ import annotations

from typing import Any

from turn import STEP_WIKIPEDIA_CALLS

from .models import PageResult
from .queries import page_url
from .settings import LICENSE_NAME, LICENSE_URL, PLANNER_SUMMARY_CHARS

WIKIPEDIA_CALLS_TITLE = "Wikipedia"

REASON_TEXT = {
    "empty": "nessuna pagina trovata: si può cercare con un altro titolo, tipo o lingua",
    "ambiguous": "solo pagine di disambiguazione: serve più contesto (ruolo, anno) per scegliere",
    "unverified": "nessuna pagina combacia con certezza col titolo cercato",
    "more_in_page": "la pagina ha altre sezioni non ancora lette",
    "omitted_by_budget": "una sezione scelta non è entrata nel budget di testo del turno",
    "keywords_absent": "alcune parole chiave non compaiono in nessuna sezione di questa edizione: l'altra edizione potrebbe coprire il dettaglio",
}

KEYWORD_TEXT = {
    "read": "lette",
    "unread": "non lette",
    "absent": "assenti dall'articolo",
    "not_in_lead": "non nell'introduzione (articolo non ancora aperto)",
}


def build_wikipedia_trace(
    calls: list[str],
    reused: int,
    searches: list[dict[str, Any]],
    opens: list[dict[str, Any]],
    pages: list[PageResult],
    hints: list[str] | None = None,
) -> list[dict[str, Any]]:
    data: dict[str, Any] = {
        "calls": list(calls),
        "reused": reused,
        "searches": [dict(search) for search in searches],
        "opens": [dict(row) for row in opens],
        "pages": [
            {
                "title": page.title,
                "language": page.language,
                "url": page_url(page.language, page.title),
                "verification": page.verification,
                "notes": list(page.notes),
                "last_revised": page.last_revised,
                "total_chars": page.total_chars,
                "delivered_chars": page.delivered_chars,
                "sections": list(page.sections),
                "omitted": len(page.omitted),
            }
            for page in pages
        ],
        "license": {"name": LICENSE_NAME, "url": LICENSE_URL},
    }
    if hints:
        data["hints"] = list(hints)
    return [{"kind": STEP_WIKIPEDIA_CALLS, "title": WIKIPEDIA_CALLS_TITLE, "data": data}]


def _outline_line(page: PageResult) -> str:
    if page.outline is None:
        return "  Lette solo le introduzioni: l'elenco delle sezioni si ottiene aprendo la pagina (page, depth sections o full)."
    items = " · ".join(f"{row['title']}{'*' if row['delivered'] else ''} ({row['chars']})" for row in page.outline)
    return f"  Sezioni (* = già letta, caratteri): {items}"


def _keywords_line(page: PageResult) -> str | None:
    if not page.keywords:
        return None
    parts = []
    for row in page.keywords:
        text = f"«{row['keyword']}» {KEYWORD_TEXT.get(str(row['status']), row['status'])}"
        if row["status"] == "unread" and row.get("sections"):
            text += " (in: " + ", ".join(row["sections"]) + ")"
        parts.append(text)
    return "  Parole chiave: " + "; ".join(parts)


def build_planner_summary(
    pages: list[PageResult],
    reasons: list[str],
    *,
    context_used: int,
    context_budget: int,
    calls_left: int,
    edition: str | None = None,
    languages_tried: list[str] | None = None,
    other_edition: str | None = None,
) -> str:
    """Compact description of the step for the planner (at most `PLANNER_SUMMARY_CHARS`).

    It says which edition was used, what was read and what was left out, where the keywords stand
    and why more could help. It holds no text of the extracts: the planner does not need the words
    the final answer already gets, only where to look next.
    """
    lines = []
    if edition:
        tried = ", ".join(languages_tried or [edition])
        other = (
            f"edizione {other_edition} non ancora consultata (si apre con language {other_edition})"
            if other_edition
            else "tutte le edizioni già consultate"
        )
        lines.append(f"Wikipedia, edizione usata: {edition}; consultate nel turno: {tried}; {other}.")
    lines.append(
        f"{len(pages)} pagine; testo nel prompt {context_used}/{context_budget} caratteri; "
        f"chiamate HTTP rimaste {calls_left}."
    )
    for page in pages:
        total = f"/{page.total_chars}" if page.total_chars is not None else ""
        lines.append(
            f"- [{page.language}] {page.title} ({page.verification}): letti {page.delivered_chars}{total} caratteri."
        )
        lines.append(_outline_line(page))
        if page.omitted:
            lines.append("  Non lette: " + ", ".join(f"{row['title']} ({row['chars']})" for row in page.omitted[:12]))
        keywords = _keywords_line(page)
        if keywords:
            lines.append(keywords)
    if reasons:
        lines.append("Si può continuare: " + "; ".join(REASON_TEXT[reason] for reason in reasons) + ".")
    summary = "\n".join(lines)
    return summary if len(summary) <= PLANNER_SUMMARY_CHARS else summary[: PLANNER_SUMMARY_CHARS - 1].rstrip() + "…"
