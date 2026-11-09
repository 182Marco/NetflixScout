"""Metadata enrichment: infobox (fallback) + Wikidata (from the snapshot of original responses).

`derive_record` and the helpers are pure: same candidate + same Wikidata JSON = same record.
Nothing is invented: unknown single values are null, unknown collections are empty lists.
"""
from __future__ import annotations

import json
import logging
import re
import urllib.parse
from pathlib import Path
from typing import Any, Iterable

from pydantic import ValidationError

from .clean_plot import clean_wikitext
from .config import PipelineConfig
from .schema import IMDB_RE, MAX_DURATION, MAX_YEAR, MIN_DURATION, MIN_YEAR, QID_RE, FilmRecord, dumps_record
from .wikidata_client import Snapshot, WikidataClient, WikidataError

log = logging.getLogger("ragwiki.enrich")

# Bump when the derivation of a record from the same inputs changes: checkpoints of an older
# derivation are ignored, so a file is never made of batches derived by different code.
DERIVATION_VERSION = 2

P_DIRECTOR, P_CAST, P_GENRE, P_COUNTRY = "P57", "P161", "P136", "P495"
P_LANGUAGE, P_LANGUAGE_WORK, P_DATE, P_DURATION = "P364", "P407", "P577", "P2047"
P_IMDB, P_TITLE, P_ROLE, P_CHARACTER_NAME = "P345", "P1476", "P453", "P4633"
UNITS_TO_MINUTES = {"Q7727": 1.0, "Q11574": 1 / 60, "Q25235": 60.0}
YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


# ---------------------------------------------------------------- Wikidata JSON helpers (pure)
def _statements(entity: dict, prop: str) -> list[dict]:
    """Statements of a property: preferred rank if present, else normal; deprecated never."""
    claims = entity.get("claims", {}).get(prop, [])
    live = [c for c in claims if c.get("rank") != "deprecated" and c.get("mainsnak", {}).get("snaktype") == "value"]
    preferred = [c for c in live if c.get("rank") == "preferred"]
    return preferred or live


def _item_id(snak: dict) -> str | None:
    value = snak.get("datavalue", {}).get("value")
    qid = value.get("id") if isinstance(value, dict) else None
    return qid if isinstance(qid, str) and QID_RE.match(qid) else None


def item_ids(entity: dict, prop: str) -> list[str]:
    return [q for c in _statements(entity, prop) if (q := _item_id(c["mainsnak"]))]


def referenced_qids(entity: dict) -> set[str]:
    """Every item whose label the record needs (people, genres, countries, languages, roles)."""
    out: set[str] = set()
    for prop in (P_DIRECTOR, P_CAST, P_GENRE, P_COUNTRY, P_LANGUAGE, P_LANGUAGE_WORK):
        out.update(item_ids(entity, prop))
    for statement in _statements(entity, P_CAST):
        for snak in statement.get("qualifiers", {}).get(P_ROLE, []):
            if (qid := _item_id(snak)):
                out.add(qid)
    return out


def label_of(entity: dict | None, languages: list[str]) -> str | None:
    if not entity:
        return None
    labels = entity.get("labels", {})
    for language in languages:
        value = labels.get(language, {}).get("value")
        if value:
            return str(value)
    return None


def year_from_wikidata(entity: dict) -> int | None:
    years = []
    for statement in _statements(entity, P_DATE):
        value = statement["mainsnak"].get("datavalue", {}).get("value", {})
        match = re.match(r"^[+-](\d{4,})-", str(value.get("time", "")))
        # Wikidata holds placeholder dates (e.g. +0001-00-00): a plausible release year or nothing
        if match and int(value.get("precision", 0)) >= 9 and MIN_YEAR <= int(match.group(1)) <= MAX_YEAR:
            years.append(int(match.group(1)))
    return min(years) if years else None


def duration_from_wikidata(entity: dict) -> int | None:
    for statement in _statements(entity, P_DURATION):
        value = statement["mainsnak"].get("datavalue", {}).get("value", {})
        unit = str(value.get("unit", "")).rsplit("/", 1)[-1]
        factor = UNITS_TO_MINUTES.get(unit)
        try:
            amount = float(value.get("amount"))
        except (TypeError, ValueError):
            continue
        if factor and amount > 0:
            minutes = round(amount * factor)
            if MIN_DURATION <= minutes <= MAX_DURATION:
                return minutes
    return None


