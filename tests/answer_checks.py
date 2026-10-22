"""Check a final (Italian) answer against the constraint statuses it was given (D5).

Used by `tests/test_answer_constraints.py` on answers recorded in real runs, and by the e2e
evaluation scripts on fresh answers. Deterministic, no network. It looks only at the
sentences of each film's section that mention a constraint (via `terms`) and reports:

- a `not_verifiable` constraint stated or inferred instead of declared unverifiable;
- missing information turned into a negative ("non tratta l'eutanasia");
- a `probable` constraint presented as confirmed;
- a `contradicted` constraint never stated as such.
"""
from __future__ import annotations

import re

# "non … verificare / confermato / documentato / noto …" in the same clause.
UNVERIFIABLE = re.compile(
    r"\bnon\b[^.;]*?\b(verificab|verificare|verificat|confermat|confermar|documentat|indicat|not[oi]\b|garantir|"
    r"determinab|disponibil|emerg|stabilir)"
)
NEGATIVE_PROOF = re.compile(r"\bnon (tratta|parla|affronta|riguarda|racconta|è ambientat|ha un finale|è giappones)")
CONFIRMED = re.compile(r"\b(confermat|verificat|certament|sicuramente)")
CONTRADICTION = re.compile(r"\b(non risulta|non è|non sono|contraddett|non appartiene)")


def _sentences(text: str) -> list[str]:
    """Sentences, split again at adversative links so one clause cannot cover another
    ("X è suggerita…, mentre Y non è verificabile"). Lists joined by commas stay whole."""
    # Only ", mentre / , ma …": without the comma the word is inside one clause ("è invece").
    parts = re.split(r"(?<=[.!?])\s+|\n+|;|,\s+(?:mentre|ma|tuttavia|però)\s+", text)
    return [part.strip() for part in parts if part and part.strip()]


def _sections(answer: str, titles: list[str]) -> dict[str, str]:
    """Text from each title's first mention to the next title's first mention."""
    lower = answer.lower()
    starts = sorted((lower.find(t.lower()), t) for t in titles if lower.find(t.lower()) >= 0)
    sections = {}
    for i, (start, title) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(answer)
        sections[title] = answer[start:end]
    return sections


def check_answer(answer: str, report: dict, terms: dict[str, tuple[str, ...]]) -> list[str]:
    """Problems found; `terms` maps a constraint to the Italian words that name it."""
    problems: list[str] = []
    labels = {label for check in report.get("checks", []) for label in check["results"]}
    titles = sorted({label.rsplit(" (", 1)[0] for label in labels}, key=len, reverse=True)
    sections = _sections(answer, titles)
    for check in report.get("checks", []):
        keys = terms.get(check["constraint"])
        if not keys:
            continue
        for label, result in check["results"].items():
            title = label.rsplit(" (", 1)[0]
            section = sections.get(title)
            if section is None:
                continue
            mentions = [s for s in _sentences(section) if any(k in s.lower() for k in keys)]
            status = result["status"]
            for sentence in mentions:
                low = sentence.lower()
                unverifiable = bool(UNVERIFIABLE.search(low))
                if status == "not_verifiable" and NEGATIVE_PROOF.search(low) and not unverifiable:
                    problems.append(f"{title} · {check['constraint']}: assenza presentata come prova negativa: {sentence}")
                elif status == "not_verifiable" and not unverifiable:
                    problems.append(f"{title} · {check['constraint']}: non verificabile ma affermato o dedotto: {sentence}")
                if status == "probable" and CONFIRMED.search(low) and "probabil" not in low and not unverifiable:
                    problems.append(f"{title} · {check['constraint']}: probabile presentato come confermato: {sentence}")
            if status == "contradicted" and not any(CONTRADICTION.search(s.lower()) for s in mentions):
                problems.append(f"{title} · {check['constraint']}: contraddetto dai dati ma non dichiarato")
    return problems
