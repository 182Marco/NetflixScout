"""Phase 2, step 4: 72 retrieval queries (12 for each of 6 types), written by the LLM from the ORIGINAL plot of a
source film, in Italian, without names/places and with paraphrase instead of the plot's own words.
The source film is a known relevant item; other relevant films are found by pooled judging (evaluate.py)."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor

from common import RESULTS, load_films, llm

OUT = RESULTS / "queries.json"
TYPES = {
    "analogy": "analogia narrativa: la richiesta descrive la struttura della storia (cosa succede e perché) usando parole "
               "completamente diverse da quelle della trama, in modo che la somiglianza sia di storia e non di lessico",
    "themes_conflicts": "temi e conflitti: la richiesta chiede film costruiti attorno ai temi e al conflitto centrale di "
                        "questa storia (per esempio lealtà contro interesse, colpa, appartenenza), senza raccontare la trama",
    "psych_transformation": "trasformazione psicologica: la richiesta descrive come cambia interiormente il protagonista "
                            "(da che stato a che stato e per quale ragione), senza dettagli di ambientazione",
    "atmosphere_situation": "atmosfera e situazione: la richiesta descrive il clima emotivo, il tono e la situazione di "
                            "partenza (isolamento, attesa, minaccia sottile...), non gli eventi",
    "multi_subplot": "più sottotrame: la richiesta chiede una storia corale o con più fili narrativi intrecciati e ne "
                     "descrive almeno due in modo astratto, con le sfumature del loro rapporto",
    "combined": "richiesta combinata: tre caratteristiche insieme (per esempio un tipo di conflitto, un tono e un "
                "tipo di personaggio o di epoca generica) espresse in modo naturale in un'unica richiesta",
}
INSTRUCTIONS = (
    "Sei una persona che cerca un film da guardare e non ricorda il titolo. Scrivi la richiesta che faresti a un "
    "assistente cinematografico, in italiano, in una o tre frasi naturali, ispirata al film la cui trama ricevi. "
    "NON nominare titolo, personaggi, attori, registi, città, paesi o oggetti specifici e non riusare le parole "
    "distintive della trama: usa sinonimi e astrazioni. Deve poter corrispondere a più film, non essere un "
    "identikit unico. Tipo di richiesta: {focus}. Rispondi solo con il testo della richiesta."
)


def main() -> None:
    films = load_films()
    sources = json.loads((RESULTS / "sample.json").read_text())["sources"]
    # round-robin over types, sources are already ordered by length bin (18 per bin) -> 3 per type per bin
    plan = [(f"q{n:02d}", list(TYPES)[n % len(TYPES)], fid) for n, fid in enumerate(sources)]

    def run(item):
        qid, qtype, fid = item
        text = llm("queries", INSTRUCTIONS.format(focus=TYPES[qtype]), films[fid]["synopsis"]).strip().strip('"')
        return {"qid": qid, "type": qtype, "source": fid, "text": text}

    with ThreadPoolExecutor(6) as pool:
        out = list(pool.map(run, plan))
    words = lambda s: set(re.findall(r"\w{4,}", s.lower()))
    for q in out:  # lexical overlap of the query with its source plot (reported, not filtered)
        w = words(q["text"])
        q["overlap"] = round(len(w & words(films[q["source"]]["synopsis"])) / max(1, len(w)), 3)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(len(out), "queries; mean overlap", round(sum(q["overlap"] for q in out) / len(out), 3))
    for q in out[:6]:
        print(q["qid"], q["type"], "|", q["text"])


if __name__ == "__main__":
    main()
