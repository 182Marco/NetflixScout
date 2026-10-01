"""rag.py — la pipeline RAG del modulo, nel toolkit aikit/.

È il file scritto a Modulo 3 · Lezione 2 (tre funzioni piatte e un CONFIG
in cima), promosso in aikit/ a Modulo 3 · Lezione 3 con lo stesso rito di
embeddings.py, vectorstore.py e chunk.py nel Modulo 2. Si importa:

    from aikit import rag

    chunks = rag.recupera("una domanda", 4)          # i k chunk più pertinenti
    risposta = rag.genera(chunks, "una domanda")     # il generate, sui chunk dati
    risposta, usati = rag.rispondi("una domanda")    # recupera + genera, single-turn

Rispetto alla versione di Modulo 3 · Lezione 2 cambiano due cose. La riga
SCRIPTS: il file sta un livello più in basso (scaffolding/aikit/ invece
di solutions/) e risale di tre cartelle invece di due. E la generazione,
modificata IN AULA a Modulo 3 · Lezione 3 (live coding di apertura):
rispondi() faceva tre cose in una — recupera, costruisce il prompt, chiama
il modello — e non c'era modo di darle chunk diversi o una storia. Ora la
generazione è una funzione a sé, genera(chunks, domanda, storia=None), le
regole del prompt stanno in ISTRUZIONI, e rispondi(query, storia=None) è
genera(recupera(query), query, storia). Tutto il resto è identico; sopra
le funzioni non ci sono più i «TODO 1-3» di Modulo 3 · Lezione 2.

Le quattro funzioni, sulle tre interfacce dell'architettura RAG
(Modulo 3 · Lezione 1):

    indicizza()                      l'INGEST: corpus → chunk → embedding → collection
    recupera(query, k)               il RETRIEVE: domanda → i k chunk più pertinenti
    genera(chunks, domanda, storia)  il GENERATE: chunk + domanda (+ storia) → risposta
    rispondi(query, storia)          recupera + genera → (risposta, chunk usati)

Chi ha chunk diversi (hybrid search, re-ranking) o una storia (chat.py)
chiama genera() con i suoi: la generazione non si riscrive.
"""
import sys
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent.parent   # scripts/, tre livelli sopra
sys.path.insert(0, str(SCRIPTS / "scaffolding"))

from dotenv import load_dotenv               # noqa: E402
from openai import OpenAI                    # noqa: E402

from aikit.loaders import load               # noqa: E402 — Modulo 2 · Lezione 4
from aikit.clean import clean, pipeline_for  # noqa: E402 — Modulo 2 · Lezione 5
from aikit.chunk import chunk_recursive      # noqa: E402 — Modulo 2 · Lezione 10
from aikit.embeddings import embed           # noqa: E402 — Modulo 2 · Lezione 7
from aikit import vectorstore                # noqa: E402 — Modulo 2 · Lezione 9

load_dotenv()

client = OpenAI()

# ---------------------------------------- il punto unico di configurazione
# Tutto ciò che nel Progetto Modulo 2 stava sparso nel codice ora sta qui:
# per cambiare un parametro si tocca UNA riga, e si vede subito cosa c'è da
# tarare. Da Modulo 3 · Lezione 4 in poi le manopole si girano da qui.
CONFIG = {
    "corpus_dir": SCRIPTS / "dataset" / "lumen_m3",  # i sei documenti Lumen
    "collection": "lumen_m3",       # la collection del modulo, si indicizza una volta
    "chunk_size": 500,              # recursive, come nel Modulo 2
    "k": 4,                         # chunk recuperati per domanda
    "modello": "gpt-5.6-luna",      # il generator (Luna da Modulo 3 · Lezione 11; prima gpt-4o-mini)
    "embedding_backend": "openai",  # lo stesso backend per ingest e query
}

# Le regole del prompt RAG di Modulo 2 · Lezione 11, nelle instructions:
# valgono per ogni chiamata, single-turn o con una storia davanti. È il
# testo tagliato dal vecchio prompt di rispondi(); cambia una parola —
# «nei documenti del messaggio», non più «qui sotto» — perché ora i
# documenti stanno nel messaggio user e le regole qui.
ISTRUZIONI = """Rispondi alla domanda usando SOLO le informazioni nei documenti
del messaggio. 
Non cercare su intenet. 
Non usare id film e markup nella risposta.
Prima dell'inizio del consiglio riporta titolo, anno più il genere tra parentesi.
Poi spiega le motivazioni del consiglio con il tono informale, caldo e amabile di un amico che vuole spiegare quali film sono adatti alla richiesta. Riporta i passaggi specifici trovati che te lo fanno pensare dando dettagli emozionanti rispetto a ciò
che l'utente cerca. Se la risposta non è nei
documenti, rispondi esattamente: "Non lo trovo nei documenti." — senza
inventare nulla."""


