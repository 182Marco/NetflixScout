"""The registry of sources written to the `source` table, with hashes computed from the real input files."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
FILM_SNAPSHOT = ROOT / "pipelines/wikipedia_films/data/cache/wikidata/itwiki-20261101-a"
SERIES_SNAPSHOT = ROOT / "pipelines/wikipedia_series/data/cache/wikidata/itwiki-20261101-series-a"
FILM_CATALOG = ROOT / "pipelines/wikipedia_films/data/clean_v3/films.v3.jsonl"
SERIES_DIR = ROOT / "pipelines/wikipedia_series/data/s5"
DEFAULT_DB = ROOT / "cinema_db/data/cinema.sqlite3"
PHASE4_SNAPSHOT = ROOT / "cinema_db/data/wikidata_phase4"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class SourceSpec:
    key: str
    name: str
    kind: str
    url: str | None
    license: str
    license_url: str | None
    usage_scope: str
    attribution_required: int
    attribution_text: str | None
    terms_note: str
    snapshot_label: str | None
    snapshot_sha256: str | None
    retrieved_at: str | None

    def row(self, source_id: int) -> tuple:
        return (source_id, self.name, self.kind, self.url, self.license, self.license_url, self.usage_scope, self.attribution_required,
                self.attribution_text, self.terms_note, self.snapshot_label, self.snapshot_sha256, self.retrieved_at)


def manifest_hash(directory: Path) -> str:
    manifest = directory / "manifest.json"
    return sha256_file(manifest) if manifest.is_file() else ""


def build_sources(film_index_sha: str, film_acquired: str, series_rag_sha: str, series_acquired: str,
                  phase4: tuple[str, str] | None = None) -> list[SourceSpec]:
    cc0 = ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/")
    sa = ("CC BY-SA 4.0", "https://creativecommons.org/licenses/by-sa/4.0/")
    specs = [
        SourceSpec("wd_film", "wikidata-film-snapshot", "wikidata", "https://www.wikidata.org", *cc0, "open_public_domain", 0, None,
                   "Original API responses downloaded by the film project (pipelines/wikipedia_films), read from the local snapshot; Wikidata structured data is CC0.",
                   "itwiki-20261101-a", film_index_sha, film_acquired),
        SourceSpec("wd_series", "wikidata-series-snapshot", "wikidata", "https://www.wikidata.org", *cc0, "open_public_domain", 0, None,
                   "Original API responses downloaded by the series project (pipelines/wikipedia_series), read from the local snapshot; Wikidata structured data is CC0.",
                   "itwiki-20261101-series-a", series_rag_sha, series_acquired),
        SourceSpec("cat_film", "film-catalog-v3", "derived", "https://it.wikipedia.org", *sa, "open_share_alike", 1, "Contains data from the Italian Wikipedia (CC BY-SA 4.0) and Wikidata (CC0).",
                   "Clean film catalogue built by pipelines/wikipedia_films from the it.wikipedia dump 20261101 (SHA-1 recorded in that project) and Wikidata; only facts are imported here, not the plot text.",
                   "films.v3.jsonl", sha256_file(FILM_CATALOG), None),
        SourceSpec("cat_series", "series-catalog-s5", "derived", "https://it.wikipedia.org", *sa, "open_share_alike", 1, "Contains data from the Italian Wikipedia (CC BY-SA 4.0) and Wikidata (CC0).",
                   "Clean series catalogue built by pipelines/wikipedia_series from the it.wikipedia dump 20261101 and Wikidata; only facts are imported here, not the plot text.",
                   "data/s5", manifest_hash(SERIES_DIR), None),
        SourceSpec("vocab", "cinema-db-genre-vocabulary", "manual", None, "Authored for this database", None, "unverified", 0, None,
                   "Canonical genre vocabulary and mapping rules written for this project (cinema_db/harness/build/genres.py); the licence of this authored work is for the owner to decide.",
                   None, None, None),
    ]
    if phase4:  # appended LAST so that a build without it keeps every source id (and the digest) it had
        specs.append(SourceSpec(
            "wd_p4", "wikidata-phase4-targeted", "wikidata", "https://www.wikidata.org", *cc0, "open_public_domain", 0, None,
            "Targeted requests to the public Wikidata endpoints (labels and life dates of people, award, ceremony, country, language, currency and company items), "
            "stored byte for byte in cinema_db/data/wikidata_phase4 and read from there; Wikidata structured data is CC0.",
            "wikidata_phase4", phase4[0], phase4[1]))
    return specs