def string_claim(entity: dict, prop: str) -> str | None:
    for statement in _statements(entity, prop):
        value = statement["mainsnak"].get("datavalue", {}).get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def original_title_from_wikidata(entity: dict) -> str | None:
    for statement in _statements(entity, P_TITLE):
        value = statement["mainsnak"].get("datavalue", {}).get("value", {})
        if isinstance(value, dict) and str(value.get("text", "")).strip():
            return str(value["text"]).strip()
    return None


# ---------------------------------------------------------------- infobox fallback (pure)
def _param(infobox: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = infobox.get(name)
        if value and value.strip():
            return value
    return None


def _split_names(wikitext: str) -> list[str]:
    plain = clean_wikitext(wikitext)
    return [part.strip() for part in re.split(r"[,;\n/]+", plain) if part.strip()]


def infobox_year(infobox: dict[str, str]) -> int | None:
    raw = _param(infobox, "anno uscita", "anno", "annouscita", "anno produzione", "annoproduzione")
    match = YEAR_RE.search(clean_wikitext(raw)) if raw else None
    return int(match.group(1)) if match else None


def infobox_duration(infobox: dict[str, str]) -> int | None:
    raw = _param(infobox, "durata")
    # raw value: durations often sit inside templates ({{Lista|100 min|...}}) that cleaning drops
    match = re.search(r"\b(\d{1,4})\s*(?:min|minuti|')", raw) if raw else None
    return int(match.group(1)) if match and int(match.group(1)) > 0 else None


def infobox_actors(infobox: dict[str, str], limit: int) -> list[dict]:
    raw = _param(infobox, "attori")
    if not raw:
        return []
    actors = []
    for line in raw.splitlines():
        if not line.lstrip().startswith("*"):
            continue
        text = clean_wikitext(line)
        name, _, character = text.partition(":")
        if name.strip():
            actors.append({"name": name.strip(), "wikidata_id": None, "character": character.strip() or None})
    return actors[:limit]


def infobox_list(infobox: dict[str, str], base: str) -> list[str]:
    values: list[str] = []
    for key in sorted(infobox, key=lambda k: (len(k), k)):
        if key == base or re.fullmatch(rf"{re.escape(base)} \d+", key):
            values.extend(_split_names(infobox[key]))
    return list(dict.fromkeys(values))


# ---------------------------------------------------------------- record derivation (pure)
def derive_record(
    candidate: dict,
    entity: dict | None,
    entities: dict[str, dict],
    *,
    config: PipelineConfig,
) -> dict[str, Any]:
    """Build the record dict (not yet validated). `entities` maps QID -> label-bearing entity."""
    languages = config.wikidata.languages
    infobox = candidate.get("infobox", {})
    entity = entity or {}
    qid = entity.get("id") if QID_RE.match(str(entity.get("id", ""))) else None

    def names(ids: Iterable[str]) -> list[str]:
        found = (label_of(entities.get(i), languages) for i in ids)
        return list(dict.fromkeys(n for n in found if n))

    directors = [
        {"name": n, "wikidata_id": i}
        for i in item_ids(entity, P_DIRECTOR)
        if (n := label_of(entities.get(i), languages))
    ]
    if not directors:
        directors = [{"name": n, "wikidata_id": None} for n in _split_names(infobox.get("regista", ""))]

    actors: list[dict] = []
    for statement in _statements(entity, P_CAST):
        actor_id = _item_id(statement["mainsnak"])
        name = label_of(entities.get(actor_id or ""), languages)
        if not name:
            continue
        character = None
        for snak in statement.get("qualifiers", {}).get(P_ROLE, []):
            character = label_of(entities.get(_item_id(snak) or ""), languages)
            if character:
                break
        if character is None:
            for snak in statement.get("qualifiers", {}).get(P_CHARACTER_NAME, []):
                value = snak.get("datavalue", {}).get("value")
                if isinstance(value, str) and value.strip():
                    character = value.strip()
                    break
        actors.append({"name": name, "wikidata_id": actor_id, "character": character})
    if not actors:
        actors = infobox_actors(infobox, config.wikidata.max_actors)

    imdb = string_claim(entity, P_IMDB)
    page_id = int(candidate["page_id"])
    title = candidate["title"]
    return {
        "film_id": qid or f"wp-{page_id}",
        "wikidata_id": qid,
        "wikipedia_page_id": page_id,
        "title": title,
        "original_title": original_title_from_wikidata(entity)
        or (clean_wikitext(infobox["titolo originale"]) or None if infobox.get("titolo originale") else None),
        "year": year_from_wikidata(entity) or infobox_year(infobox),
        "director": directors,
        "duration_minutes": duration_from_wikidata(entity) or infobox_duration(infobox),
        "actors": actors[: config.wikidata.max_actors],
        "genres": names(item_ids(entity, P_GENRE)) or infobox_list(infobox, "genere"),
        "country": names(item_ids(entity, P_COUNTRY)) or infobox_list(infobox, "paese"),
        "language": names(item_ids(entity, P_LANGUAGE) or item_ids(entity, P_LANGUAGE_WORK))
        or infobox_list(infobox, "lingua originale"),
        "synopsis": candidate["plot"],
        "imdb_id": imdb if imdb and IMDB_RE.match(imdb) else None,
        "wikipedia_url": "https://it.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"), safe="_(),!:'"),
        "source_revision_id": str(candidate["revision_id"]),
        "retrieved_at": config.dump_timestamp,
    }


