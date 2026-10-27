from __future__ import annotations


def _resolve_runtime_config(config: dict) -> dict:
    """Runtime copy of the RAG configuration: the index meta must match the embedding model used for queries."""
    vectorstore_config = dict(config["vectorstore"])
    embedding_config = dict(config["embedding"])

    if vectorstore_config.get("qdrant") is not None:
        vectorstore_config["qdrant"] = {**vectorstore_config["qdrant"], "model": embedding_config["model"]}

    conversation_config = config.get(
        "conversation",
        {
            "token_threshold": 40000,
            "compact_model": "gpt-5.6-luna",
            "compact_instructions": (
                "Compatta la conversazione mantenendo continuita operativa. "
                "Produci solo markdown con sezioni: FATTO, DECISIONE, APERTO, IPOTESI. "
                "Includi esclusivamente elementi ancora utili per i prossimi turni. "
                "Rimuovi output rumoroso, duplicazioni, tentativi superati e dettagli obsoleti."
            ),
        },
    )

    runtime_config = {
        **config,
        "retrieval": dict(config["retrieval"]),
        "rerank": dict(config["rerank"]),
        "generation": dict(config["generation"]),
        "conversation": dict(conversation_config),
        "embedding": embedding_config,
        "vectorstore": vectorstore_config,
    }

    return runtime_config
