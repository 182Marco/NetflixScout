"""Live check of the TMDb completion in IMDb mode (no OpenAI): one `/find` per returned film, posters, identity by IMDb id, nothing written.

    python -m tool.RAGWikipediaFilm.eval.tmdb_enrich_live"""
from __future__ import annotations

import importlib
import json
import random
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    app = importlib.import_module("app")
    built = app.build_app()
    orch = built["orchestrator"]
    films = [json.loads(l) for l in (ROOT / "data/clean_v3/films.v3.jsonl").open(encoding="utf-8")]
    rng = random.Random(20261105)
    with_imdb = rng.sample([f for f in films if f.get("imdb_id")], 30)
    without = [f for f in films if not f.get("imdb_id")][:3]
    rows, report = [], []
    for batch in (with_imdb[i:i + 5] for i in range(0, 30, 5)):
        chunks = [{"id": f["film_id"], "title": f["title"], "release_year": str(f["year"]), "imdb_id": f["imdb_id"], "cast": "", "testo": "x"} for f in batch]
        t = time.time()
        res = orch._enrich("rag_search", {"query": "q", "chunks": chunks, "metadata": {}, "trace": [], "turn_id": f"t{len(rows)}"})
        sec = round(time.time() - t, 2)
        enr = res["metadata"]["tmdb_enrichment"]
        calls = [s for s in res["trace"] if s["kind"] == "tmdb_calls"][0]["data"]
        items = calls["items"]
        rows.append({"films": len(batch), "matched": sum(c["status"] == "matched" for c in enr["candidates"]), "cards": len(items),
                     "with_poster": sum(1 for i in items if i.get("poster_path")), "http_calls": len(calls["calls"]), "seconds": sec,
                     "title_searches": sum(1 for c in calls["calls"] if "/search/" in c["url"]), "writes": sum(1 for c in calls["calls"] if c["method"] != "GET")})
    chunks = [{"id": f["film_id"], "title": f["title"], "release_year": str(f["year"]), "imdb_id": None, "testo": "x"} for f in without]
    res = orch._enrich("rag_search", {"query": "q", "chunks": chunks, "metadata": {}, "trace": [], "turn_id": "tx"})
    skipped = [c["status"] for c in res["metadata"]["tmdb_enrichment"]["candidates"]]
    tot = lambda k: sum(r[k] for r in rows)
    lines = ["# Arricchimento TMDb per IMDb ID (prova live, nessuna chiamata a OpenAI)", "",
             f"30 film campionati a caso dal catalogo v3 con IMDb ID, in 6 gruppi da 5 (come i `k_finale` di un turno).", "",
             f"- Film trovati su TMDb per IMDb ID: {tot('matched')}/30; locandine: {tot('with_poster')}/{tot('cards')} schede.",
             f"- Chiamate HTTP: {tot('http_calls')} in tutto, {tot('http_calls') / 6:.1f} per gruppo di 5 (una `/find` per film più la lista dei generi); ricerche per titolo: {tot('title_searches')}; chiamate non GET: {tot('writes')}.",
             f"- Tempo per gruppo: media {sum(r['seconds'] for r in rows) / 6:.1f} s.",
             f"- Film senza IMDb ID (3): stato {skipped}; nessuna ricerca per titolo.", ""]
    (ROOT / "eval/results/TMDB_ENRICH_LIVE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