# ------------------------- indicizza · scritta a Modulo 3 · Lezione 2
def indicizza():
    """L'ingest: load → clean → chunk → embed → upsert, su tutto il corpus.

    Ricrea la collection da ZERO (vectorstore.crea_collection): rilanciare
    non raddoppia i chunk. Stampa il conteggio per documento e ritorna il
    numero totale di chunk indicizzati.
    """
    collection = vectorstore.crea_collection(CONFIG["collection"])
    ids, testi, meta = [], [], []
    for percorso in sorted(CONFIG["corpus_dir"].glob("*.txt")):
        documenti = load(str(percorso))                                  # Modulo 2 · Lezione 4
        testo_grezzo = "\n".join(d.text for d in documenti)
        testo_pulito = clean(testo_grezzo, pipeline_for(str(percorso)))  # Modulo 2 · Lezione 5
        pezzi = chunk_recursive(testo_pulito, CONFIG["chunk_size"])      # Modulo 2 · Lezione 10
        for i, pezzo in enumerate(pezzi):
            ids.append(f"{percorso.stem}-{i:03d}")
            testi.append(pezzo)
            meta.append({"source": percorso.name})
        print(f"  {percorso.stem}: {len(pezzi)} chunk")
    vettori = embed(testi, backend=CONFIG["embedding_backend"])         # Modulo 2 · Lezione 7
    vectorstore.indicizza(collection, ids, testi, vettori, meta)
    print(f"indicizzati {len(testi)} chunk da {len(list(CONFIG['corpus_dir'].glob('*.txt')))} "
          f"documenti in '{CONFIG['collection']}'")
    return len(testi)


# -------------------------- recupera · scritta a Modulo 3 · Lezione 2
def recupera(query, k=None):
    """Il retrieve: i k chunk più pertinenti per la query, dal più simile.

    Ogni chunk è un dict {"id", "testo", "score", "source"}. Se k non è
    indicato vale quello di CONFIG. La collection si riapre qui dentro con
    vectorstore.apri_collection(CONFIG["collection"]).
    """
    if k is None:
        k = CONFIG["k"]
    collection = vectorstore.apri_collection(CONFIG["collection"])
    return vectorstore.search(collection, query, k, backend=CONFIG["embedding_backend"])


# ----------------------------------- genera · 🎤 Modulo 3 · Lezione 3
def genera(chunks, domanda, storia=None):
    """Il generate da solo: il prompt RAG di Modulo 2 · Lezione 11 (sezioni
    marcate: i chunk, la domanda) e la chiamata al modello, con le regole
    in ISTRUZIONI. Ritorna il testo della risposta.

    storia è la lista dei messaggi precedenti (user/assistant, Modulo 3 ·
    Lezione 3): va nell'input DAVANTI al messaggio del turno, così il
    modello vede i turni prima di questo. Senza storia è il single-turn
    di Modulo 3 · Lezione 2.
    """
    documenti = ""
    for c in chunks:
        meta = []
        if c.get("title"):
            meta.append(f"titolo: {c['title']}")
        if c.get("release_year"):
            meta.append(f"anno: {c['release_year']}")
        if c.get("release_date"):
            meta.append(f"data_uscita: {c['release_date']}")
        if c.get("genres"):
            meta.append(f"generi: {c['genres']}")
        if c.get("cast"):
            meta.append(f"cast: {c['cast']}")
        meta_testo = "\n".join(meta)
        documento = f"<documento>\n{meta_testo}\n<trama>\n{c['testo']}\n</trama>\n</documento>\n"
        documenti += documento
    prompt = f"<documenti>\n{documenti}</documenti>\n\n<domanda>\n{domanda}\n</domanda>"

    if storia is None:
        storia = []
    r = client.responses.create(
        model=CONFIG["modello"],
        instructions=ISTRUZIONI,
        input=storia + [{"role": "user", "content": prompt}],
    )
    return r.output_text


# -------------------------- rispondi · scritta a Modulo 3 · Lezione 2
def rispondi(query, storia=None):
    """recupera() + genera(), in una riga. Ritorna (risposta, chunks): i
    chunk che hanno fatto da contesto sono lo strumento di debug del
    modulo. Senza storia è il single-turn di Modulo 3 · Lezione 2.
    """
    chunks = recupera(query)
    return genera(chunks, query, storia), chunks


# ------------------------------------------------- helper di stampa (dati)
def stampa_chunks(chunks):
    """I chunk recuperati, uno per riga: posizione, id, score, anteprima."""
    for posizione, c in enumerate(chunks, start=1):
        anteprima = " ".join(c["testo"].split())[:58]
        print(f"   {posizione}. {c['id']}  score={c['score']:.3f}  {anteprima}…")
