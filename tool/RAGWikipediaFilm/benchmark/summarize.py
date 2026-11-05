"""Phase 2, step 3: LLM summaries of the pool at two compression levels (B1 moderate, B2 strong).
A plot already about as short as the target is kept as is (the LLM could only lose information).
Results are written incrementally to results/summaries.json (resumable)."""
from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

from common import RESULTS, load_films, llm, ntok

OUT = RESULTS / "summaries.json"
LEVELS = {"B1": (0.40, 90, 250), "B2": (0.15, 40, 90)}  # ratio of original words, min words, max words
INSTRUCTIONS = (
    "Condensa la trama di un film in italiano per un sistema di ricerca semantica. Conserva: i personaggi "
    "principali e le loro relazioni, le motivazioni e i desideri, i conflitti principali e secondari, lo sviluppo "
    "e l'evoluzione della storia fino alla conclusione, i temi e i sottotesti, gli elementi distintivi "
    "(ambientazione, epoca, tono). Non inventare nulla, non aggiungere giudizi o commenti, non tralasciare le "
    "sottotrame importanti. Usa i nomi propri. Prosa continua, senza elenchi né titoli. Rispondi solo con la "
    "sintesi, di circa {words} parole."
)


def target_words(level: str, original: str) -> int | None:
    ratio, lo, hi = LEVELS[level]
    w = len(original.split())
    target = int(min(hi, max(lo, ratio * w)))
    return None if w <= 1.25 * target else target  # None = keep the original


def main() -> None:
    films = load_films()
    ids = json.loads((RESULTS / "sample.json").read_text())["pool"]
    if len(sys.argv) > 1:
        ids = ids[: int(sys.argv[1])] if sys.argv[1].isdigit() else ids
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    jobs = []
    for fid in ids:
        for level in LEVELS:
            key = f"{level}:{fid}"
            if key in data:
                continue
            t = target_words(level, films[fid]["synopsis"])
            if t is None:
                data[key] = {"text": films[fid]["synopsis"], "kept_original": True}
            else:
                jobs.append((key, fid, level, t))

    def run(job):
        key, fid, level, t = job
        text = llm(f"summary:{level}", INSTRUCTIONS.format(words=t), films[fid]["synopsis"]).strip()
        return key, {"text": text, "kept_original": False, "target_words": t}

    with ThreadPoolExecutor(6) as pool:
        for n, (key, val) in enumerate(pool.map(run, jobs), 1):
            data[key] = val
            if n % 25 == 0:
                OUT.write_text(json.dumps(data))
                print(n, "/", len(jobs), flush=True)
    OUT.write_text(json.dumps(data))
    print("jobs", len(jobs), "total entries", len(data))


if __name__ == "__main__":
    main()
