"""tools.py — il giro del tool calling e i quattro tool di Modulo 3 · Lezione 7-8, nel toolkit aikit/.

È il file finito di Modulo 3 · Lezione 8 (solutions/tools.py), promosso in
aikit/ con lo stesso rito di rag.py, hybrid.py e rerank.py: cambiano la
riga SCRIPTS (sta un livello più in basso e risale di tre cartelle invece
di due) e le intestazioni delle sezioni, perché prezzo_prodotto non è più
un esercizio: l'avete scritta voi. Si importa:

    from aikit.tools import (Calcolatrice, calcolatrice, DataOggi, data_oggi,
                             QueryDb, query_db, PrezzoProdotto, prezzo_prodotto,
                             definisci_tool)

Oggi (Modulo 3 · Lezione 9) working/assistente.py prende da qui gli SCHEMI
(le classi Pydantic, la cui docstring è la descrizione che il modello
legge), le FUNZIONI dei quattro tool e definisci_tool(); la lista TOOLS,
esegui() e il giro chiedi() li riscrive per conto suo, perché deve
aggiungere il tool cerca_documenti e il log della strada presa. Il main
qui sotto è quello di Modulo 3 · Lezione 8 e si può ancora lanciare.

Il file, dall'alto in basso:

  1   Calcolatrice + calcolatrice(), DataOggi + data_oggi() (Modulo 3 · Lezione 7);
  2   QueryDb, con lo schema del database nella docstring, e query_db(sql):
      sola lettura, solo SELECT, al massimo LIMITE righe, errori restituiti
      come testo (Modulo 3 · Lezione 8, codice spiegato);
  3   PrezzoProdotto + prezzo_prodotto(codice): il prezzo di listino con una
      query fissa (Modulo 3 · Lezione 8, esercizio);
  4   definisci_tool() e TOOLS;
  5   esegui(nome, argomenti);
  6   chiedi(domanda): il giro, con un tetto alle chiamate.

Uso (dalla cartella scripts/):
    python scaffolding/aikit/tools.py
"""
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Literal

SCRIPTS = Path(__file__).parent.parent.parent   # scripts/, tre livelli sopra
sys.path.insert(0, str(SCRIPTS / "scaffolding"))

from dotenv import load_dotenv                   # noqa: E402
from openai import OpenAI                        # noqa: E402
from pydantic import BaseModel                   # noqa: E402 — Modulo 2 · Lezione 13

from aikit.llm_client import cost_usd            # noqa: E402 — Modulo 2 · Lezione 3

load_dotenv(".env")                    # OPENAI_API_KEY
client = OpenAI()

MODELLO = "gpt-5.6-luna"                         # è in PRICING di llm_client: cost_usd sa quanto costa (Luna da Modulo 3 · Lezione 11; prima gpt-4.1-mini)
ISTRUZIONI = "Rispondi in italiano, in una frase, senza domande di cortesia."   # valgono a ogni chiamata del giro
DB = SCRIPTS / "dataset" / "lumen.db"            # il database degli ordini Lumen
LIMITE = 50                                      # righe massime che query_db rimanda al modello: bastano per rispondere, costano poco
MAX_CHIAMATE = 6                                 # tetto al giro: con gli errori che tornano al modello, potrebbe non finire (6 = qualche correzione, non di più)

# Le domande del main: un conteggio, uno stato degli ordini, un prezzo.
DOMANDE = [
    "Quanti ordini ha fatto Giulia Moretti?",
    "Quanti ordini sono ancora in viaggio?",
    "Quanto costa la LMX-4400?",
]
SOLO = None      # una domanda sola al posto delle altre, per provare: SOLO = "Quanto costa la LMX-4400?"


# ---------------------------------- 1 · calcolatrice e data · Modulo 3 · Lezione 7
class Calcolatrice(BaseModel):                   # la docstring qui sotto è la descrizione che il modello legge
    """Esegue un'operazione aritmetica tra due numeri e ritorna il risultato esatto."""
    a: float
    b: float
    operazione: Literal["+", "-", "*", "/"]      # nello schema diventa un enum: il modello non può inventarne altre


def calcolatrice(a, b, operazione):
    """La funzione vera: la eseguiamo NOI, il modello la chiede soltanto."""
    if operazione == "+":
        return a + b
    if operazione == "-":
        return a - b
    if operazione == "*":
        return a * b
    return a / b


class DataOggi(BaseModel):
    """Ritorna la data di oggi, nel formato AAAA-MM-GG."""
    pass


