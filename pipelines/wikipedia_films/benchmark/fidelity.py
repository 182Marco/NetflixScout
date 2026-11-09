"""Phase 2, step 7: do the summaries keep the narrative content? For a stratified subset of the evaluation sample
(plots summarised at both levels): (1) the LLM extracts a checklist of key narrative elements from the ORIGINAL plot, by
category; (2) for each summary it marks every element as covered / partial / missing and lists statements NOT supported by
the original (unsupported). Results: results/fidelity.json."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from common import RESULTS, llm_json, load_films, ntok

OUT = RESULTS / "fidelity.json"
CATEGORIES = ["motivazioni", "conflitto_principale", "conflitti_secondari", "evoluzione_storia", "temi_sottotesti",
              "relazioni", "elementi_distintivi"]
EXTRACT = (
    "Dalla trama di un film estrai una checklist degli elementi narrativi essenziali, per categoria: "
    + ", ".join(CATEGORIES) + ". Da 1 a 3 voci brevi (una frase) per categoria, solo se la trama le contiene; "
    "ometti le categorie assenti. Rispondi solo con JSON: {{\"voci\": [{{\"id\": 1, \"categoria\": \"...\", \"voce\": \"...\"}}]}}."
)
CHECK = (
    "Ricevi la trama originale di un film, una sua sintesi e una checklist di elementi narrativi. Per ogni voce indica "
    "se la SINTESI la contiene: 1 = presente, 0.5 = presente solo in parte o in modo vago, 0 = assente. Elenca inoltre "
    "le affermazioni della sintesi NON supportate dalla trama originale o in contraddizione con essa (invenzioni o errori). "
    'Rispondi solo con JSON: {{"copertura": {{"<id>": <0|0.5|1>}}, "non_supportate": ["..."]}}.'
)


def main() -> None:
    n_films = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    films = load_films()
    sm = json.loads((RESULTS / "sample.json").read_text())
    summaries = json.loads((RESULTS / "summaries.json").read_text())
    cand = [f for f in sm["sample"] if not summaries[f"B2:{f}"]["kept_original"]]
    cand.sort(key=lambda f: ntok(films[f]["synopsis"]))
    step = len(cand) / n_films
    chosen = [cand[int(i * step)] for i in range(n_films)]
    data = json.loads(OUT.read_text()) if OUT.exists() else {}

    def run(fid):
        if fid in data:
            return fid, data[fid]
        orig = films[fid]["synopsis"]
        voci = llm_json("fidelity:extract", EXTRACT, orig)["voci"]
        checklist = "\n".join(f"{v['id']}. [{v['categoria']}] {v['voce']}" for v in voci)
        res = {"items": voci, "levels": {}}
        for lv in ("B1", "B2"):
            s = summaries[f"{lv}:{fid}"]
            if s["kept_original"]:
                continue
            r = llm_json("fidelity:check", CHECK,
                         f"TRAMA ORIGINALE:\n{orig}\n\nSINTESI:\n{s['text']}\n\nCHECKLIST:\n{checklist}")
            cov = {str(k): float(v) for k, v in r["copertura"].items()}
            res["levels"][lv] = {"coverage": cov, "unsupported": r.get("non_supportate", []),
                                 "orig_tokens": ntok(orig), "summary_tokens": ntok(s["text"])}
        return fid, res

    with ThreadPoolExecutor(6) as ex:
        for n, (fid, res) in enumerate(ex.map(run, chosen), 1):
            data[fid] = res
            if n % 10 == 0:
                OUT.write_text(json.dumps(data, ensure_ascii=False))
                print(n, "/", len(chosen), flush=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False))


if __name__ == "__main__":
    main()
