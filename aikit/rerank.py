"""rerank.py — il secondo stadio: riordinare i candidati leggendo domanda e chunk insieme.

hybrid.cerca_hybrid() (Modulo 3 · Lezione 4, in aikit/) mette il chunk
giusto in top-3 su tutte le query con un codice, ma non sempre primo: su
«Cosa copre SRV-02?» il listino è secondo, dietro la garanzia SRV-03, e
su tre domande concettuali la fusione ha fatto scendere il chunk giusto.
Il primo stadio confronta domanda e chunk SEPARATAMENTE (un vettore, una
lista di token, una distanza): quando due chunk dicono quasi la stessa
cosa non li separa. A Modulo 3 · Lezione 5 si è aggiunto un secondo stadio
che legge la COPPIA domanda + chunk e la giudica:

  1 (codice spiegato)     rerank_cohere(query, chunks): la top-k dell'hybrid
                          riordinata da Cohere Rerank, un cross-encoder
                          servito via API;
  2-3 (esercizio)         rerank_llm(query, chunks), lo stesso lavoro fatto
                          dal modello generico con lo structured output di
                          Modulo 2 · Lezione 13, e cerca_due_stadi(), che
                          mette in fila primo e secondo stadio.

Da Modulo 3 · Lezione 6 vive in aikit/, promosso con lo stesso rito di
rag.py e hybrid.py: è il file finito di Modulo 3 · Lezione 5
(solutions/rerank.py), cambiano la riga SCRIPTS (sta un livello più in
basso e risale di tre cartelle invece di due) e le intestazioni delle
funzioni 2-3, non più «TODO» perché le avete scritte voi. Si importa:

    from aikit import rerank

    chunks = rerank.cerca_due_stadi("una domanda", 10, 3, "cohere")   # o "llm"

Il main è quello di Modulo 3 · Lezione 5 (la demo su SRV-02, poi il
QUERY_SET nelle tre modalità): si può ancora lanciare, ma il file di oggi
è working/debug.py.

Uso (dalla cartella scripts/):
    python scaffolding/aikit/rerank.py
"""
import os
import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).parent.parent.parent   # scripts/, tre livelli sopra
sys.path.insert(0, str(SCRIPTS / "scaffolding"))

import cohere                                    # noqa: E402 — la libreria di stasera
from dotenv import load_dotenv                   # noqa: E402
from openai import OpenAI                        # noqa: E402
from pydantic import BaseModel                   # noqa: E402 — Modulo 2 · Lezione 13

from aikit import rag                            # noqa: E402 — Modulo 3 · Lezione 2
from aikit import hybrid                         # noqa: E402 — Modulo 3 · Lezione 4
from aikit import vectorstore                    # noqa: E402 — Modulo 2 · Lezione 9

load_dotenv(SCRIPTS / ".env")                    # OPENAI_API_KEY e COHERE_API_KEY

# ---------------------------------------- il punto unico di configurazione
CONFIG = {
    "k_largo": 10,                    # candidati del primo stadio (hybrid) che il reranker riordina
    "k_finale": 3,                    # quanti ne restano dopo il rerank
    "modello_cohere": "rerank-v3.5",  # il cross-encoder di Cohere
    "modello_llm": "gpt-5.6-luna",    # il modello generico usato come reranker (Luna da Modulo 3 · Lezione 11; prima gpt-4o-mini)
    "pausa": 6,                       # secondi tra una domanda e l'altra: la chiave Trial di Cohere fa 10 chiamate al minuto
}

# La query della demo del codice spiegato: la lezione scorsa l'hybrid la
# lasciava seconda, dietro la garanzia SRV-03.
DOMANDA_DEMO = "Cosa copre SRV-02?"

# Il query set fisso del modulo (Modulo 3 · Lezione 4): stesse tredici
# domande, stasera con una colonna in più per ogni backend.
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

# Chi non ha la chiave Cohere lavora col solo backend LLM: il main salta la
# colonna cohere invece di fermarsi.
HA_COHERE = bool(os.getenv("COHERE_API_KEY"))
cohere_client = cohere.ClientV2(api_key=os.getenv("COHERE_API_KEY") or "manca")
client = OpenAI()


