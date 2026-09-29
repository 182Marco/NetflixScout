"""hybrid.py — la ricerca per parole (BM25) accanto a quella per significato, fuse con RRF.

rag.recupera() (Modulo 3 · Lezione 2, in aikit/) cerca solo per
SIGNIFICATO: embedding della domanda, coseno con i chunk. Su un codice
(«Cosa è successo nel ticket TCK-1152?») il significato non aiuta: TCK-1152
non ha sinonimi, e l'embedding lo confonde con gli altri ticket che parlano
dello stesso tema — il chunk giusto c'è, ma dietro. Stasera si aggiunge la
ricerca per PAROLE e si fondono i due ranking:

  1-2 (codice spiegato)   l'indice BM25 sugli stessi 82 chunk della
                          collection lumen_m3, e cerca_bm25(query, k): sono
                          già scritte, il docente le spiega;
  TODO 3-4 (esercizio)    rrf(liste, k), la fusione che usa solo il rango,
                          e cerca_hybrid(query, k) che mette insieme le due
                          ricerche.

Il main lancia prima la query della demo (semantico vs BM25 fianco a
fianco), poi tutto il QUERY_SET nelle tre modalità: la tabella in fondo al
file si compila guardando quell'output. La consegna completa è in
CONSEGNA.md.

Da Modulo 3 · Lezione 5 vive in aikit/, promosso con lo stesso rito di
rag.py: è il file finito di Modulo 3 · Lezione 4 (solutions/hybrid.py),
cambiano la riga SCRIPTS (sta un livello più in basso e risale di tre
cartelle invece di due) e le intestazioni delle funzioni 3-4, non più
«TODO» perché le avete scritte voi. Si importa:

    from aikit import hybrid

    hybrid.costruisci_indice_bm25()                  # una volta, all'avvio
    chunks = hybrid.cerca_hybrid("una domanda", 10)  # semantico + BM25, fusi con RRF

Uso (dalla cartella scripts/):
    python scaffolding/aikit/hybrid.py
"""
import re
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent.parent   # scripts/, tre livelli sopra
sys.path.insert(0, str(SCRIPTS / "scaffolding"))

from rank_bm25 import BM25Okapi                  # noqa: E402 — la libreria di stasera

from aikit import rag                            # noqa: E402 — Modulo 3 · Lezione 2
from aikit import vectorstore                    # noqa: E402 — Modulo 2 · Lezione 9

# ---------------------------------------- il punto unico di configurazione
CONFIG = {
    "k": 3,               # chunk mostrati per ogni modalità
    "candidati": 10,      # quanti ne chiede cerca_hybrid() a ciascuna lista prima di fondere
    "rrf_costante": 60,   # la costante di RRF: 1 / (60 + posizione)
}

# La query della demo del codice spiegato: un ticket citato per codice.
DOMANDA_DEMO = "Cosa è successo nel ticket TCK-1152?"

# Il query set fisso del modulo: da stasera a Modulo 3 · Lezione 6 si giudica
# sempre su queste tredici domande (l'esito si annota nella tabella in fondo).
QUERY_SET = [
    "Cosa è successo nel ticket TCK-1152?",
    "Cosa copre SRV-02?",
    "Com'è stato risolto il TCK-1201?",
    "Con l'errore E07, per quanti secondi devo scollegare l'alimentazione?",
    "Quale RMA devo aprire per un danno da trasporto?",
    "Cosa ha introdotto il firmware 2.3.0?",
    "La scrivania non sta ferma, si muove tutta quando scrivo: che controllo faccio?",
    "Quanto tempo ho per richiedere il contributo per la postazione di casa?",
    "Posso lavorare dall'estero?",
    "Il monitor scende piano piano da solo: cosa faccio?",
    "Ho comprato con un codice sconto: posso restituire?",
    "Perché il piano si ferma sempre a metà corsa?",
    "Posso pagare alla consegna, in contrassegno?",
]

# L'indice BM25: lo riempie costruisci_indice_bm25(), lo legge cerca_bm25().
INDICE = {}


