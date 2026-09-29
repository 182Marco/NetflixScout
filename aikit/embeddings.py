"""embeddings.py — da testo a vettore, con backend selezionabile.

Costruito insieme a Modulo 2 · Lezione 7; da Modulo 2 · Lezione 8 vive nel toolkit aikit/ e NON si tocca.
Il modulo che regge tutto il blocco retrieval (Modulo 2 · Lezione 7-10):

    from aikit.embeddings import embed, cosine_similarity

    vecs = embed(["testo uno", "testo due"], backend="openai")
    print(cosine_similarity(vecs[0], vecs[1]))

Due backend dietro la stessa firma:
  - "openai"  → API text-embedding-3-small (a pagamento, i testi escono)
  - "local"   → sentence-transformers sulla tua macchina (gratis, offline)

Rispetto al file scritto a Modulo 2 · Lezione 7 manca solo la cache su disco: qui non
serve, e senza è più corto e più leggibile. Rilanciare la stessa query
ri-paga l'embedding — parliamo di $0.0000002.
"""
import time

import numpy as np
from dotenv import load_dotenv

load_dotenv()

# Modelli di default dei due backend (verificati live, luglio 2026).
MODELLO_OPENAI = "text-embedding-3-small"   # 1536 dim — $0.02 / 1M token
MODELLO_LOCAL = "all-MiniLM-L6-v2"          # 384 dim — ~88 MB, gira in CPU


# ------------------------------------------------------------ Modulo 2 · Lezione 7 · cosine
def cosine_similarity(a, b):
    """Similarità coseno tra due vettori: cos(θ) = a·b / (|a| |b|).

    Vale 1.0 per vettori paralleli (stesso significato), ~0 per vettori
    ortogonali (nessuna relazione), -1.0 per vettori opposti. Conta l'ANGOLO,
    non la lunghezza: per questo non serve normalizzare prima.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    return float((a @ b) / (np.linalg.norm(a) * np.linalg.norm(b)))


# ---------------------------------------------------- Modulo 2 · Lezione 7 · i due backend
def embed_openai(texts):
    """Embedding via API OpenAI. I testi VIAGGIANO verso il servizio."""
    from openai import OpenAI

    risposta = OpenAI().embeddings.create(model=MODELLO_OPENAI, input=texts)
    token = risposta.usage.total_tokens
    costo = token / 1_000_000 * 0.02       # $0.02 per milione di token
    print(f"  [openai] {len(texts)} testi, {token} token → ${costo:.6f}")
    return np.array([d.embedding for d in risposta.data], dtype=np.float32)


_modello_locale = None   # caricato una volta sola: l'import e il load costano


def embed_local(texts):
    """Embedding con sentence-transformers, sulla TUA macchina.

    Il primo uso scarica il modello (~88 MB) nella cache di Hugging Face;
    da lì in poi è tutto offline e gratis.
    """
    global _modello_locale
    if _modello_locale is None:
        from sentence_transformers import SentenceTransformer

        _modello_locale = SentenceTransformer(MODELLO_LOCAL)
    return np.asarray(_modello_locale.encode(texts), dtype=np.float32)


def embed(texts, backend="openai"):
    """Embedda una lista di testi con il backend scelto."""
    if backend == "openai":
        return embed_openai(texts)
    elif backend == "local":
        return embed_local(texts)
    else:
        raise ValueError(f"backend {backend!r} sconosciuto: 'openai' o 'local'")


# ------------------------------------------------------------- demo a occhio
if __name__ == "__main__":
    frasi = [
        "La scrivania si alza e si abbassa con il doppio motore.",   # A
        "Il piano motorizzato sale e scende in silenzio.",           # B: come A, parole diverse
        "Il reso va richiesto entro trenta giorni dalla consegna.",  # C: altro tema
    ]
    for backend in ("openai", "local"):
        print(f"\nbackend = {backend}")
        inizio = time.perf_counter()
        vecs = embed(frasi, backend=backend)
        print(f"  shape {vecs.shape} in {time.perf_counter() - inizio:.2f}s")
        print(f"  A~B (stesso senso, parole diverse): {cosine_similarity(vecs[0], vecs[1]):.3f}")
        print(f"  A~C (temi diversi):                 {cosine_similarity(vecs[0], vecs[2]):.3f}")
