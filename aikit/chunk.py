"""chunk.py — le tre strategie di chunking di Modulo 2 · Lezione 10, da oggi nel toolkit aikit/.

Sono le funzioni che avete scritto a Modulo 2 · Lezione 10 (fixed, recursive) più quella
mostrata in demo dal docente (semantic), promosse in aikit/ — lo stesso
percorso di embeddings.py, search.py e vectorstore.py. NON si toccano, si
importano:

    from aikit.chunk import chunk_fixed, chunk_recursive, carica_documenti

Oggi (Modulo 2 · Lezione 12) servono per il Lab 2: si ri-chunka con una configurazione diversa,
si re-indicizza `lumen_chunks` (`aikit.vectorstore.crea_collection`, che
CANCELLA e ricrea) e si confronta la risposta finale sulle stesse query.
"""
from pathlib import Path

from aikit.embeddings import embed, cosine_similarity

DATASET = Path(__file__).parent.parent.parent / "dataset"


def chunk_fixed(testo, size, overlap):
    """Blocchi di `size` caratteri; ogni blocco riparte `overlap` caratteri
    prima della fine del precedente. Restituisce la lista dei pezzi."""
    pezzi = []
    inizio = 0
    while inizio < len(testo):
        pezzi.append(testo[inizio:inizio + size])
        inizio = inizio + size - overlap
    return pezzi


def chunk_recursive(testo, size):
    """Taglia sull'ULTIMO separatore che ci sta in `size` caratteri, provando
    i separatori dal più forte al più debole (paragrafo, riga, frase); se
    nessuno ci sta, taglio secco a `size`. Poi riparte sul resto. Restituisce
    pezzi lunghi al massimo `size`."""
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


def chunk_semantic(testo, soglia):
    """Taglia dove il DISCORSO cambia: embedda le frasi una per una e chiude
    il chunk quando la similarità tra una frase e la successiva scende sotto
    `soglia` — un calo di similarità è un cambio di argomento."""
    frasi = []
    for riga in testo.split("\n"):
        for frase in riga.split(". "):
            if frase.strip():
                frasi.append(frase.strip())

    vettori = embed(frasi)

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


def carica_documenti():
    """I 3 documenti lunghi di Lumen, da dataset/: {nome: testo}."""
    documenti = {}
    for percorso in sorted(DATASET.glob("*.txt")):
        documenti[percorso.stem] = percorso.read_text(encoding="utf-8")
    return documenti


def mostra_chunk(pezzi):
    """Com'è venuto lo spezzatino: taglia e confini di ogni chunk."""
    for numero, pezzo in enumerate(pezzi):
        pulito = " ".join(pezzo.split())
        print(f"  {numero:3d} · {len(pezzo):4d} car · "
              f"{pulito[:34]} ⟨…⟩ {pulito[-34:]}")