def tokenizza(testo):
    """Da testo a lista di token: minuscole, solo lettere e numeri.
    «Cosa copre SRV-02?» → ['cosa', 'copre', 'srv', '02']. BM25 confronta
    QUESTI token, esatti: niente sinonimi, niente parafrasi."""
    return re.findall(r"\w+", testo.lower())


# ------------------------------------ 1 · costruisci_indice_bm25() · 🎤 codice spiegato, già scritto
def costruisci_indice_bm25():
    """Legge tutti i chunk della collection di rag.py
    (vectorstore.apri_collection(rag.CONFIG["collection"]) e poi
    collection.get(), il metodo ChromaDB che ritorna ids, documents e
    metadatas di tutto senza query), li tokenizza e costruisce l'indice
    BM25Okapi. Riempie il dizionario INDICE dichiarato sopra (INDICE["bm25"]
    = l'indice, INDICE["chunks"] = la lista dei chunk nello stesso ordine,
    dict con "id", "testo", "source"), senza ricrearlo. Ritorna quanti
    chunk ha indicizzato."""
    collection = vectorstore.apri_collection(rag.CONFIG["collection"])   # la stessa di rag.py
    dati = collection.get()                       # tutti i chunk, senza query: ids, documents, metadatas
    chunks = []
    for i in range(len(dati["ids"])):             # un dict per chunk, come li ritorna rag.recupera()
        chunks.append({
            "id": dati["ids"][i],
            "testo": dati["documents"][i],
            "source": dati["metadatas"][i]["source"],
        })
    corpus_token = [tokenizza(c["testo"]) for c in chunks]   # una lista di token per chunk
    INDICE["bm25"] = BM25Okapi(corpus_token)      # l'indice: nessuna chiamata, una frazione di secondo
    INDICE["chunks"] = chunks                     # stesso ordine dell'indice: da una posizione si risale al chunk
    return len(chunks)


# ------------------------------------ 2 · cerca_bm25() · 🎤 codice spiegato, già scritto
def cerca_bm25(query, k):
    """I k chunk con lo score BM25 più alto per la query, dal più alto in
    giù: la stessa forma di rag.recupera() (dict con "id", "testo",
    "score", "source"), ma lo score è quello di BM25."""
    punteggi = INDICE["bm25"].get_scores(tokenizza(query))   # uno per chunk
    # ordino gli INDICI (non i punteggi): da un indice risalgo al chunk
    ordine = sorted(range(len(punteggi)), key=lambda i: punteggi[i], reverse=True)
    risultati = []
    for i in ordine[:k]:                          # i primi k, nella forma di rag.recupera(): così rrf() tratta le due liste allo stesso modo
        risultati.append({**INDICE["chunks"][i], "score": float(punteggi[i])})
    return risultati


# ------------------------------ 3 · rrf() · scritta a Modulo 3 · Lezione 4
def rrf(liste, k):
    """Reciprocal Rank Fusion: da più liste ordinate di chunk a una sola.
    Ogni chunk (riconosciuto dal suo "id", uguale in tutte le liste) vale 1 / (CONFIG["rrf_costante"] + posizione) in ogni lista
    in cui compare (posizione a partire da 1), e i contributi si sommano.
    Ritorna i k chunk con la somma più alta, con "score" = la somma."""
    somme = {}
    visti = {}
    for lista in liste:
        for posizione, chunk in enumerate(lista, start=1):
            somme[chunk["id"]] = somme.get(chunk["id"], 0) + 1 / (CONFIG["rrf_costante"] + posizione)
            visti[chunk["id"]] = chunk
    migliori = sorted(somme, key=somme.get, reverse=True)[:k]
    return [{**visti[cid], "score": somme[cid]} for cid in migliori]


# ----------------------- 4 · cerca_hybrid() · scritta a Modulo 3 · Lezione 4
def cerca_hybrid(query, k):
    """La ricerca ibrida: CONFIG["candidati"] chunk dal semantico
    (rag.recupera) e altrettanti da BM25 (cerca_bm25), fusi con rrf().
    Ritorna i k chunk in testa alla fusione."""
    semantici = rag.recupera(query, CONFIG["candidati"])
    keyword = cerca_bm25(query, CONFIG["candidati"])
    return rrf([semantici, keyword], k)