# --------------------- 1 · rerank_cohere() · codice spiegato a Modulo 3 · Lezione 5
def rerank_cohere(query, chunks):
    """Riordina i chunk con Cohere Rerank: UNA chiamata con la domanda e i
    testi di tutti i chunk, il modello legge ogni coppia domanda + chunk
    e dà un punteggio di pertinenza. Ritorna gli stessi chunk dal più
    pertinente in giù, con "score" = relevance score (tra 0 e 1)."""
    risposta = cohere_client.rerank(
        model=CONFIG["modello_cohere"],
        query=query,
        documents=[c["testo"] for c in chunks],   # solo i testi: il modello non sa cos'è un chunk
        top_n=len(chunks),                         # li rivogliamo tutti, riordinati
    )
    riordinati = []
    for r in risposta.results:                     # già in ordine di pertinenza
        riordinati.append({**chunks[r.index], "score": r.relevance_score})   # r.index = posizione nella lista che abbiamo mandato
    return riordinati


# ------------------------- 2 · rerank_llm() · scritta a Modulo 3 · Lezione 5
class Ordine(BaseModel):
    """La risposta del modello: gli indici dei chunk, dal più al meno pertinente."""
    indici: list[int]


def rerank_llm(query, chunks):
    """Riordina i chunk con l'LLM: un prompt con la domanda e i chunk
    numerati ([0], [1], …), e responses.parse() con text_format=Ordine
    (Modulo 2 · Lezione 13) per farsi restituire gli indici in ordine di
    pertinenza. Ritorna gli stessi chunk in quell'ordine, con "score" =
    quanti ne restano dietro (il primo vale len(chunks), l'ultimo 1): il
    modello dà un ordine, non un punteggio. Il modello può ripetere un
    indice o saltarne uno: nel risultato ogni chunk deve tornare una volta
    sola, e tutti. Stampa i token usati: risposta.usage.input_tokens e
    output_tokens."""
    elenco = ""
    for i, c in enumerate(chunks):
        elenco += f"[{i}] {c['testo']}\n\n"
    prompt = (f"Domanda: {query}\n\nPassaggi numerati:\n\n{elenco}"
              "Ordina TUTTI i passaggi dal più al meno utile per rispondere alla domanda. "
              "Restituisci gli indici in quell'ordine, ognuno una sola volta.")
    risposta = client.responses.parse(model=CONFIG["modello_llm"], input=prompt, text_format=Ordine)
    print(f"  [llm] {risposta.usage.input_tokens} token in, {risposta.usage.output_tokens} out")

    ordine = []
    for i in risposta.output_parsed.indici:       # solo indici validi, una volta sola
        if 0 <= i < len(chunks) and i not in ordine:
            ordine.append(i)
    for i in range(len(chunks)):                  # se il modello ne ha saltato qualcuno, in coda
        if i not in ordine:
            ordine.append(i)
    riordinati = []
    for posizione, i in enumerate(ordine):
        riordinati.append({**chunks[i], "score": float(len(chunks) - posizione)})
    return riordinati


# --------------------- 3 · cerca_due_stadi() · scritta a Modulo 3 · Lezione 5
def cerca_due_stadi(query, k_largo, k_finale, backend):
    """La ricerca a due stadi: primo stadio hybrid.cerca_hybrid(query,
    k_largo), secondo stadio rerank_cohere() o rerank_llm() a seconda di
    backend ("cohere" oppure "llm"). Ritorna i primi k_finale chunk
    riordinati."""
    candidati = hybrid.cerca_hybrid(query, k_largo)
    if backend == "cohere":
        riordinati = rerank_cohere(query, candidati)
    else:
        riordinati = rerank_llm(query, candidati)
    return riordinati[:k_finale]


# ------------------------------------------------- helper di stampa (dati)
def stampa_domanda(query):
    """L'intestazione di un blocco di confronto."""
    print("\n" + "=" * 78)
    print(f"D: {query}")


def stampa_confronto(colonne):
    """Le modalità fianco a fianco: per ognuna i chunk in ordine, uno per
    riga (posizione, id, score, inizio del testo). colonne è una lista di
    (nome, risultati, secondi); secondi può essere None."""
    for nome, risultati, secondi in colonne:
        tempo = f"  ({secondi:.2f} s)" if secondi is not None else ""
        print(f"  [{nome}]{tempo}")
        if risultati is None:
            print("     (ancora da scrivere)")
            continue
        if risultati == []:
            print("     (senza COHERE_API_KEY in .env: si salta)")
            continue
        for posizione, c in enumerate(risultati, start=1):
            anteprima = " ".join(c["testo"].split())[:44]
            print(f"     {posizione}. {c['id']:<24} score={c['score']:8.3f}  {anteprima}…")