# ---------------------------------------------------------------- Wikidata requests
def entities_for_titles(client: WikidataClient, titles: list[str]) -> dict[str, dict]:
    """itwiki title -> Wikidata entity (claims + labels), from ONE request for the whole batch."""
    cfg = client.cfg
    payload = client.get_json(
        {
            "action": "wbgetentities",
            "sites": cfg.site,
            "titles": "|".join(titles),
            "props": "claims|labels|sitelinks",
            "sitefilter": cfg.site,
            "languages": "|".join(cfg.languages),
        }
    )
    found: dict[str, dict] = {}
    for entity in payload.get("entities", {}).values():
        if "missing" in entity:
            continue
        title = entity.get("sitelinks", {}).get(cfg.site, {}).get("title")
        if title:
            found[title] = entity
    return found


LANG_RE = re.compile(r"^[a-z]{2,3}(-[a-z0-9]+)?$")


def label_query(ids: list[str], languages: list[str]) -> str:
    """SPARQL for the labels of given items. Only validated QIDs and language codes are interpolated."""
    if not all(QID_RE.match(i) for i in ids) or not all(LANG_RE.match(l) for l in languages):
        raise ValueError("refusing to build a query from an invalid id or language code")
    values = " ".join(f"wd:{i}" for i in ids)
    langs = ", ".join(f'"{l}"' for l in languages)
    return (
        f"SELECT ?item ?lang ?label WHERE {{ VALUES ?item {{ {values} }} "
        f"?item rdfs:label ?label . BIND(LANG(?label) AS ?lang) FILTER(?lang IN ({langs})) }}"
    )


def labels_for_ids(client: WikidataClient, ids: Iterable[str]) -> dict[str, dict]:
    """QID -> {"id", "labels": {lang: {"value"}}}, from SPARQL responses (kept in the snapshot)."""
    cfg = client.cfg
    ordered = sorted(set(ids))
    out: dict[str, dict] = {}

    def fetch(chunk: list[str]) -> None:
        try:
            payload = client.sparql_json(label_query(chunk, cfg.languages))
        except WikidataError:
            if len(chunk) <= 50:  # a small batch that fails is a real failure
                raise
            middle = len(chunk) // 2  # the Query Service has a time limit: retry in halves
            fetch(chunk[:middle])
            fetch(chunk[middle:])
            return
        for row in payload["results"]["bindings"]:
            qid = row["item"]["value"].rsplit("/", 1)[-1]
            entity = out.setdefault(qid, {"id": qid, "labels": {}})
            entity["labels"][row["lang"]["value"]] = {"language": row["lang"]["value"], "value": row["label"]["value"]}

    for start in range(0, len(ordered), cfg.label_batch_size):
        fetch(ordered[start : start + cfg.label_batch_size])
    return out


