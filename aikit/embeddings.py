"""embeddings.py — da testo a vettore, con backend selezionabile.

Costruito insieme a Modulo 2 · Lezione 7; da Modulo 2 · Lezione 8 vive nel toolkit aikit/ e NON si tocca.
Il modulo che regge tutto il blocco retrieval (Modulo 2 · Lezione 7-10):

    from aikit.embeddings import embed, cosine_similarity

    vecs = embed(["testo uno", "testo due"], backend="openai")
    print(cosine_similarity(vecs[0], vecs[1]))

Due backend dietro la stessa firma:
  - "openai"  → API text-embedding-3-small (a pagamento, i testi escono)
  - "local"   → sentence-transformers sulla tua macchina (gratis, offline)

Il vector store viene salvato in:

    dbVettoriale/
    ├── openai/
    │   ├── embeddings.npy
    │   └── metadata.json
    └── local/
        ├── embeddings.npy
        └── metadata.json
"""

import json
from pathlib import Path

import numpy as np
from dotenv import load_dotenv

load_dotenv()

# Modelli di default dei due backend
MODELLO_OPENAI = "text-embedding-3-small"   # 1536 dim
MODELLO_LOCAL = "all-MiniLM-L6-v2"          # 384 dim

# Cartella principale del database vettoriale
CARTELLA_DB = Path("dbVettoriale")


# ------------------------------------------------------------ Modulo 2 · Lezione 7 · cosine

def cosine_similarity(a, b):
    """Similarità coseno tra due vettori."""

    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)

    return float(
        (a @ b) /
        (np.linalg.norm(a) * np.linalg.norm(b))
    )


# ---------------------------------------------------- Modulo 2 · Lezione 7 · i due backend

def embed_openai(texts):
    """Embedding via API OpenAI. I testi VIAGGIANO verso il servizio."""

    from openai import OpenAI

    client = OpenAI()
    batch_size = 1000
    embeddings = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]

        risposta = client.embeddings.create(
            model=MODELLO_OPENAI,
            input=batch,
        )

        token = risposta.usage.total_tokens
        costo = token / 1_000_000 * 0.02

        print(
            f"  [openai] {len(batch)} testi, "
            f"{token} token → ${costo:.6f}"
        )

        embeddings.extend(
            d.embedding for d in risposta.data
        )

    return np.array(
        embeddings,
        dtype=np.float32,
    )


_modello_locale = None


def embed_local(texts):
    """Embedding con sentence-transformers, sulla TUA macchina."""

    global _modello_locale

    if _modello_locale is None:
        from sentence_transformers import SentenceTransformer

        _modello_locale = SentenceTransformer(
            MODELLO_LOCAL,
            device="cpu",
        )

    return np.asarray(
        _modello_locale.encode(texts),
        dtype=np.float32,
    )


def embed(texts, backend="openai"):
    """Embedda una lista di testi con il backend scelto."""
    if backend == "openai":
        return embed_openai(texts)
    elif backend == "local":
        return embed_local(texts)

    else:
        raise ValueError(
            f"backend {backend!r} sconosciuto: "
            "'openai' o 'local'"
        )


# ------------------------------------------------------------ vector store

def cartella_backend(backend):
    """Restituisce la cartella del vector store del backend."""

    if backend not in ("openai", "local"):
        raise ValueError(
            f"backend {backend!r} sconosciuto: "
            "'openai' o 'local'"
        )

    cartella = CARTELLA_DB / backend
    cartella.mkdir(
        parents=True,
        exist_ok=True,
    )

    return cartella


def salva_vector_store(
    records,
    backend,
):
    """Salva embeddings e metadata nel database del backend."""

    cartella = cartella_backend(backend)

    file_embeddings = cartella / "embeddings.npy"
    file_metadata = cartella / "metadata.json"

    embeddings = np.array(
        [
            record["embedding"]
            for record in records
        ],
        dtype=np.float32,
    )

    metadata = [
        {
            "id": record["id"],
            "testo": record["testo"],
            "metadata": record["metadata"],
            "source": record["source"],
        }
        for record in records
    ]

    np.save(
        file_embeddings,
        embeddings,
    )

    file_metadata.write_text(
        json.dumps(
            metadata,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"\nVector store {backend} salvato:"
    )
    print(
        f"  embeddings: {file_embeddings}"
    )
    print(
        f"  metadata:   {file_metadata}"
    )
    print(
        f"  shape:      {embeddings.shape}"
    )


def carica_vector_store(backend):
    """Carica il vector store del backend richiesto."""

    cartella = cartella_backend(backend)

    file_embeddings = cartella / "embeddings.npy"
    file_metadata = cartella / "metadata.json"

    if not file_embeddings.exists():
        raise FileNotFoundError(
            f"Embeddings non trovati: {file_embeddings}"
        )

    if not file_metadata.exists():
        raise FileNotFoundError(
            f"Metadata non trovati: {file_metadata}"
        )

    embeddings = np.load(
        file_embeddings
    )

    metadata = json.loads(
        file_metadata.read_text(
            encoding="utf-8"
        )
    )

    return embeddings, metadata


# ------------------------------------------------------------ creazione record

def crea_record(
    chunk,
    embedding,
    metadata=None,
    id=None,
    source=None,
):
    """Crea un record del vector store."""

    if metadata is None:
        metadata = {}

    return {
        "id": id,
        "testo": chunk,
        "embedding": embedding,
        "metadata": metadata,
        "source": source,
    }


# ------------------------------------------------------------ ricerca

def cerca(
    query,
    backend="openai",
    k=3,
):
    """Cerca i chunk semanticamente più simili alla query."""

    embeddings, metadata = carica_vector_store(
        backend
    )

    query_embedding = embed(
        [query],
        backend=backend,
    )[0]

    scores = np.array([
        cosine_similarity(
            query_embedding,
            embedding,
        )
        for embedding in embeddings
    ])

    indici = np.argsort(scores)[::-1][:k]

    risultati = []

    for indice in indici:
        risultato = metadata[indice].copy()

        risultato["score"] = float(
            scores[indice]
        )

        risultati.append(risultato)

    return risultati