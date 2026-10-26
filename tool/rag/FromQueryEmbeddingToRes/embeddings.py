"""Embedding helpers and vector similarity utilities."""

import numpy as np
from dotenv import load_dotenv

load_dotenv()

def cosine_similarity(a, b):
    """Compute cosine similarity between two vectors."""

    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)

    return float(
        (a @ b) /
        (np.linalg.norm(a) * np.linalg.norm(b))
    )


def embed_openai(texts, model, timeout=None):
    """Create embeddings through OpenAI's embeddings API.

    `timeout` (seconds) is for callers that run inside a turn and cannot wait: it is applied with
    no retry. Without it the client behaves exactly as before.
    """

    from openai import OpenAI

    client = OpenAI(timeout=timeout, max_retries=0) if timeout else OpenAI()
    batch_size = 1000
    embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]

        risposta = client.embeddings.create(
            model=model,
            input=batch,
        )

        embeddings.extend(
            d.embedding for d in risposta.data
        )

    return np.array(
        embeddings,
        dtype=np.float32,
    )


_modelli_locali = {}


def embed_local(texts, model):
    """Create embeddings with a local sentence-transformers model."""
    if model not in _modelli_locali:
        from sentence_transformers import SentenceTransformer

        _modelli_locali[model] = SentenceTransformer(
            model,
            device="cpu",
        )

    return np.asarray(
        _modelli_locali[model].encode(texts),
        dtype=np.float32,
    )


def embed(texts, backend, model, timeout=None):
    """Embed a list of texts with the chosen backend and model."""
    if backend == "openai":
        return embed_openai(texts, model) if timeout is None else embed_openai(texts, model, timeout)
    elif backend == "local":
        return embed_local(texts, model)

    else:
        raise ValueError(
            f"backend {backend!r} sconosciuto: "
            "'openai' o 'local'"
        )