# ---------------------------------------------------------------- batch driver
def _input_fingerprint(path: Path, limit: int | None) -> str:
    """Identity of the enrich input: candidates content + limit. A checkpoint is valid only for it."""
    import hashlib

    digest = hashlib.sha256(f"derivation={DERIVATION_VERSION}\nlimit={limit}\n".encode())
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def _candidate_offsets(path: Path) -> list[tuple[int, int]]:
    offsets: list[tuple[int, int]] = []
    with path.open("rb") as handle:
        position = 0
        for line in handle:
            if line.strip():
                offsets.append((json.loads(line)["page_id"], position))
            position += len(line)
    offsets.sort()
    return offsets


def _read_candidate(handle, offset: int) -> dict:
    handle.seek(offset)
    return json.loads(handle.readline())


def run_enrich(config: PipelineConfig, client: WikidataClient | None = None, *, limit: int | None = None) -> dict:
    out_dir = config.processed_dir
    cand_path = out_dir / config.output.candidates_file
    films_path = out_dir / config.output.films_file
    part_path = films_path.with_suffix(films_path.suffix + ".part")
    reject_path = out_dir / "rejected_records.jsonl"
    ckpt_path = out_dir / "enrich_checkpoint.json"
    if not cand_path.exists():
        raise FileNotFoundError(f"{cand_path} not found: run the extract phase first")

    if client is None:
        client = WikidataClient(config.wikidata, Snapshot(config.snapshot_dir))
    offsets = _candidate_offsets(cand_path)
    if limit is not None:
        offsets = offsets[:limit]
    size = config.wikidata.batch_size
    batches = [offsets[i : i + size] for i in range(0, len(offsets), size)]

    fingerprint = _input_fingerprint(cand_path, limit)
    done, written, rejected = 0, 0, 0
    if ckpt_path.exists() and part_path.exists():
        ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
        if (
            ckpt.get("snapshot_id") == config.wikidata.snapshot_id
            and ckpt.get("batch_size") == size
            and ckpt.get("input") == fingerprint
        ):
            done, written, rejected = ckpt["batches_done"], ckpt["written"], ckpt["rejected"]
            with part_path.open("r+b") as handle:
                handle.truncate(ckpt["films_bytes"])
            with reject_path.open("r+b") as handle:
                handle.truncate(ckpt["rejected_bytes"])
            log.info("resuming after %d batches", done)
    if done == 0:
        part_path.write_bytes(b"")
        reject_path.write_bytes(b"")

    with cand_path.open("rb") as candidates, part_path.open("ab") as films, reject_path.open("ab") as rejects:
        for number in range(done, len(batches)):
            records = [_read_candidate(candidates, off) for _, off in batches[number]]
            wd = entities_for_titles(client, [r["title"] for r in records])
            needed: set[str] = set()
            for entity in wd.values():
                needed |= referenced_qids(entity)
            labels = labels_for_ids(client, needed) if needed else {}
            for record in records:
                derived = derive_record(record, wd.get(record["title"]), labels, config=config)
                try:
                    films.write((dumps_record(FilmRecord.model_validate(derived)) + "\n").encode("utf-8"))
                    written += 1
                except ValidationError as error:
                    rejected += 1
                    problem = {
                        "page_id": record["page_id"],
                        "title": record["title"],
                        "reason": "schema_validation",
                        "errors": [f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors()],
                    }
                    rejects.write((json.dumps(problem, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
            films.flush()
            rejects.flush()
            ckpt_path.write_text(
                json.dumps(
                    {
                        "snapshot_id": config.wikidata.snapshot_id,
                        "batch_size": size,
                        "input": fingerprint,
                        "batches_done": number + 1,
                        "written": written,
                        "rejected": rejected,
                        "films_bytes": films.tell(),
                        "rejected_bytes": rejects.tell(),
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            log.info("batch %d/%d: films=%d rejected=%d", number + 1, len(batches), written, rejected)
    part_path.replace(films_path)
    ckpt_path.unlink(missing_ok=True)
    return {
        "films": written,
        "rejected": rejected,
        "snapshot_hits": client.snapshot_hits,
        "network_requests": client.network_requests,
    }