def data_oggi():
    return date.today().isoformat()


# ------------------------- 2 · il database · Modulo 3 · Lezione 8, codice spiegato
class QueryDb(BaseModel):
    """Esegue una query SQL (solo SELECT, dialetto SQLite) sul database degli
    ordini Lumen e ritorna le righe trovate. Tabelle e colonne:
    prodotti(codice TEXT, nome TEXT, categoria TEXT, prezzo REAL)
    clienti(id INTEGER, nome TEXT, tipo TEXT, citta TEXT, data_registrazione TEXT)
    ordini(id INTEGER, cliente_id INTEGER, data TEXT, stato TEXT, data_consegna TEXT, spese_spedizione REAL)
    righe_ordine(id INTEGER, ordine_id INTEGER, codice_prodotto TEXT, quantita INTEGER, prezzo_unitario REAL)"""
    sql: str                                     # il modello non vede i dati: vede solo questo schema


def query_db(sql):
    """Esegue la query scritta dal modello, in sola lettura. Ritorna le
    righe come testo; se qualcosa va storto ritorna l'errore come testo,
    così il modello lo legge e può correggere la query."""
    if not sql.strip().lower().startswith("select"):   # strip e lower: vale anche per " select …"
        return "Errore: sono ammesse solo query SELECT."
    try:
        con = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)   # mode=ro: il file non si può modificare (as_uri regge anche cartelle con # o spazi; uri=True serve a leggere «?mode=ro»)
        cursore = con.execute(sql)                   # qui il testo scritto dal modello diventa una query eseguita
        colonne = [c[0] for c in cursore.description]   # description: una tupla per colonna, il nome è il primo campo
        righe = cursore.fetchmany(LIMITE + 1)    # una in più, per sapere se ce n'erano altre
        con.close()                              # se c'è un errore non ci arriva: la connessione si chiude a fine programma, va bene così
    except Exception as e:                       # colonna sbagliata, sintassi, file mancante, due query in una…
        return f"Errore: {e}"                    # NON si solleva: torna al modello, che può correggersi
    testo = " | ".join(colonne)                  # una riga per l'intestazione, poi una per riga, colonne separate da |
    for riga in righe[:LIMITE]:
        testo += "\n" + " | ".join(str(valore) for valore in riga)
    if len(righe) > LIMITE:
        testo += f"\n(mostrate solo le prime {LIMITE} righe)"
    return testo


# ------------------------------ 3 · prezzo_prodotto · scritta a Modulo 3 · Lezione 8
# Il modello passa solo il codice: la query è fissa, con il segnaposto ? e
# il valore a parte, mai il codice incollato nella stringa.
class PrezzoProdotto(BaseModel):
    """Ritorna nome e prezzo di listino (euro, IVA inclusa) di un prodotto Lumen dato il suo codice, per esempio LD-210."""
    codice: str


def prezzo_prodotto(codice):
    """Ritorna una stringa con nome e prezzo di listino del prodotto con quel
    codice, o un messaggio chiaro se non si trova. La riga si legge con
    fetchone(), che ritorna None se il codice non c'è."""
    codice = codice.strip().upper()              # " lmx-4400" → "LMX-4400"
    try:
        con = sqlite3.connect(DB.as_uri() + "?mode=ro", uri=True)   # mode=ro: se il file manca non ne crea uno vuoto
        riga = con.execute("SELECT nome, prezzo FROM prodotti WHERE codice = ?", (codice,)).fetchone()
        con.close()
    except Exception:                            # file che manca, o lumen.db vuoto rimasto da una prova
        return "Errore: il listino dei prodotti non è raggiungibile."
    if riga is None:                             # fetchone() dà None se il codice non c'è
        return f"Nessun prodotto con codice {codice} nel listino."
    return f"{codice} — {riga[0]}: {riga[1]:.2f} euro"


# ---------------------------------- 4 · la definizione dei tool · Modulo 3 · Lezione 7
def definisci_tool(schema, nome):
    """Dallo schema Pydantic alla definizione che l'API si aspetta: un
    dict con il nome, la descrizione (la docstring dello schema) e i
    parametri in JSON Schema (model_json_schema()). È il testo che il
    modello legge per decidere SE e COME chiamare il tool."""
    return {
        "type": "function",
        "name": nome,
        "description": schema.__doc__,
        "parameters": schema.model_json_schema(),
        "strict": False,                         # la modalità strict vuole uno schema più rigido di questo: non serve
    }


