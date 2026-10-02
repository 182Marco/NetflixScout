from __future__ import annotations

from rag.FromQueryEmbeddingToRes.chat import run_conversation_loop
from rag.FromQueryEmbeddingToRes.models import RerankBackend, SearchMode


RAG_CONFIG = {
    "retrieval": {
        "search_mode": SearchMode.semantic,
        "k_largo": 10,
        "k_finale": 3,
        "rrf_costante": 60,
    },
    "rerank": {
        "backend": RerankBackend.cohere,
        "cohere_model": "rerank-v3.5",
        "llm_model": "gpt-5.6-luna",
    },
    "generation": {
        "model": "gpt-5.6-luna",
        "instructions": (
            "Rispondi alla domanda usando solo le informazioni nei documenti del messaggio. "
            "Non cercare su internet. "
            "Non usare id film o markup nella risposta. "
            "Prima del consiglio riporta titolo, anno e genere tra parentesi. "
            "Poi spiega le motivazioni del consiglio con tono informale, caldo e amabile, "
            "citando i passaggi specifici che motivano la scelta. "
            'Se la risposta non e presente nei documenti, rispondi esattamente: "Non lo trovo nei documenti."'
        ),
    },
    "conversation": {
        "token_threshold": 60000,
        "compact_model": "gpt-5.6-luna",
        "compact_instructions": (
            "Compatta la conversazione mantenendo continuita operativa. "
            "Produci solo markdown con sezioni: FATTO, DECISIONE, APERTO, IPOTESI. "
            "Includi esclusivamente elementi ancora utili per i prossimi turni. "
            "Rimuovi output rumoroso, duplicazioni, tentativi superati e dettagli obsoleti."
        ),
    },
    "embedding": {
        "backend": "openai",
        "model": "text-embedding-3-small",
    },
    "vectorstore": {
        "collection": "netflix_scout",
        "db_dir": None,
    },
}

NON_CINEMA_BLOCK_MESSAGES = {
    "it": "Non rispondo a domande non cinematografiche",
    "en": "I do not answer non-film questions",
}

EXIT_COMMANDS = {"exit", "quit"}
COMPACT_NOTICE = "🧠 Soglia 60k raggiunta: history compattata. 💬 Continuiamo!"


def main() -> None:
    run_conversation_loop(
        config=RAG_CONFIG,
        exit_commands=EXIT_COMMANDS,
        compact_notice=COMPACT_NOTICE,
    )


if __name__ == "__main__":
    main()
