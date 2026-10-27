"""Fixed terminal texts of a turn (headings and labels), by turn language: it, en or de.

Any other turn language gets English (`turn.label_language`). The session texts (banner,
prompt, goodbye) are not here: they belong to no message and stay as they are.
"""
from __future__ import annotations

from turn import label_language

TEXTS = {
    "it": {
        "answer_title": "RISPOSTA FINALE DELL'LLM",
        "compact": "🧠 Soglia raggiunta: history compattata. 💬 Continuiamo!",
        "embedded": "Testo usato per l'embedding",
        "genres": "Generi richiesti",
        "params": "Parametri di ricerca",
        "by_planner": "scelti dal planner",
        "references": "Film di riferimento",
        "guided": "ricerca guidata",
        "not_guided": "ricerca non guidata",
        "similar": "simile a",
        "different": "diverso da",
        "tmdb_calls": "chiamate TMDb",
        "embedding_created": "embedding creato",
        "plot": "TESTO",
        "db_executed": "QUERY ESEGUITE",
        "db_none": "Nessuna query eseguita.",
        "db_query": "QUERY",
    },
    "en": {
        "answer_title": "FINAL ANSWER FROM THE LLM",
        "compact": "🧠 Threshold reached: history compacted. 💬 Let's continue!",
        "embedded": "Text used for the embedding",
        "genres": "Requested genres",
        "params": "Search parameters",
        "by_planner": "chosen by the planner",
        "references": "Reference films",
        "guided": "guided search",
        "not_guided": "search not guided",
        "similar": "similar to",
        "different": "different from",
        "tmdb_calls": "TMDb calls",
        "embedding_created": "embedding created",
        "plot": "PLOT",
        "db_executed": "QUERIES RUN",
        "db_none": "No query run.",
        "db_query": "QUERY",
    },
    "de": {
        "answer_title": "ENDGÜLTIGE ANTWORT DES LLM",
        "compact": "🧠 Schwelle erreicht: Verlauf verdichtet. 💬 Weiter geht's!",
        "embedded": "Für das Embedding verwendeter Text",
        "genres": "Gewünschte Genres",
        "params": "Suchparameter",
        "by_planner": "vom Planer gewählt",
        "references": "Referenzfilme",
        "guided": "geführte Suche",
        "not_guided": "ungeführte Suche",
        "similar": "ähnlich wie",
        "different": "anders als",
        "tmdb_calls": "TMDb-Aufrufe",
        "embedding_created": "Embedding erstellt",
        "plot": "HANDLUNG",
        "db_executed": "AUSGEFÜHRTE ABFRAGEN",
        "db_none": "Keine Abfrage ausgeführt.",
        "db_query": "ABFRAGE",
    },
}


def texts(language: str | None) -> dict[str, str]:
    return TEXTS[label_language(language)]
