"""Writes `reports/series_data_map.md` from the REAL data: the five record types of `data/s5`, the payload of the Qdrant collection, keys and
measured cardinalities. Read-only (files and Qdrant), no API.   python -m pipelines.wikipedia_series.schema_map"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

from qdrant_client import QdrantClient

from . import index as I
from .build_relations import read
from .common import DATA_DIR

OUT = Path(__file__).parent / "reports" / "series_data_map.md"


def types_of(path) -> tuple[int, dict[str, Counter]]:
    ty, n = defaultdict(Counter), 0
    for r in read(path):
        n += 1
        for k, v in r.items():
            ty[k][type(v).__name__ if v is not None else "null"] += 1
    return n, ty


def main() -> int:
    s5, lines = DATA_DIR / "s5", ["# Mappa dei dati delle serie TV (generata dai dati reali)\n",
                                  "Generata da `python -m pipelines.wikipedia_series.schema_map`. Nessuna base SQL: i record sono file JSONL (`data/s5`) e punti Qdrant "
                                  "(`wikipedia_series_it_v1`, un punto per unità embeddata, id = uuid5(namespace, `record_id`)).\n"]
    ids = {}
    for name in ("series", "seasons", "episodes", "tv_movies"):
        n, ty = types_of(s5 / f"{name}.jsonl")
        ids[name] = {r["record_id"]: r for r in read(s5 / f"{name}.jsonl")}
        lines += [f"\n## `{name}.jsonl` — {n} record\n", "| campo | tipi osservati (conteggio) |", "|---|---|"]
        lines += [f"| `{k}` | {', '.join(f'{t} {c}' for t, c in v.most_common())} |" for k, v in sorted(ty.items())]
    series, seasons, episodes, movies = (ids[k] for k in ("series", "seasons", "episodes", "tv_movies"))
    per_series_seasons = Counter(s["series_id"] for s in seasons.values() if s.get("series_id"))
    per_series_eps = Counter(e["series_id"] for e in episodes.values() if e.get("series_id"))
    per_season_eps = Counter(e["season_id"] for e in episodes.values() if e.get("season_id"))
    uncertain = {r["record_id"] for r in read(s5 / "uncertain.jsonl")}
    known = set(series) | uncertain          # a parent may be an `uncertain` programme: kept as a record, never embedded
    in_unc = {"seasons": sum(1 for s in seasons.values() if s.get("series_id") in uncertain),
              "episodes": sum(1 for e in episodes.values() if e.get("series_id") in uncertain)}
    broken = {"seasons->series": sum(1 for s in seasons.values() if s.get("series_id") and s["series_id"] not in known),
              "episodes->series": sum(1 for e in episodes.values() if e.get("series_id") and e["series_id"] not in known),
              "episodes->season": sum(1 for e in episodes.values() if e.get("season_id") and e["season_id"] not in seasons)}
    lines += ["\n## Chiavi e relazioni (misurate)\n", "| relazione | chiave | cardinalità | verifica |", "|---|---|---|---|",
              f"| `series` PK | `record_id` (`wp-<pageid>`) | — | {len(series)} id unici |",
              f"| `season` → `series` | `seasons.series_id` → `series.record_id` | N:1 (0..1: {sum(1 for s in seasons.values() if not s.get('series_id'))} orfane) | max {max(per_series_seasons.values())} stagioni per serie; riferimenti rotti {broken['seasons->series']}; {in_unc['seasons']} con padre in `uncertain` (record senza vettore) |",
              f"| `episode` → `series` | `episodes.series_id` → `series.record_id` | N:1 (0..1: {sum(1 for e in episodes.values() if not e.get('series_id'))} senza serie) | max {max(per_series_eps.values())} episodi per serie; rotti {broken['episodes->series']}; {in_unc['episodes']} con padre in `uncertain` |",
              f"| `episode` → `season` | `episodes.season_id` → `seasons.record_id` | N:1 (0..1: {sum(1 for e in episodes.values() if not e.get('season_id'))} senza stagione-pagina) | max {max(per_season_eps.values())} episodi per stagione; rotti {broken['episodes->season']} |",
              f"| `tv_movie` | `record_id` | nessuna relazione con serie/stagioni (`series_id`/`season_id` nulli: {sum(1 for m in movies.values() if not m.get('series_id') and not m.get('season_id'))}/{len(movies)}) | autonomo |",
              "| stagione logica | `seasons.logical = true` | nodo senza testo né vettore | non presente in Qdrant |\n"]
    c = QdrantClient(url=I.URL, timeout=60)
    info = c.get_collection(I.COLLECTION)
    sample = c.scroll(I.COLLECTION, limit=1, with_payload=True)[0][0].payload
    lines += [f"\n## Collezione Qdrant `{I.COLLECTION}`\n", f"- punti {c.count(I.COLLECTION, exact=True).count}, vettore {info.config.params.vectors.size} × {info.config.params.vectors.distance}, stato {info.status}",
              "- indici di payload: " + ", ".join(f"`{k}` ({v.data_type})" for k, v in sorted(info.payload_schema.items())),
              "- campi aggiunti al record: `unit_id`, `embedded_text_kind`, `title_norm`, `original_title_norm`, `title_base_norm`, `series_title_norm`, `genres_norm`, `imdb_id`, `network_norm`, `text_embedded_prefix` (solo episodi)",
              "- esempio di chiavi del payload di un punto: " + ", ".join(f"`{k}`" for k in sorted(sample))]
    OUT.write_text("\n".join(lines) + "\n")
    print(f"written {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