# La lista che il modello vede a ogni chiamata.
TOOLS = [
    definisci_tool(Calcolatrice, "calcolatrice"),
    definisci_tool(DataOggi, "data_oggi"),
    definisci_tool(QueryDb, "query_db"),
    definisci_tool(PrezzoProdotto, "prezzo_prodotto"),
]


# ------------------------------- 5 · l'esecuzione · Modulo 3 · Lezione 7-8
def esegui(nome, argomenti):
    """Esegue il tool che il modello ha chiesto: nome come in TOOLS,
    argomenti già convertiti in dict. Ritorna il risultato."""
    if nome == "calcolatrice":
        return calcolatrice(argomenti["a"], argomenti["b"], argomenti["operazione"])
    if nome == "data_oggi":
        return data_oggi()
    if nome == "query_db":
        return query_db(argomenti["sql"])
    if nome == "prezzo_prodotto":
        return prezzo_prodotto(argomenti["codice"])
    raise ValueError(f"tool sconosciuto: {nome}")


# ----------------------------------------------- 6 · il giro · Modulo 3 · Lezione 7-8
def chiedi(domanda):
    """Il giro del tool calling. Chiama il modello con la domanda e la
    lista dei tool; se nell'output ci sono item function_call, esegue
    ognuno e rimanda il risultato come function_call_output con lo
    stesso call_id; ripete finché il modello risponde con testo, o fino
    a MAX_CHIAMATE. Ritorna il testo della risposta."""
    storia = [{"role": "user", "content": domanda}]   # la conversazione: la domanda, poi ciò che si aggiunge a ogni giro
    n_chiamate = 0
    costo = 0.0
    while True:
        if n_chiamate == MAX_CHIAMATE:           # il tetto al giro (Modulo 3 · Lezione 8)
            stampa_costo(n_chiamate, costo)
            return f"(mi fermo: {MAX_CHIAMATE} chiamate senza una risposta)"
        r = client.responses.create(
            model=MODELLO,
            instructions=ISTRUZIONI,
            input=storia,
            tools=TOOLS,
        )
        n_chiamate += 1
        costo += cost_usd(MODELLO, r.usage.input_tokens, r.usage.output_tokens)
        stampa_chiamata(n_chiamate, r)

        storia += r.output                       # TUTTO l'output torna nell'input, anche le function_call
        chiamate = [item for item in r.output if item.type == "function_call"]
        if not chiamate:                         # niente da eseguire: è la risposta
            stampa_costo(n_chiamate, costo)
            return r.output_text                 # il testo del message, già estratto dagli item

        for chiamata in chiamate:                # può chiederne più d'uno nella stessa risposta
            argomenti = json.loads(chiamata.arguments)   # arguments è una STRINGA JSON
            risultato = esegui(chiamata.name, argomenti)
            stampa_esecuzione(chiamata.name, argomenti, risultato)
            storia.append({
                "type": "function_call_output",
                "call_id": chiamata.call_id,     # lo stesso della richiesta: così il modello sa a cosa risponde
                "output": str(risultato),        # sempre una stringa
            })


# ------------------------------------------------- helper di stampa (dati)
# Producono le righe «chiamata 1  [137 token in, 27 out] …» che si vedono a schermo.
def stampa_chiamata(n, r):
    """Una riga per chiamata: i token e cosa c'è nell'output."""
    item = []
    for i in r.output:
        if i.type == "function_call":
            item.append(f"function_call {i.name}({i.arguments})")
        else:
            item.append(i.type)
    print(f"   chiamata {n}  [{r.usage.input_tokens} token in, {r.usage.output_tokens} out]  output: " + " · ".join(item))


def stampa_esecuzione(nome, argomenti, risultato):
    """Il risultato di una query può essere lungo: se ne stampano al
    massimo sei righe (il modello riceve tutto)."""
    righe = str(risultato).split("\n")
    print(f"      eseguo {nome}: " + righe[0])
    for riga in righe[1:6]:
        print("         " + riga)
    if len(righe) > 6:
        print(f"         … altre {len(righe) - 6} righe")


def stampa_costo(n, costo):
    print(f"   {n} chiamat{'a' if n == 1 else 'e'} · ${costo:.5f}")


if __name__ == "__main__":
    domande = [SOLO] if SOLO else DOMANDE
    for domanda in domande:
        print("\n" + "=" * 72)
        print(f"D: {domanda}")
        risposta = chiedi(domanda)
        print(f"→ {risposta}")
