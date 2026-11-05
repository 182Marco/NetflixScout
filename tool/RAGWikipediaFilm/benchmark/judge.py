"""Phase 2, step 6: pooled relevance judgments. For each query the union of the top-10 of every pooling system is judged
(0/1/2) by the LLM on the ORIGINAL plot (never the summary). The source film is a known relevant item (grade 2).
Judgments are written incrementally to results/judgments.json (resumable)."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from common import RESULTS, ENC, llm_json, load_films
from retrieval import CONFIGS, rankings

OUT = RESULTS / "judgments.json"
DEPTH = 10
BATCH = 10
INSTRUCTIONS = (
    "Sei un valutatore di un sistema di raccomandazione cinematografica. Ricevi la richiesta di un utente e una lista "
    "di trame di film numerate. Per ogni trama assegna un grado di pertinenza alla richiesta:\n"
    "2 = il film corrisponde chiaramente alla richiesta (struttura narrativa, temi e conflitti, trasformazione del "
    "protagonista o atmosfera, secondo ciò che la richiesta chiede; se chiede più caratteristiche, tutte rispettate);\n"
    "1 = corrisponde solo in parte (alcuni aspetti ma non l'insieme o non l'aspetto principale);\n"
    "0 = non corrisponde, o solo per somiglianze superficiali (stesso genere, epoca o ambientazione ma storia o temi diversi).\n"
    "Giudica sul contenuto della trama, non sul titolo né sul genere dichiarato. Rispondi solo con un oggetto JSON "
    '{{"gradi": {{"<numero>": <0|1|2>, ...}}}} con una voce per ogni trama.'
)


def shown(text: str, limit: int = 1500) -> str:
    ids = ENC.encode(text, disallowed_special=())
    if len(ids) <= limit:
        return text
    return ENC.decode(ids[:1200]) + " […] " + ENC.decode(ids[-300:])


def main() -> None:
    films = load_films()
    queries = json.loads((RESULTS / "queries.json").read_text())
    runs = rankings({k: CONFIGS[k] for k in CONFIGS})
    pools = {q["qid"]: set() for q in queries}
    for (variant, cname), r in runs.items():
        for qi, q in enumerate(queries):
            pools[q["qid"]] |= {r["films"][j] for j in r["top"][qi, :DEPTH]}
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    jobs = []
    for q in queries:
        todo = sorted(f for f in pools[q["qid"]] if f != q["source"] and f not in data.get(q["qid"], {}))
        for i in range(0, len(todo), BATCH):
            jobs.append((q, todo[i:i + BATCH]))
    print("queries", len(queries), "pooled (query,film) pairs", sum(len(p) for p in pools.values()),
          "to judge", sum(len(t) for _, t in jobs), "calls", len(jobs), flush=True)
    if "--dry" in sys.argv:
        return

    def run(job):
        q, fids = job
        listing = "\n\n".join(f"[{n}] {shown(films[f]['synopsis'])}" for n, f in enumerate(fids, 1))
        res = llm_json("judge", INSTRUCTIONS, f"Richiesta: {q['text']}\n\nTrame:\n\n{listing}")
        grades = res["gradi"]
        return q["qid"], {f: int(grades[str(n)]) for n, f in enumerate(fids, 1)}

    with ThreadPoolExecutor(6) as ex:
        for n, (qid, g) in enumerate(ex.map(run, jobs), 1):
            data.setdefault(qid, {}).update(g)
            if n % 20 == 0:
                OUT.write_text(json.dumps(data))
                print(n, "/", len(jobs), flush=True)
    for q in queries:
        data.setdefault(q["qid"], {})[q["source"]] = 2  # known relevant item (by construction)
    OUT.write_text(json.dumps(data))
    json.dump({q["qid"]: sorted(pools[q["qid"]]) for q in queries}, open(RESULTS / "pools.json", "w"))


if __name__ == "__main__":
    main()