def _prova(funzione, *args):
    """Chiama la funzione e misura i secondi; se è un TODO non ancora
    scritto ritorna (None, None)."""
    inizio = time.time()
    try:
        return funzione(*args), time.time() - inizio
    except NotImplementedError:
        return None, None


if __name__ == "__main__":
    # La collection e l'indice BM25 del modulo, come a Modulo 3 · Lezione 4.
    if vectorstore.apri_collection(rag.CONFIG["collection"]).count() == 0:
        rag.indicizza()
    hybrid.costruisci_indice_bm25()

    k_largo, k_finale = CONFIG["k_largo"], CONFIG["k_finale"]

    # --- codice spiegato: la top-10 dell'hybrid, riordinata da Cohere
    stampa_domanda(DOMANDA_DEMO)
    candidati = hybrid.cerca_hybrid(DOMANDA_DEMO, k_largo)
    if HA_COHERE:
        riordinati, secondi = _prova(rerank_cohere, DOMANDA_DEMO, candidati)
        if riordinati is None:
            raise SystemExit("rerank_cohere() manca o è rotta: nel file consegnato è già scritta, si riparte da solutions/rerank.py.")
        riordinati = riordinati[:k_finale]
    else:
        riordinati, secondi = [], None             # senza chiave: la colonna si salta
    stampa_confronto([
        (f"hybrid, primi {k_finale} di {k_largo}", candidati[:k_finale], None),
        (f"cohere, primi {k_finale} di {k_largo}", riordinati, secondi),
    ])
    if riordinati:
        time.sleep(CONFIG["pausa"])               # anche dopo la demo: la prima chiamata del ciclo arriva subito dopo

    # --- esercizio: il query set con e senza rerank
    print("\n\n" + "#" * 78 + "\n# IL QUERY SET CON E SENZA RERANK\n" + "#" * 78)
    for domanda in QUERY_SET:
        stampa_domanda(domanda)
        if HA_COHERE:
            cohere_ris, s_cohere = _prova(cerca_due_stadi, domanda, k_largo, k_finale, "cohere")
        else:
            cohere_ris, s_cohere = [], None
        llm_ris, s_llm = _prova(cerca_due_stadi, domanda, k_largo, k_finale, "llm")
        stampa_confronto([
            ("hybrid", hybrid.cerca_hybrid(domanda, k_finale), None),
            ("cohere", cohere_ris, s_cohere),
            ("llm", llm_ris, s_llm),
        ])
        if cohere_ris:                            # c'è stata una chiamata Cohere: il free tier fa 10 chiamate al minuto
            time.sleep(CONFIG["pausa"])


# ------------------------------------------------- la tabella da compilare
# Per ogni query del set: la posizione del chunk giusto in hybrid / cohere
# / llm (— = oltre la terza), e i secondi delle due chiamate come li
# stampa il main. La colonna del chunk giusto è già compilata: è la
# tabella della lezione scorsa. Si compila a mano guardando l'output; è il
# deliverable della serata insieme al codice.
#
# | #  | query (inizio)              | chunk giusto             | hybrid | cohere | llm | s cohere | s llm |
# |----|-----------------------------|--------------------------|--------|--------|-----|----------|-------|
# | 1  | …ticket TCK-1152?           | ticket-supporto-008      |        |        |     |          |       |
# | 2  | Cosa copre SRV-02?          | listino-catalogo-006     |        |        |     |          |       |
# | 3  | …risolto il TCK-1201?       | ticket-supporto-004      |        |        |     |          |       |
# | 4  | Con l'errore E07…           | manuale-lumadesk-009     |        |        |     |          |       |
# | 5  | Quale RMA devo aprire…      | listino-catalogo-008     |        |        |     |          |       |
# | 6  | …firmware 2.3.0?            | changelog-rilasci-002    |        |        |     |          |       |
# | 7  | La scrivania non sta ferma… | manuale-lumadesk-013     |        |        |     |          |       |
# | 8  | Quanto tempo ho…            | guida-smart-working-004  |        |        |     |          |       |
# | 9  | Posso lavorare dall'estero? | guida-smart-working-009  |        |        |     |          |       |
# | 10 | Il monitor scende…          | ticket-supporto-007      |        |        |     |          |       |
# | 11 | Ho comprato con un codice…  | policy-resi-garanzia-007 |        |        |     |          |       |
# | 12 | Perché il piano si ferma…   | ticket-supporto-003      |        |        |     |          |       |
# | 13 | Posso pagare alla consegna… | — (fuori corpus)         |        |        |     |          |       |
