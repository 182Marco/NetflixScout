"""Text chunking helpers."""

from aikit.embeddings import embed, cosine_similarity


def chunk_fixed(testo, size, overlap):
    """Split text into fixed-size character windows with overlap."""
    pezzi = []
    inizio = 0
    while inizio < len(testo):
        pezzi.append(testo[inizio:inizio + size])
        inizio = inizio + size - overlap
    return pezzi


def chunk_recursive(testo, size):
    """Split text on the strongest separator that fits inside the target size."""
    if len(testo) <= size:
        return [testo]
    finestra = testo[:size]
    for separatore in ("\n\n", "\n", ". "):
        posizione = finestra.rfind(separatore)
        if posizione > 0:
            pezzo = testo[:posizione]
            resto = testo[posizione + len(separatore):]
            return [pezzo] + chunk_recursive(resto, size)
    return [finestra] + chunk_recursive(testo[size:], size)


def chunk_semantic(testo, soglia, backend, model):
    """Split text when semantic similarity between adjacent sentences drops below a threshold."""
    frasi = []
    for riga in testo.split("\n"):
        for frase in riga.split(". "):
            if frase.strip():
                frasi.append(frase.strip())

    vettori = embed(frasi, backend=backend, model=model)

    pezzi = []
    corrente = [frasi[0]]
    for i in range(1, len(frasi)):
        simile = cosine_similarity(vettori[i - 1], vettori[i])
        if simile < soglia:
            pezzi.append(" ".join(corrente))
            corrente = []
        corrente.append(frasi[i])
    pezzi.append(" ".join(corrente))
    return pezzi
