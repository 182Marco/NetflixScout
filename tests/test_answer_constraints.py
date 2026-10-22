"""Final answers vs constraint statuses (D5).

Real excerpts are copied verbatim from answers produced in the real e2e runs of
2026-10-22 (e2e_results_v3.json, verify_d1_d5.json). Constructed ones are marked as such
and cover the mistakes no real answer happened to make. The second part checks the text
the model receives: one readable line per film and constraint.
"""
from __future__ import annotations

from answer_checks import check_answer

from orchestrator import LLMOrchestrator
from rag.FromQueryEmbeddingToRes.constraints import constraint_report, constraint_summary
from rag.FromQueryEmbeddingToRes.models import QuerySignals

TERMS = {
    "Japanese": ("giappones",), "Comedy": ("commedia",), "set on Mars": ("marte", "marzian"),
    "euthanasia": ("eutanasia",), "non-tragic ending": ("finale",), "similar themes": ("temi",),
}


def _report(constraint, statuses):
    return {"checks": [{"constraint": constraint, "type": "t", "results": {k: {"status": v} for k, v in statuses.items()}}]}


# --- case 20 ---------------------------------------------------------------------------

REAL_20_BAD = (  # verify_d1_d5.json, case 20: nationality inferred from the plot
    "### 3. *The Mysterians* (1957)\n- **Vincoli:** fantascienza e anni Cinquanta sono confermati. "
    "L’origine giapponese è suggerita dal riferimento al Giappone nella trama, mentre il finale aperto e "
    "l’impatto emotivo non sono verificabili."
)
REAL_20_GOOD = (  # e2e_results_v3.json, case 20
    "1. **Conquest of Space (1955)**\n   - La fantascienza e l’ambientazione negli anni Cinquanta sono confermate "
    "dai dati del catalogo. Il genere commedia è invece contraddetto dai generi indicati, che sono fantascienza, "
    "dramma e avventura."
)


def test_case_20_nationality_inferred_from_a_character_is_flagged() -> None:
    problems = check_answer(REAL_20_BAD, _report("Japanese", {"The Mysterians (1957)": "not_verifiable"}), TERMS)

    assert len(problems) == 1 and "non verificabile ma affermato o dedotto" in problems[0]


def test_case_20_a_declared_contradiction_passes_and_an_ignored_one_is_flagged() -> None:
    report = _report("Comedy", {"Conquest of Space (1955)": "contradicted"})
    constructed = "1. **Conquest of Space (1955)** è una commedia di fantascienza ambientata su Marte."

    assert check_answer(REAL_20_GOOD, report, TERMS) == []
    assert check_answer(constructed, report, TERMS) == ["Conquest of Space · Comedy: contraddetto dai dati ma non dichiarato"]


def test_case_20_probable_presented_as_confirmed_is_flagged() -> None:
    report = _report("set on Mars", {"Conquest of Space (1955)": "probable"})
    real = "1. **Conquest of Space (1955)** — l’ambientazione su Marte è probabile, sulla base della trama."
    constructed = "1. **Conquest of Space (1955)** — l’ambientazione su Marte è confermata."

    assert check_answer(real, report, TERMS) == []
    assert "probabile presentato come confermato" in check_answer(constructed, report, TERMS)[0]


# --- cases 11, 12, 13 -------------------------------------------------------------------

def test_case_11_absence_is_not_turned_into_a_negative() -> None:
    report = _report("euthanasia", {"Reach for Me (2009)": "not_verifiable"})
    real = ("### 2. *Reach for Me* — 2008\n- **Vincoli:** il requisito “senza fantascienza” e il genere drammatico "
            "sono confermati. La presenza dell’eutanasia, il tono delicato e la complessità dei personaggi non sono "
            "verificabili dai dati disponibili.")
    constructed = "### 2. *Reach for Me* — 2008\nIl film non tratta l’eutanasia."

    assert check_answer(real, report, TERMS) == []
    assert "assenza presentata come prova negativa" in check_answer(constructed, report, TERMS)[0]


def test_case_12_an_unknown_ending_is_never_deduced() -> None:
    report = _report("non-tragic ending", {"Little Odessa (1994)": "not_verifiable"})
    real = ("### 1. *Little Odessa* (1994)\n- **Vincoli:** conflitto morale, finale non tragico e assenza di una "
            "conclusione tragica non sono verificabili.")
    constructed = "### 1. *Little Odessa* (1994)\nIl finale è sereno e lascia spazio alla speranza."

    assert check_answer(real, report, TERMS) == []
    assert check_answer(constructed, report, TERMS)


def test_case_13_unverifiable_similarity_is_declared() -> None:
    report = _report("similar themes", {"Closed for Winter (2009)": "not_verifiable"})
    real = ("| **Closed for Winter** | 2009 | … |\n\nPer tutti e tre i titoli, la verifica dei vincoli “temi simili”, "
            "“atmosfera simile” e assenza di elementi riconducibili a *Mare dentro* resta **non determinabile dai dati "
            "disponibili**.")

    assert check_answer(real, report, TERMS) == []


# --- what the model receives --------------------------------------------------------------

def _chunk(title, year, genres, plot):
    return {"title": title, "release_year": str(year), "genres": genres, "testo": plot}


MYSTERIANS = _chunk("The Mysterians", 1957, "Alien Film; Japanese Movies; Horror; Science Fiction", "Invaders land near Fuji.")
CONQUEST = _chunk("Conquest of Space", 1955, "Science Fiction; Drama", "Sergeant Imoto, the Japanese crewman, prays.")


def test_catalog_genre_verifies_nationality_and_a_character_does_not() -> None:
    report = constraint_report(QuerySignals(positive_signals=["Japanese"], genres=["Comedy"]), [MYSTERIANS, CONQUEST])
    summary = constraint_summary(report)

    def line(title, constraint):
        return next(entry for entry in summary[title] if entry.startswith(f"{constraint}:"))

    assert line("The Mysterians (1957)", "Japanese").startswith("Japanese: verificato — generi:")
    assert line("Conquest of Space (1955)", "Japanese").startswith("Japanese: non verificabile (non dire né che lo rispetta")
    assert line("Conquest of Space (1955)", "Comedy").startswith("Comedy: contraddetto (dillo esplicitamente)")


def test_the_final_prompt_carries_the_summary_lines() -> None:
    summary = constraint_summary(constraint_report(QuerySignals(positive_signals=["non-tragic ending"]), [CONQUEST]))
    orchestrator = LLMOrchestrator(config={"orchestrator": {}}, tools=[], client=object())

    content = orchestrator._build_final_context(
        query="q", tool_result={"tool_name": "rag_search", "chunks": [], "metadata": {"constraints_summary": summary}}
    )[-1]["content"]

    assert "non-tragic ending: non verificabile (non dire né che lo rispetta né che non lo rispetta, non dedurlo)" in content


def test_case_11_real_v4_declaration_with_confermare_is_accepted() -> None:
    """Real v4 answer: "non è possibile confermare un tema specifico dell’eutanasia"."""
    report = _report("euthanasia", {"Mother and Son (1997)": "not_verifiable"})
    real = ("### 3. *Mother and Son* (1997)\nIl film affronta la cura di una madre morente; dai dati disponibili "
            "non è possibile confermare un tema specifico dell’eutanasia.")

    assert check_answer(real, report, TERMS) == []
