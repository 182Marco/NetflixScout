from __future__ import annotations

from pathlib import Path

from .vectorstore import db_dir_for_backend


def _resolve_runtime_config(config: dict) -> dict:
    db_root = Path("dbVettoriale")
    vectorstore_config = dict(config["vectorstore"])
    embedding_config = dict(config["embedding"])

    if vectorstore_config["db_dir"]:
        db_dir = Path(vectorstore_config["db_dir"])
        effective_backend = embedding_config["backend"]
    else:
        openai_dir = db_root / "openai"
        local_dir = db_root / "local"

        if openai_dir.exists() and not local_dir.exists():
            effective_backend = "openai"
        elif local_dir.exists() and not openai_dir.exists():
            effective_backend = "local"
        else:
            effective_backend = embedding_config["backend"]

        db_dir = db_dir_for_backend(effective_backend)

    runtime_config = {
        **config,
        "retrieval": dict(config["retrieval"]),
        "rerank": dict(config["rerank"]),
        "generation": dict(config["generation"]),
        "conversation": dict(config["conversation"]),
        "embedding": {**embedding_config, "backend": effective_backend},
        "vectorstore": {**vectorstore_config, "db_dir": db_dir},
    }

    return runtime_config
