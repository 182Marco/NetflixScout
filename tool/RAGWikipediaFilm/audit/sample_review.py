"""Phase 5: stratified sample of the film records whose classification confidence is not 'high'.

Deterministic (fixed seed, sorted ids). The sample is only a way to look at records; the reading verdicts live in
`sample_verdicts.py` and nothing here changes the catalogue."""
from __future__ import annotations

import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261104
# strata: subtype group -> sample size (None = every record)
SIZES = {"tv_film": 60, "feature": 40, "animated": 30}


def load() -> tuple[dict, dict]:
    cl = {}
    for line in (ROOT / "data/audit/classification.jsonl").open():
        r = json.loads(line)
        cl[r["film_id"]] = r
    films = {}
    for line in (ROOT / "data/processed/films.jsonl").open():
        f = json.loads(line)
        films[f["film_id"]] = f
    return cl, films


def population(cl: dict) -> list[dict]:
    return sorted((r for r in cl.values() if r["verdict"] == "film" and r["confidence"] != "high"),
                  key=lambda r: r["film_id"])


def draw(cl: dict) -> dict[str, list[dict]]:
    strata: dict[str, list[dict]] = {}
    for r in population(cl):
        strata.setdefault(r["subtype"] if r["subtype"] in SIZES else "other", []).append(r)
    rng = random.Random(SEED)
    out = {}
    for name in sorted(strata):
        rows = strata[name]
        n = SIZES.get(name)
        out[name] = sorted(rng.sample(rows, n), key=lambda r: r["film_id"]) if n and n < len(rows) else rows
    return out


def show(stratum: str, start: int, end: int, chars: int = 190) -> None:
    cl, films = load()
    for r in draw(cl)[stratum][start:end]:
        f = films[r["film_id"]]
        print(f'{r["film_id"]}|{f["title"]}|{f["year"]}|{f.get("duration_minutes")}|{r["subtype"]}|{"IB" if r["infobox_film"] else "cat"}'
              f'|{len(f["synopsis"])}|{f["synopsis"][:chars]!r}')


if __name__ == "__main__":
    import sys
    show(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))