# ------------------------------------------------- helper di stampa (dati)
def stampa_confronto(query, colonne):
    """Le modalità fianco a fianco: per ognuna i chunk in ordine, uno per
    riga (posizione, id, score, inizio del testo). colonne è una lista di
    (nome, risultati)."""
    print("\n" + "=" * 78)
    print(f"D: {query}")
    for nome, risultati in colonne:
        print(f"  [{nome}]")
        if risultati is None:
            print("     (ancora da scrivere)")
            continue
        for posizione, c in enumerate(risultati, start=1):
            anteprima = " ".join(c["testo"].split())[:44]
            print(f"     {posizione}. {c['id']:<24} score={c['score']:8.3f}  {anteprima}…")


def _prova(funzione, *args):
    """Chiama la funzione; se è un TODO non ancora scritto ritorna None."""
    try:
        return funzione(*args)
    except NotImplementedError:
        return None


if __name__ == "__main__":
    # La collection del modulo: si indicizza solo se è vuota (come a
    # Modulo 3 · Lezione 2-3, costa meno di un centesimo).
    if vectorstore.apri_collection(rag.CONFIG["collection"]).count() == 0:
        rag.indicizza()

    # --- codice spiegato: l'indice BM25 e la demo sul codice prodotto
    n = _prova(costruisci_indice_bm25)
    if n is None:
        raise SystemExit("costruisci_indice_bm25() manca o è rotta: nel file consegnato è già scritta, si riparte da solutions/hybrid.py.")
    print(f"indice BM25: {n} chunk, {len(INDICE['bm25'].idf)} termini distinti")

    k = CONFIG["k"]
    stampa_confronto(DOMANDA_DEMO, [
        ("semantico", rag.recupera(DOMANDA_DEMO, k)),
        ("bm25", _prova(cerca_bm25, DOMANDA_DEMO, k)),
    ])
    if _prova(cerca_bm25, DOMANDA_DEMO, k) is None:
        raise SystemExit("cerca_bm25() manca o è rotta: nel file consegnato è già scritta, si riparte da solutions/hybrid.py.")

    # --- esercizio: il query set nelle tre modalità
    print("\n\n" + "#" * 78 + "\n# IL QUERY SET NELLE TRE MODALITÀ\n" + "#" * 78)
    for domanda in QUERY_SET:
        stampa_confronto(domanda, [
            ("semantico", rag.recupera(domanda, k)),
            ("bm25", cerca_bm25(domanda, k)),
            ("hybrid", _prova(cerca_hybrid, domanda, k)),
        ])


# ------------------------------------------------- la tabella da compilare
# Per ogni query del set: qual è il chunk giusto (dall'anteprima stampata),
# e in che posizione sta nelle tre modalità. Il main stampa i primi
# CONFIG["k"] (3): se il chunk giusto non c'è, alza k a 10 e rilancia;
# oltre il decimo posto si scrive —.
# Si compila a mano guardando l'output del main; è il deliverable della
# serata insieme al codice.
#
# | #  | query (inizio)              | chunk giusto | semantico | bm25 | hybrid |
# |----|-----------------------------|--------------|-----------|------|--------|
# | 1  | …ticket TCK-1152?           |              |           |      |        |
# | 2  | Cosa copre SRV-02?          |              |           |      |        |
# | 3  | …risolto il TCK-1201?       |              |           |      |        |
# | 4  | Con l'errore E07…           |              |           |      |        |
# | 5  | Quale RMA devo aprire…      |              |           |      |        |
# | 6  | …firmware 2.3.0?            |              |           |      |        |
# | 7  | La scrivania non sta ferma… |              |           |      |        |
# | 8  | Quanto tempo ho…            |              |           |      |        |
# | 9  | Posso lavorare dall'estero? |              |           |      |        |
# | 10 | Il monitor scende…          |              |           |      |        |
# | 11 | Ho comprato con un codice…  |              |           |      |        |
# | 12 | Perché il piano si ferma…   |              |           |      |        |
# | 13 | Posso pagare alla consegna… |              |           |      |        |
