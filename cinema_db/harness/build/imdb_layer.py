"""Phase-9 layer: builds `cinema.v3.sqlite3` from a COPY of the v2 database plus the IMDb archive, MovieLens aggregates and local catalogues.

    python -m cinema_db.harness.build.imdb_layer --out cinema_db/data/cinema.v3.sqlite3

What it does, in this order (all deterministic, offline; the runtime database is only READ, never changed):
 1. copies the base file and adds the v3 tables (`cinema_db/schema_v3.py`) and the two new `source` rows;
 2. recovers identifiers of works the build imported without them (`ids_reliable = false`) ONLY when IMDb confirms title, year and kind;
 3. attaches IMDb person ids (strong matches only; weak, conflicting and shared ones are recorded as candidates, never attached);
 4. applies the source priority decided by the owner for type, year and runtime (IMDb first; the losing value is kept in `entity_claim`);
 5. adds IMDb and MovieLens ratings, each with its own source, scale, votes and date;
 6. matches existing episodes to IMDb episodes (strong evidence only) and attaches their ids;
 7. adds NEW works (MovieLens feature films, shorts and TV films; Italian film pages without a plot; recovered mixed-media pages) with their
    credits, never creating a second work for an existing one and never merging people by name;
 8. fills `work_status`, rebuilds the FTS index, runs every integrity check and records the inputs in `build_info`.
Reconciliation (owner decisions of 2026-11-08, see `reconcile_rules.py`): the PRIMARY id of a work with several IMDb ids is chosen by rule and only
it feeds type/year/runtime/ratings (the others are kept in `entity_claim`); 12 safe person merges are a reversible map (`entity_canonical`);
ids claimed by several persons go to the one whose birth year matches; titles held for "same title and year" are released when proven distinct;
IMDb episodes of series that already have episodes are imported; credits of IMDb people that are only a candidate of an existing person are kept
through a NEW person with the candidate recorded (never merged).
Works and people that do not qualify go to separate JSONL archives next to the output (with the reason), not into the catalogue.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cinema_db import schema as S2
from cinema_db import schema_v3 as V3
from cinema_db.harness.audit import imdb_load as L
from cinema_db.harness.audit import imdb_sections as AS
from cinema_db.harness.audit import reconcile as RC
from cinema_db.harness.audit import util
from cinema_db.harness.audit.sections import Context
from cinema_db.harness.build import genres as G
from cinema_db.harness.build import movielens_layer as ML
from cinema_db.harness.build import reconcile_rules as RR
from cinema_db.harness.build import title_keys as TK
from cinema_db.harness.build import id_rules
from cinema_db.harness.build.build import content_digest, invariants
from cinema_db.harness.build.common import normalize_name

ROOT = util.ROOT
BUILDER = "cinema_db.harness.build.imdb_layer/2"
BUILDER_ML = "cinema_db.harness.build.imdb_layer/3+movielens"
ENTRY_TYPES = ("movie", "short", "tvShort", "tvMovie", "tvSpecial")
TYPE_TO_KIND = {"movie": "film", "short": "short", "tvShort": "short", "tvMovie": "tv_film", "tvSpecial": "tv_film", "tvSeries": "series", "tvMiniSeries": "miniseries"}
CHANGEABLE_KINDS = ("film", "short", "tv_film", "series", "miniseries")
TV_TYPES = ("tvSeries", "tvMiniSeries", "tvMovie", "tvSpecial")
CATEGORY_ROLE = {"actor": "cast", "actress": "cast", "self": "cast", "archive_footage": "cast", "archive_sound": "cast", "director": "director",
                 "writer": "writer", "producer": "producer", "composer": "composer", "cinematographer": "cinematographer", "editor": "editor",
                 "production_designer": "production_designer"}


@dataclass
class LayerInputs:
    base: Path = util.CINEMA_DB
    staging: Path = ROOT / "cinema_db/data/audit_a1/imdb_staging.sqlite3"
    movielens: Path = util.MOVIELENS_DB
    s5_dir: Path = util.S5
    audit_dir: Path = util.OUT_DIR  # holds dump_scan.jsonl
    imdb_manifest: Path = ROOT / "cinema_db/data/imdb_snapshot/2026-11-08/manifest.json"
    id_overrides: Path = id_rules.OVERRIDES_PATH  # verified corrections of identifiers that break the shape of their scheme (id_rules.py)
    movielens_layer: bool = False  # True = schema 4: every MovieLens film, genre and tag (`movielens_layer.py`); False = the schema-3 file, byte for byte as before
    memo: dict[str, Any] = field(default_factory=dict)  # tests pre-seed archives that would otherwise be read from the real project


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Layer:
    def __init__(self, inputs: LayerInputs, out_tmp: Path, sep_dir: Path) -> None:
        self.inp = inputs
        self.sep_dir = sep_dir
        self.counts: collections.Counter[str] = collections.Counter()
        self.separate: dict[str, list[dict]] = collections.defaultdict(list)
        shutil.copyfile(inputs.base, out_tmp)
        self.db = sqlite3.connect(out_tmp)
        self.db.execute("PRAGMA foreign_keys = OFF")
        self.db.execute("PRAGMA journal_mode = OFF")
        self.db.execute("PRAGMA synchronous = OFF")
        self.st = sqlite3.connect(f"file:{inputs.staging}?mode=ro", uri=True)
        self.ctx = Context(inputs.audit_dir, cinema=inputs.base, movielens=inputs.movielens)
        self.ctx._memo.update(inputs.memo)
        self.manifest = json.loads(inputs.imdb_manifest.read_text(encoding="utf-8"))["datasets"]
        self.today = max(e["retrieved_at"] for e in self.manifest.values())[:10]
        self.next_entity = self.db.execute("SELECT COALESCE(MAX(entity_id), 0) + 1 FROM entity").fetchone()[0]
        self.imdb_work: dict[str, int] = {}
        self.primary_tconst: dict[int, str] = {}  # work -> its primary IMDb title id (the only one that feeds type/year/runtime/ratings)
        self.imdb_alias: dict[str, int] = {}  # secondary IMDb title ids -> work (kept as non-primary ids and in entity_claim)
        self.merges: list[tuple[int, int, str, str]] = []  # (survivor, merged, nconst, evidence)
        self.cand_of_nconst: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)  # nconst -> [(existing person, candidate tier)]
        self.slots_taken: set[tuple] = set()
        self._guard_works: dict[str, list[int]] = {}
        self.used_ids: set[tuple[str, str]] = set()
        self.name_seen: set[tuple] = set()
        self.credit_seen: set[tuple] = set()

    # ---------------------------------------------------------------------------------------------- helpers
    def new_entity(self, kind: str) -> int:
        eid = self.next_entity
        self.next_entity += 1
        self.db.execute("INSERT INTO entity VALUES (?,?)", (eid, kind))
        return eid

    def add_name(self, eid: int, name: str, kind: str, language: str | None, ref: str | None, primary: bool = False) -> None:
        name = " ".join(str(name).split())
        norm = normalize_name(name)
        key = (eid, norm, language or "", kind)
        if not name or not norm or key in self.name_seen:
            return
        self.name_seen.add(key)
        self.db.execute("INSERT INTO entity_name (entity_id, name, name_norm, language, kind, is_primary, source_id, source_ref) VALUES (?,?,?,?,?,?,?,?)",
                        (eid, name, norm, language, kind, 1 if primary else 0, self.src_imdb, ref))

    def add_external(self, eid: int, scheme: str, value: str, ref: str | None, source: int | None = None, primary: bool = True) -> bool:
        key = (scheme, value)
        if key in self.used_ids:
            self.counts[f"id_already_used:{scheme}"] += 1
            return False
        self.used_ids.add(key)
        if primary and self.db.execute("SELECT 1 FROM external_id WHERE entity_id = ? AND scheme = ? AND is_primary = 1", (eid, scheme)).fetchone():
            primary = False  # the schema allows one preferred value per scheme: a second one is kept as an alias
            self.counts[f"id_added_as_alias:{scheme}"] += 1
        self.db.execute("INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id, source_ref) VALUES (?,?,?,?,?,?)",
                        (eid, scheme, value, 1 if primary else 0, source or self.src_imdb, ref))
        return True

    def candidate(self, eid: int, scheme: str, value: str, tier: str, evidence: str) -> None:
        self.db.execute("INSERT OR IGNORE INTO external_id_candidate VALUES (?,?,?,?,?,?)", (eid, scheme, value, tier, evidence, self.src_imdb))
        self.counts[f"candidate:{tier}"] += 1

    def claim(self, eid: int, fld: str, value: Any, source: int, ref: str | None) -> None:
        self.db.execute("INSERT OR IGNORE INTO entity_claim VALUES (?,?,?,?,?,?)", (eid, fld, str(value), source, ref, None))
        self.counts[f"claim:{fld}"] += 1

    def provenance(self, eid: int, fld: str, ref: str | None) -> None:
        self.db.execute("INSERT OR REPLACE INTO field_provenance VALUES (?,?,?,?,?)", (eid, fld, self.src_imdb, ref, self.today))

    # ------------------------------------------------------------------------------------------------ setup
    def setup(self) -> None:
        for ddl in V3.TABLES_V3 + V3.INDEXES_V3:
            self.db.execute(ddl)
        m = self.manifest
        digest = hashlib.sha256("".join(f"{k}:{m[k]['sha256']}" for k in sorted(m)).encode()).hexdigest()
        c = self.db.execute
        c("INSERT INTO source (name, kind, url, license, license_url, usage_scope, attribution_required, attribution_text, terms_note, snapshot_label, snapshot_sha256, retrieved_at)"
          " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("imdb-datasets", "imdb", "https://datasets.imdbws.com/", "IMDb non-commercial datasets", "https://developer.imdb.com/non-commercial-datasets/",
                                                 "non_commercial", 1, "Information courtesy of IMDb (https://www.imdb.com).", "Licence not audited: owner decision 2026-11-07.",
                                                 f"datasets {self.today}", digest, max(e["retrieved_at"] for e in m.values())))
        self.src_imdb = c("SELECT source_id FROM source WHERE name = 'imdb-datasets'").fetchone()[0]
        st_ml = self.inp.movielens.stat()
        ml = {"bytes": st_ml.st_size, "mtime": int(st_ml.st_mtime)}
        c("INSERT INTO source (name, kind, url, license, license_url, usage_scope, attribution_required, attribution_text, terms_note, snapshot_label, snapshot_sha256, retrieved_at)"
          " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ("movielens-32m-aggregates", "dataset", "https://grouplens.org/datasets/movielens/32m/", "GroupLens MovieLens 32M", None, "unverified", 1,
                                                 "MovieLens 32M, GroupLens.", "Only per-film aggregates (mean, count) are stored; licence not audited: owner decision 2026-11-07.",
                                                 "ml-32m", f"bytes={ml['bytes']};mtime={ml['mtime']}", "2023-10-13"))
        self.src_ml = c("SELECT source_id FROM source WHERE name = 'movielens-32m-aggregates'").fetchone()[0]
        self.src_film = (c("SELECT source_id FROM source WHERE name = 'film-catalog-v3'").fetchone() or [None])[0]
        self.imdb_title = {}
        self.sanitize_external_ids()  # before anything reads the identifiers: a value with the wrong shape never feeds the rest of the build
        for scheme, value in c("SELECT scheme, value FROM external_id"):
            self.used_ids.add((scheme, value))
        for eid, scheme, value in c("SELECT entity_id, scheme, value FROM external_id WHERE scheme = 'imdb_title'"):
            self.imdb_work[value] = eid
        for row in c("SELECT entity_id, name_norm, language, kind FROM entity_name"):
            self.name_seen.add((row[0], row[1], row[2] or "", row[3]))
        for row in c("SELECT work_id, person_id, role, COALESCE(character_name, '') FROM credit"):
            self.credit_seen.add(row)
        self.kind_of = {w: k for w, k in c("SELECT work_id, kind FROM work")}
        self.parents = {p for (p,) in c("SELECT DISTINCT parent_work_id FROM work WHERE parent_work_id IS NOT NULL")}
        self.genre_id = {code: gid for gid, code in c("SELECT genre_id, code FROM genre")}
        self.label_by_norm = {(norm, en): lid for lid, norm, en in c("SELECT label_id, label_norm, label_en FROM genre_label WHERE label_en IS NOT NULL")}
        self.next_label = c("SELECT COALESCE(MAX(label_id), 0) + 1 FROM genre_label").fetchone()[0]
        self.imdb_title = {}  # filled lazily

    def title_row(self, tconst: str) -> tuple | None:
        row = self.imdb_title.get(tconst)
        if row is None and tconst not in self.imdb_title:
            row = self.st.execute("SELECT type, ptitle, otitle, adult, start, runtime, genres, pnorm, onorm FROM title WHERE tconst = ?", (tconst,)).fetchone()
            self.imdb_title[tconst] = row
        return row

    # ------------------------------------------------------------------------------- 1b. identifiers with a wrong shape
    _IMDB_TYPES_FOR = {"series": {"tvSeries", "tvMiniSeries"}, "miniseries": {"tvSeries", "tvMiniSeries"}, "episode": {"tvEpisode"},
                       "film": {"movie", "tvMovie", "tvSpecial", "video"}, "short": {"short", "tvShort"}, "tv_film": {"tvMovie", "tvSpecial", "movie"}}

    def sanitize_external_ids(self) -> None:
        """Remove every identifier whose value does not have the shape of its scheme. A verified correction (`id_overrides.json`) replaces it only for the exact record that
        supplied it, and only if the replacement exists in the local IMDb archive with a type compatible with the work and a year within one of the work's; otherwise the
        identifier stays absent. The rejected value is kept as a claim of the source that supplied it, and every case is listed in the separate archive `invalid_ids`."""
        overrides = id_rules.load_overrides(self.inp.id_overrides)
        bad = [(e, s, v, p, src, ref) for e, s, v, p, src, ref in self.db.execute("SELECT entity_id, scheme, value, is_primary, source_id, source_ref FROM external_id ORDER BY scheme, entity_id, value")
               if not id_rules.has_valid_shape(s, v)]
        taken = {(s, v) for s, v in self.db.execute("SELECT scheme, value FROM external_id")}
        for eid, scheme, value, primary, source, ref in bad:
            self.db.execute("DELETE FROM external_id WHERE entity_id = ? AND scheme = ? AND value = ?", (eid, scheme, value))
            self.claim(eid, f"{scheme}_rejected", value, source, ref)
            self.counts[f"id_wrong_shape:{scheme}"] += 1
            record = {"entity_id": eid, "scheme": scheme, "rejected": value, "source_ref": ref, "result": "dropped"}
            entry = overrides.get((scheme, value, ref or ""))
            if entry and entry["action"] == "replace":
                replacement = entry["value"]
                work = self.db.execute("SELECT kind, release_year FROM work WHERE work_id = ?", (eid,)).fetchone()
                row = self.title_row(replacement) if scheme == "imdb_title" else None
                reason = None
                if scheme != "imdb_title" or work is None:
                    reason = "only a title id of a work can be corrected"
                elif row is None:
                    reason = "the replacement is not in the IMDb archive"
                elif row[0] not in self._IMDB_TYPES_FOR.get(work[0], {row[0]}):
                    reason = f"IMDb type {row[0]} is not compatible with a work of kind {work[0]}"
                elif work[1] is not None and row[4] is not None and abs(int(row[4]) - int(work[1])) > 1:
                    reason = f"IMDb year {row[4]} differs from the work's {work[1]}"
                elif (scheme, replacement) in taken:
                    reason = "the replacement already identifies another entity"
                if reason is None:
                    self.db.execute("INSERT INTO external_id (entity_id, scheme, value, is_primary, source_id, source_ref) VALUES (?,?,?,?,?,?)",
                                    (eid, scheme, replacement, primary, self.src_imdb, f"override:{entry['id']}"))
                    self.claim(eid, f"{scheme}_override", f"{value} -> {replacement}", self.src_imdb, f"override:{entry['id']}")
                    taken.add((scheme, replacement))
                    self.counts[f"id_override_replaced:{scheme}"] += 1
                    record.update(result="replaced", value=replacement, override=entry["id"])
                else:
                    self.counts[f"id_override_refused:{scheme}"] += 1
                    record.update(result="dropped", override=entry["id"], refused=reason)
            else:
                self.counts[f"id_dropped:{scheme}"] += 1
            self.separate["invalid_ids"].append(record)

    # -------------------------------------------------------------------------------- 2. recovery of identifiers
    def recover_identifiers(self) -> None:
        """Works the v2 build imported WITHOUT identifiers (`ids_reliable = false`): attach the IMDb id only if IMDb confirms them."""
        by_ref = {ref.split(";")[0]: w for w, ref in self.db.execute("SELECT work_id, source_ref FROM work WHERE source_ref IS NOT NULL")}
        report = []
        for name in ("series", "tv_movies"):
            path = self.inp.s5_dir / f"{name}.jsonl"
            if not path.is_file():
                continue
            for d in util.iter_jsonl(path):
                ids = d.get("ids") or {}
                t = util.imdb_tt(ids.get("imdb_id"))
                if not t or d.get("ids_reliable") or not d.get("default_search_eligible", True):
                    continue
                w = by_ref.get(d.get("record_id"))
                if w is None or t in self.imdb_work:
                    continue
                self.counts["recovery_candidates"] += 1
                verdict, why = self.confirm_tv_record(d, t)
                if not verdict:
                    self.counts[f"recovery_not_confirmed:{why}"] += 1
                    if self.title_row(t):
                        self.candidate(w, "imdb_title", t, "ids_reliable_false_unconfirmed", why)
                    continue
                self.add_external(w, "imdb_title", t, d["record_id"])
                self.register_imdb(w, t)
                self.counts["recovered_identifiers"] += 1
                qid = ids.get("qid")
                if qid and self.add_external(w, "wikidata", qid, d["record_id"], primary=True):
                    self.counts["recovered_qids"] += 1
                report.append({"work_id": w, "record_id": d.get("record_id"), "title": d.get("title"), "imdb": t, "qid": qid, "imdb_type": self.title_row(t)[0]})
        self.separate["recovered_identifiers"] = report

    def confirm_tv_record(self, rec: dict, tconst: str) -> tuple[bool, str]:
        row = self.title_row(tconst)
        if row is None:
            return False, "imdb_id_unknown_to_imdb"
        ttype, _p, _o, _adult, start, _rt, _g, pnorm, onorm = row
        title = rec.get("title") or ""
        keys = {util.norm_title(title), util.norm_title(util.strip_qualifier(title)), util.norm_title(rec.get("original_title") or "")} - {""}
        if not keys & {pnorm, onorm}:
            return False, "title_differs"
        year = rec.get("year")
        if not (isinstance(year, int) or str(year).isdigit()) or not start or abs(int(year) - start) > 1:
            return False, "year_differs_or_missing"
        if ttype not in TV_TYPES:
            return False, "type_not_television"
        return True, "confirmed"

    # ------------------------------------------------------------------------ 2b. the primary IMDb id of each work
    def register_imdb(self, work: int, tconst: str) -> None:
        """A work's (only or primary) IMDb id: the one whose record feeds type, year, runtime and ratings."""
        self.imdb_work[tconst] = work
        self.primary_tconst[work] = tconst

    def choose_primary_imdb(self) -> None:
        """Works with several IMDb ids: choose the primary by rule (`reconcile_rules.primary_imdb_id`) and rewrite `is_primary` in THIS build only.

        The v2 flag follows Wikidata's order, not any quality: on the 58 doubles it was wrong on 14. The secondary ids stay on the work as
        non-primary identifiers; their IMDb values are kept as claims (`alias_claims`), never applied to the work."""
        by_work: dict[int, list[str]] = collections.defaultdict(list)
        for tconst, w in sorted(self.imdb_work.items()):
            by_work[w].append(tconst)
        for w, ids in sorted(by_work.items()):
            if len(ids) == 1:
                self.primary_tconst[w] = ids[0]
                # 50 works of the v2 file carry their only IMDb id flagged non-primary (a v2 build quirk): a sole id is the primary one
                if self.db.execute("UPDATE external_id SET is_primary = 1 WHERE entity_id = ? AND scheme = 'imdb_title' AND value = ? AND is_primary = 0", (w, ids[0])).rowcount:
                    self.counts["imdb_sole_id_made_primary"] += 1
                continue
            names = {util.norm_title(n) for (n,) in self.db.execute("SELECT name FROM entity_name WHERE entity_id = ?", (w,))} - {""}
            cands = []
            for t in ids:
                row = self.title_row(t)
                votes = self.st.execute("SELECT votes FROM rating WHERE tconst = ?", (t,)).fetchone()
                cands.append({"tconst": t, "known": row is not None, "title_match": bool(row) and bool(names & {row[7], row[8]}), "votes": votes[0] if votes else 0})
            best = RR.primary_imdb_id(cands)
            flagged = [v for (v,) in self.db.execute("SELECT value FROM external_id WHERE entity_id = ? AND scheme = 'imdb_title' AND is_primary = 1", (w,))]
            self.primary_tconst[w] = best
            self.counts["double_imdb_works"] += 1
            if flagged != [best]:
                old_src = {v: sid for v, sid in self.db.execute("SELECT value, source_id FROM external_id WHERE entity_id = ? AND scheme = 'imdb_title'", (w,))}
                self.db.execute("UPDATE external_id SET is_primary = 0 WHERE entity_id = ? AND scheme = 'imdb_title'", (w,))
                self.db.execute("UPDATE external_id SET is_primary = 1 WHERE entity_id = ? AND scheme = 'imdb_title' AND value = ?", (w, best))
                for old in flagged:
                    self.claim(w, "imdb_title_previous_primary", old, old_src[old], old)
                self.counts["double_imdb_primary_changed"] += 1
            for t in ids:
                if t != best:
                    self.imdb_alias[t] = w

    def alias_claims(self, work: int, tconst: str) -> None:
        """What IMDb says about a SECONDARY id of a work, kept as claims (value, source and the id as `source_ref`); never applied to the work."""
        row = self.title_row(tconst)
        if row is None:
            self.claim(work, "imdb_alt_id_unknown_to_imdb", tconst, self.src_imdb, tconst)
            return
        ttype, ptitle, _o, _a, start, runtime, _g, _pn, _on = row
        for fld, val in (("imdb_alt_title_type", ttype), ("imdb_alt_title", ptitle), ("imdb_alt_release_year", start), ("imdb_alt_runtime_min", runtime)):
            if val not in (None, ""):
                self.claim(work, fld, val, self.src_imdb, tconst)
        r = self.st.execute("SELECT average, votes FROM rating WHERE tconst = ?", (tconst,)).fetchone()
        if r:
            self.claim(work, "imdb_alt_rating", f"{r[0]}/10 ({r[1]} votes)", self.src_imdb, tconst)

    # ------------------------------------------------------------------------ 3b. person reconciliation (approved rules only)
    def _attach_person_id(self, person: int, nconst: str, ref: str) -> bool:
        if not self.add_external(person, "imdb_name", nconst, ref, primary=True):
            return False
        self.person_of_nconst[nconst] = person
        self.unattached_nconst.discard(nconst)
        self.db.execute("DELETE FROM external_id_candidate WHERE entity_id = ? AND scheme = 'imdb_name' AND value = ?", (person, nconst))
        return True

    def reconcile_persons(self, cand: dict) -> None:
        """(1) merge persons ONLY where `reconcile_rules.merge_check` passes (a reversible map, nothing deleted); (2) give an id claimed by
        several persons to the one whose birth year matches IMDb's and whom every other claimant contradicts."""
        deaths = {p: d for p, d in self.db.execute("SELECT person_id, death_year FROM person")}
        births = {p: b for p, b in self.db.execute("SELECT person_id, birth_year FROM person")}
        with_imdb = {e for (e,) in self.db.execute("SELECT entity_id FROM external_id WHERE scheme = 'imdb_name'")}
        claimants = {r["nconst"]: set(r["persons"]) for r in cand["nconst_shared"]}
        touched: set[int] = set()
        pairs_path = self.inp.audit_dir / "candidates_person_pairs.jsonl"
        if pairs_path.is_file():
            pairs = [r for r in util.iter_jsonl(pairs_path) if r["class"] == "same_person_candidate_strong_shared_work_and_role"]
            resolved = {r["person_id"]: r for r in cand["person_nconst"]}
            for row in RC.classify_person_pairs(self.ctx, resolved, pairs):
                if row["class"] != "duplicate_confirmed_by_imdb_same_person_id":
                    continue
                a, b = row["persons"]
                n = row["imdb_ids"][0][0]
                imdb = self.st.execute("SELECT birth, death FROM name WHERE nconst = ?", (n,)).fetchone() or (None, None)
                ok, why = RR.merge_check(imdb[0], imdb[1], {"birth": births.get(a), "death": deaths.get(a)}, {"birth": births.get(b), "death": deaths.get(b)}, bool(row["shared_credits"]))
                if ok and claimants.get(n) != {a, b}:
                    ok, why = False, "id_claimed_by_other_persons"
                if ok and ({a, b} & touched or {a, b} & with_imdb):
                    ok, why = False, "person_already_merged_or_has_another_imdb_id"
                if not ok:
                    self.counts[f"person_merge_refused:{why}"] += 1
                    continue
                survivor, merged = RR.merge_survivor({"id": a, "birth": births.get(a), "credits": row["credits"][0]}, {"id": b, "birth": births.get(b), "credits": row["credits"][1]})
                evidence = json.dumps({"imdb": n, "imdb_birth": imdb[0], "imdb_death": imdb[1], "shared_credits": row["shared_credits"][:3]}, sort_keys=True)
                self.merges.append((survivor, merged, n, evidence))
                touched |= {a, b}
                self._attach_person_id(survivor, n, "layer:merged_pair")
                with_imdb.add(survivor)
                self.counts["person_merges"] += 1
        shared_rows = RC.classify_shared_nconst(self.ctx, self.st, cand["nconst_shared"])
        for row in shared_rows:
            n = row["nconst"]
            if n in self.person_of_nconst:
                continue
            imdb = self.st.execute("SELECT death FROM name WHERE nconst = ?", (n,)).fetchone()
            owner = RR.shared_id_owner(row, imdb[0] if imdb else None, deaths, with_imdb)
            if owner is None:
                continue
            if self._attach_person_id(owner, n, "layer:birth_year_decides"):
                with_imdb.add(owner)
                self.counts["person_ids_attached_birth_year_decides"] += 1

    # ---------------------------------------------------------------------------------------- 3. person ids
    def match_people(self) -> None:
        imdb_of_work = {w: self.primary_tconst[w] for w, sc in self.ctx.rev.items() if sc.get("imdb_title") and w in self.primary_tconst}
        summary, cand = AS.people_and_cast(self.ctx, self.st, imdb_of_work)
        self.people_summary = summary
        shared = {r["nconst"] for r in cand["nconst_shared"]}
        self.person_of_nconst: dict[str, int] = {}
        self.unattached_nconst: set[str] = set(shared)
        persons_with_imdb = {e for (e,) in self.db.execute("SELECT entity_id FROM external_id WHERE scheme = 'imdb_name'")}
        for r in cand["person_nconst"]:
            p, tier, ns = r["person_id"], r["tier"], r["nconst"]
            if tier == "strong" and ns[0] not in shared and p not in persons_with_imdb:
                if self.add_external(p, "imdb_name", ns[0], "layer:strong", primary=True):
                    self.person_of_nconst[ns[0]] = p
                    self.counts["person_ids_attached_strong"] += 1
            else:
                for n in ns:
                    self.unattached_nconst.add(n)
                    t = {"weak_single_title_no_birth_confirmation": "weak_single_title", "conflict_birth_year": "conflict_birth_year",
                         "conflict_several_nconst": "conflict_several_candidates"}.get(tier, "weak_single_title")
                    self.candidate(p, "imdb_name", n, t, f"title matches: {r.get('titles')}; birth cinema {r.get('birth_cinema')} imdb {r.get('birth_imdb')}")
                    self.cand_of_nconst[n].append((p, t))
        for r in cand["nconst_shared"]:
            for p in r["persons"]:
                self.candidate(p, "imdb_name", r["nconst"], "shared_by_several_entities", f"claimed by {len(r['persons'])} entities")
                self.cand_of_nconst[r["nconst"]].append((p, "shared_by_several_entities"))
        self.reconcile_persons(cand)
        self.credit_matches = cand["_credit_matches"]
        # credit order and characters for credits that already exist (fill only what is empty; never overwrite)
        updated_order = updated_char = 0
        for credit_id, nconst, ordering, chars, _cat in sorted(self.credit_matches):
            row = self.db.execute("SELECT work_id, person_id, role, character_name, billing_order FROM credit WHERE credit_id = ?", (credit_id,)).fetchone()
            if row is None:
                continue
            w, p, role, character, order = row
            new_char = " / ".join(L.parse_characters(chars)) or None
            sets, args = [], []
            if order is None and ordering is not None:
                sets.append("billing_order = ?")
                args.append(ordering)
            if character is None and new_char and (w, p, role, new_char) not in self.credit_seen:
                sets.append("character_name = ?")
                args.append(new_char)
            if sets:
                self.db.execute(f"UPDATE credit SET {', '.join(sets)} WHERE credit_id = ?", (*args, credit_id))
                updated_order += "billing_order = ?" in sets
                if "character_name = ?" in sets:
                    updated_char += 1
                    self.credit_seen.discard((w, p, role, ""))
                    self.credit_seen.add((w, p, role, new_char))
        self.counts["credits_given_billing_order"] = updated_order
        self.counts["credits_given_character"] = updated_char

    # ------------------------------------------------------------------------------ 4. priority: type, year, runtime
    def apply_priority(self, work_id: int, tconst: str, *, allow_kind: bool = True) -> None:
        row = self.title_row(tconst)
        if row is None:
            return
        ttype, _p, _o, _adult, start, runtime, _g, _pn, _on = row
        kind, year, rdate, rt, src, ref = self.db.execute("SELECT kind, release_year, release_date, runtime_min, source_id, source_ref FROM work WHERE work_id = ?", (work_id,)).fetchone()
        if allow_kind and kind in CHANGEABLE_KINDS:
            mapped = TYPE_TO_KIND.get(ttype)
            if mapped and mapped != kind and work_id not in self.parents:
                self.claim(work_id, "kind", kind, src, ref)
                self.db.execute("UPDATE work SET kind = ? WHERE work_id = ?", (mapped, work_id))
                self.kind_of[work_id] = mapped
                self.provenance(work_id, "kind", tconst)
                self.counts["kind_changed"] += 1
            elif not mapped:
                self.claim(work_id, "imdb_title_type", ttype, self.src_imdb, tconst)
            elif mapped != kind:
                self.claim(work_id, "imdb_title_type", ttype, self.src_imdb, tconst)  # has children: kind kept, IMDb value recorded
        if start and 1800 <= start <= 2100 and start != year:
            if year is not None:
                self.claim(work_id, "release_year", year, src, ref)
                self.counts["year_changed"] += 1
            else:
                self.counts["year_filled"] += 1
            self.db.execute("UPDATE work SET release_year = ? WHERE work_id = ?", (start, work_id))
            self.provenance(work_id, "release_year", tconst)
            if rdate and int(rdate[:4]) != start:
                self.claim(work_id, "release_date", rdate, src, ref)
                self.db.execute("UPDATE work SET release_date = NULL WHERE work_id = ?", (work_id,))
                self.counts["release_date_moved_to_claim"] += 1
        if runtime and 1 <= runtime <= 3000 and runtime != rt:
            if rt is not None:
                self.claim(work_id, "runtime_min", rt, src, ref)
                self.counts["runtime_changed"] += 1
            else:
                self.counts["runtime_filled"] += 1
            self.db.execute("UPDATE work SET runtime_min = ? WHERE work_id = ?", (runtime, work_id))
            self.provenance(work_id, "runtime_min", tconst)

    # ------------------------------------------------------------------------------------------- 5. ratings
    def add_ratings(self) -> None:
        """IMDb rating of the PRIMARY id only (a secondary id's rating is a claim); MovieLens aggregate once per work, through the primary id or,
        when no MovieLens film carries it, through the single film that carries a secondary id (several candidates = ambiguous = skipped)."""
        rating = {t: (a, v) for t, a, v in self.st.execute("SELECT tconst, average, votes FROM rating")}
        for w, tconst in sorted(self.primary_tconst.items()):
            r = rating.get(tconst)
            if r:
                self.db.execute("INSERT OR IGNORE INTO work_rating VALUES (?,?,?,?,?,?,?,?)", (w, self.src_imdb, r[0], 10.0, r[1], "audience", self.today, tconst))
                self.counts["ratings_imdb"] += 1
        if self.inp.movielens_layer:  # the id -> work map is read from the database NOW (episodes included); also fills ml_movie, genres and tags
            ML.apply(self)
            return
        ml = util.open_ro(self.inp.movielens)
        last = ml.execute("SELECT MAX(last_rated_at) FROM movie_stats").fetchone()[0]
        as_of = datetime.fromtimestamp(last, timezone.utc).strftime("%Y-%m-%d") if last else "2023-10-13"
        by_work: dict[int, list[tuple]] = collections.defaultdict(list)
        for movie_id, imdb, n, avg in ml.execute("SELECT l.movie_id, l.imdb_id, s.n_ratings, s.avg_rating FROM links l JOIN movie_stats s USING(movie_id) ORDER BY l.movie_id"):
            t = util.imdb_tt(imdb)
            w = (self.imdb_work.get(t) or self.imdb_alias.get(t)) if t else None
            if w is not None and n:
                by_work[w].append((movie_id, t, n, avg))
        for w, rows in sorted(by_work.items()):
            primary = [r for r in rows if r[1] == self.primary_tconst.get(w)]
            chosen = primary[0] if primary else (rows[0] if len(rows) == 1 else None)
            if chosen is None:
                self.counts["movielens_rating_ambiguous_alias"] += 1
                continue
            movie_id, t, n, avg = chosen
            self.db.execute("INSERT OR IGNORE INTO work_rating VALUES (?,?,?,?,?,?,?,?)", (w, self.src_ml, avg, 5.0, n, "audience", as_of, f"movielens:{movie_id}"))
            self.counts["ratings_movielens"] += 1
            if t != self.primary_tconst.get(w):
                self.counts["ratings_movielens_through_an_alias"] += 1

    # ------------------------------------------------------------------------------------------ 6. episodes
    def match_episodes(self) -> None:
        c = self.db
        eps: dict[int, list[tuple]] = collections.defaultdict(list)
        for w, parent_kind, parent, grand, season, number, year, title in c.execute(
            "SELECT e.work_id, p.kind, p.work_id, p.parent_work_id, e.season_number, e.episode_number, e.release_year, "
            "(SELECT name FROM entity_name n WHERE n.entity_id = e.work_id AND n.is_primary = 1) FROM work e JOIN work p ON p.work_id = e.parent_work_id WHERE e.kind = 'episode'"):
            series = grand if parent_kind == "season" else parent
            eps[series].append((w, season, number, year, util.norm_title(title or "")))
        total = strong = weak = unmatched_imdb = 0
        for series, tconst in sorted(self.primary_tconst.items()):  # the PRIMARY id of a series only: a secondary id may belong to another work
            if series not in eps:
                continue
            imdb_eps = self.st.execute("SELECT e.tconst, e.season, e.number, t.start, t.pnorm FROM episode e LEFT JOIN title t USING(tconst) WHERE e.parent = ?", (tconst,)).fetchall()
            if not imdb_eps:
                continue
            by_num: dict[tuple, list] = collections.defaultdict(list)
            for row in imdb_eps:
                if row[1] is not None and row[2] is not None:
                    by_num[(row[1], row[2])].append(row)
            cin_num: dict[tuple, list] = collections.defaultdict(list)
            for row in eps[series]:
                if row[1] is not None and row[2] is not None:
                    cin_num[(row[1], row[2])].append(row)
            used_imdb: set[str] = set()
            used_cin: set[int] = set()
            pairs: list[tuple[int, str, str]] = []
            for key, cs in sorted(cin_num.items()):
                ims = by_num.get(key, [])
                if len(cs) != 1 or len(ims) != 1:
                    continue
                cw, im = cs[0], ims[0]
                cy, iy = cw[3], im[3]
                if cy and iy:
                    ok = abs(cy - iy) <= 1
                    tier = "number+year"
                else:
                    ok = bool(cw[4]) and cw[4] == im[4]
                    tier = "number+title"
                if ok:
                    pairs.append((cw[0], im[0], tier))
                    used_imdb.add(im[0]); used_cin.add(cw[0])
                else:
                    self.candidate(cw[0], "imdb_title", im[0], "episode_number_only", f"episode number {key} only; year/title do not confirm")
                    weak += 1
            # remaining: unique normalised title inside the series, year compatible
            cin_title = collections.defaultdict(list)
            for row in eps[series]:
                if row[0] not in used_cin and row[4]:
                    cin_title[row[4]].append(row)
            im_title = collections.defaultdict(list)
            for row in imdb_eps:
                if row[0] not in used_imdb and row[4]:
                    im_title[row[4]].append(row)
            for key, cs in sorted(cin_title.items()):
                ims = im_title.get(key, [])
                if len(cs) == 1 and len(ims) == 1 and (not cs[0][3] or not ims[0][3] or abs(cs[0][3] - ims[0][3]) <= 1):
                    pairs.append((cs[0][0], ims[0][0], "title_unique"))
                    used_imdb.add(ims[0][0])
            total += len(eps[series])
            unmatched_imdb += sum(1 for r in imdb_eps if r[0] not in used_imdb)
            for cw, it, tier in pairs:
                if cw in self.primary_tconst:  # the cinema episode already has an IMDb id: a second one would be a conflict, never a silent alias
                    self.candidate(cw, "imdb_title", it, "episode_number_only", f"matched by {tier} but the episode already has the IMDb id {self.primary_tconst[cw]}")
                    self.counts["episode_match_refused:episode_already_has_another_imdb_id"] += 1
                    continue
                if self.add_external(cw, "imdb_title", it, f"episode:{tier}"):
                    strong += 1
                    self.counts[f"episode_match:{tier}"] += 1
                    self.apply_priority(cw, it, allow_kind=False)
                    r = self.st.execute("SELECT average, votes FROM rating WHERE tconst = ?", (it,)).fetchone()
                    if r:
                        self.db.execute("INSERT OR IGNORE INTO work_rating VALUES (?,?,?,?,?,?,?,?)", (cw, self.src_imdb, r[0], 10.0, r[1], "audience", self.today, it))
                        self.counts["ratings_imdb_episodes"] += 1
        self.counts["episodes_of_series_with_imdb_id"] = total
        self.counts["episodes_matched_strong"] = strong
        self.counts["episodes_weak_candidates"] = weak
        self.counts["imdb_episodes_not_in_cinema"] = unmatched_imdb

    def import_episodes(self) -> None:
        """IMDb episodes of series that ALREADY have episodes here, linked to the series by the parent's PRIMARY IMDb id (no title deduction).

        Imported only if IMDb gives a title, a season and an episode number and the (series, season, number) slot is free in this database.
        Parent = the existing season work of that number if there is one, else the series (how the existing episodes are organised)."""
        c = self.db
        slots: set[tuple] = set()
        with_episodes: set[int] = set()
        for parent_kind, parent, grand, season, number in c.execute(
                "SELECT p.kind, p.work_id, p.parent_work_id, e.season_number, e.episode_number FROM work e JOIN work p ON p.work_id = e.parent_work_id WHERE e.kind = 'episode'"):
            series = grand if parent_kind == "season" else parent
            with_episodes.add(series)
            slots.add((series, season, number))
        season_work: dict[tuple, int] = {}
        for w, parent, season in c.execute("SELECT work_id, parent_work_id, season_number FROM work WHERE kind = 'season' AND season_number IS NOT NULL ORDER BY work_id"):
            season_work.setdefault((parent, season), w)
        for series, tconst in sorted(self.primary_tconst.items()):
            if series not in with_episodes:
                continue
            for et, season, number in self.st.execute("SELECT tconst, season, number FROM episode WHERE parent = ? ORDER BY season, number, tconst", (tconst,)).fetchall():
                if ("imdb_title", et) in self.used_ids:
                    continue
                row = self.title_row(et)
                if row is None or row[0] != "tvEpisode" or row[3]:
                    self.counts["episodes_not_imported:not_a_plain_tvEpisode"] += 1
                elif not row[1] or not normalize_name(" ".join(str(row[1]).split())):  # a work needs a primary name: no title (or only punctuation) = not imported
                    self.counts["episodes_not_imported:no_title"] += 1
                elif season is None or number is None or season < 0 or number < 0:
                    self.counts["episodes_not_imported:no_season_or_number"] += 1
                elif (series, season, number) in slots:
                    self.counts["episodes_not_imported:position_taken"] += 1
                else:
                    _t, ptitle, otitle, _a, start, runtime, _g, _pn, _on = row
                    wid = self.new_entity("work")
                    parent = season_work.get((series, season), series)
                    c.execute("INSERT INTO work (work_id, kind, parent_work_id, season_number, episode_number, release_year, runtime_min, source_id, source_ref) VALUES (?,?,?,?,?,?,?,?,?)",
                              (wid, "episode", parent, season, number, start if start and 1800 <= start <= 2100 else None,
                               runtime if runtime and 1 <= runtime <= 3000 else None, self.src_imdb, et))
                    self.kind_of[wid] = "episode"
                    self.add_name(wid, ptitle, "primary", None, et, primary=True)
                    if otitle and otitle != ptitle:
                        self.add_name(wid, otitle, "original", None, et)
                    self.add_external(wid, "imdb_title", et, "episode:parent_id", primary=True)
                    c.execute("INSERT INTO work_status VALUES (?,?,?,?,?)", (wid, "imdb_episode", "imdb_episode_parent_id", None, "skeleton"))
                    slots.add((series, season, number))
                    r = self.st.execute("SELECT average, votes FROM rating WHERE tconst = ?", (et,)).fetchone()
                    if r:
                        c.execute("INSERT OR IGNORE INTO work_rating VALUES (?,?,?,?,?,?,?,?)", (wid, self.src_imdb, r[0], 10.0, r[1], "audience", self.today, et))
                        self.counts["ratings_imdb_episodes"] += 1
                    self.counts["episodes_imported"] += 1

    # ------------------------------------------------------------------------------------ 7. new works
    def cinema_title_index(self) -> dict[tuple[str, int], list[int]]:
        """(title key, year) -> existing works. Keys: the historical ASCII form AND the Unicode form (`title_keys`); an empty key is never stored.
        `self.old_index` keeps the historical index WITH its empty key, only to say which holds were caused by that defect."""
        index: dict[tuple[str, int], list[int]] = collections.defaultdict(list)
        old: dict[tuple[str, int], list[int]] = collections.defaultdict(list)
        for w, name, year in self.db.execute("SELECT n.entity_id, n.name, w.release_year FROM entity_name n JOIN work w ON w.work_id = n.entity_id "
                                             "WHERE w.kind NOT IN ('episode','season') AND w.release_year IS NOT NULL"):
            old[(util.norm_title(name), year)].append(w)
            for key in TK.title_keys(name):
                index[(key, year)].append(w)
        self.old_index = old
        return index

    def cinema_candidates(self, index, row, extra_titles=()) -> list[int]:
        """Existing works with the same title (IMDb primary or original, or the Italian page title) and a year within one."""
        _t, ptitle, otitle, _a, start, _rt, _g, pn, on = row
        found: set[int] = set()
        keys = set(TK.title_keys(ptitle)) | set(TK.title_keys(otitle)) | {k for k in (pn, on) if k}
        for t in extra_titles:
            if t:
                keys |= TK.title_keys(util.strip_qualifier(t))
        for key in keys:
            for dy in (0, -1, 1):
                found.update(index.get((key, start + dy), []))
        return sorted(found)

    def historical_candidates(self, row, extra_titles=()) -> list[int]:
        """What the check found BEFORE the Unicode correction (the ASCII key, empty included): only to tell spurious holds from real ones."""
        _t, _p, _o, _a, start, _rt, _g, pn, on = row
        found: set[int] = set()
        for key in (pn, on, *[util.norm_title(util.strip_qualifier(t)) for t in extra_titles if t]):
            for dy in (0, -1, 1):
                found.update(self.old_index.get((key, start + dy), []))
        return sorted(found)

    def possible_duplicates_by_director(self, row, tconst: str) -> list[int]:
        """Film-like works of the same year (+-1) that share a director with this IMDb title: independent evidence that a title with no title match
        may still be a work we already have (for example the same film under a transliterated name). Names are compared in their own script."""
        if not hasattr(self, "_director_index"):
            idx: dict[int, dict[str, set[int]]] = collections.defaultdict(lambda: collections.defaultdict(set))
            for w, year, name in self.db.execute(
                    "SELECT w.work_id, w.release_year, n.name FROM work w JOIN credit c ON c.work_id = w.work_id AND c.role = 'director' "
                    "JOIN entity_name n ON n.entity_id = c.person_id AND n.is_primary = 1 WHERE w.kind IN ('film','short','tv_film') AND w.release_year IS NOT NULL"):
                key = TK.person_key(name)
                if key:
                    idx[year][key].add(w)
            self._director_index = idx
        crew = self.st.execute("SELECT directors FROM crew WHERE tconst = ?", (tconst,)).fetchone()
        names = {TK.person_key(n) for x in L.split_ids(crew[0] if crew else None) for (n,) in self.st.execute("SELECT name FROM name WHERE nconst = ?", (x,))} - {""}
        start = row[4]
        found: set[int] = set()
        for dy in (0, -1, 1):
            for key in names:
                found |= self._director_index.get(start + dy, {}).get(key, set())
        # a twin that already carries ANOTHER IMDb id that IMDb knows is a different IMDb title (a prolific director has several films a year):
        # only works without such an id stay possible duplicates
        def has_other_known_id(w: int) -> bool:
            return any(i != tconst and self.title_row(i) for (i,) in self.db.execute("SELECT value FROM external_id WHERE entity_id = ? AND scheme = 'imdb_title'", (w,)))
        return sorted(w for w in found if not has_other_known_id(w))

    def hold_detail(self, index, row, tconst: str, extra_titles, reason: str) -> dict:
        """For a title held back because an existing work has the same title and year: who they are and what the directors say.

        `same_director` = probably the same film (if the existing work has no IMDb id, the id could be attached); `different_directors` =
        probably a homonym; `director_unknown` = no proof. Nothing is acted upon: the classification goes to the archive for the owner."""
        if not reason.startswith("reconciliation_hold"):
            return {}
        cands = self.cinema_candidates(index, row, extra_titles)[:5] or self._guard_works.get(tconst, [])[:5]
        best, has_imdb = self.director_verdict(tconst, cands)
        self.counts[f"hold:{best}"] += 1
        if best == "same_director" and any(w not in has_imdb for w in cands):
            self.counts["hold:same_director_and_the_existing_work_has_no_imdb_id"] += 1
        real = set(self.cinema_candidates(index, row, extra_titles))
        return {"cinema_candidates": cands, "candidate_has_imdb_id": [w in has_imdb for w in cands], "director_verdict": best,
                "candidate_basis": "real_title_match" if real else "same_year_and_same_director_only",
                "proposed_alias_if_same_director_and_no_imdb_id": best == "same_director" and any(w not in has_imdb for w in cands)}

    def director_verdict(self, tconst: str, cands: list[int]) -> tuple[str, set[int]]:
        imdb_dirs = {TK.person_key(nn) for (n,) in self.st.execute("SELECT directors FROM crew WHERE tconst = ?", (tconst,)) for x in L.split_ids(n)
                     for (nn,) in self.st.execute("SELECT name FROM name WHERE nconst = ?", (x,))} - {""}
        has_imdb = {e for (e,) in self.db.execute("SELECT DISTINCT entity_id FROM external_id WHERE scheme = 'imdb_title'")} if not hasattr(self, "_has_imdb") else self._has_imdb
        self._has_imdb = has_imdb
        verdicts = []
        for w in cands:
            names = {TK.person_key(n) for (n,) in self.db.execute("SELECT n.name FROM credit c JOIN entity_name n ON n.entity_id = c.person_id AND n.is_primary = 1 WHERE c.work_id = ? AND c.role = 'director'", (w,))} - {""}
            verdicts.append("same_director" if names & imdb_dirs else "different_directors" if names and imdb_dirs else "director_unknown")
        best = "same_director" if "same_director" in verdicts else ("director_unknown" if "director_unknown" in verdicts else "different_directors")
        return best, has_imdb

    def imdb_directors(self, tconst: str) -> set[str]:
        r = self.st.execute("SELECT directors FROM crew WHERE tconst = ?", (tconst,)).fetchone()
        return set(L.split_ids(r[0])) if r and r[0] else set()

    def hold_check(self, index, row, tconst: str, extra_titles=()) -> tuple[str | None, str | None]:
        """(reason, release class): the title has an existing work with the same title and year; is it proven to be a DIFFERENT work?

        Released only by `reconcile_rules.release_class` (other IMDb id known to IMDb + disjoint IMDb directors or far runtime, or the existing
        work is not film-like); anything else stays held, exactly as before."""
        cands = self.cinema_candidates(index, row, extra_titles)
        if not cands:
            if not self.historical_candidates(row, extra_titles):
                return None, None
            # held before only because an empty ASCII key matched unrelated works: no work has this title. Independent check before entering:
            # an existing work of the same year with the same director stays a possible duplicate and the title stays held.
            twins = self.possible_duplicates_by_director(row, tconst)
            if twins:
                self._guard_works[tconst] = twins
                return "reconciliation_hold_possible_duplicate_same_year_and_director", None
            self.separate["released_from_hold"].append({"imdb": tconst, "class": "U_no_title_match_after_unicode_correction", "cinema_candidates": [], "director_verdict": None})
            self.counts["released_from_hold:U"] += 1
            return None, "U_no_title_match_after_unicode_correction"
        verdict, _ = self.director_verdict(tconst, cands)
        checks = []
        for w in cands:
            if self.kind_of.get(w) not in RR.FILM_LIKE_KINDS:
                continue
            others = [i for (i,) in self.db.execute("SELECT value FROM external_id WHERE entity_id = ? AND scheme = 'imdb_title' ORDER BY is_primary DESC, value", (w,)) if i != tconst]
            known = [i for i in others if self.title_row(i)]
            chk = {"other_id_known": bool(known), "directors_disjoint": False, "runtime_far": False}
            if known:
                other = self.title_row(known[0])
                d1, d2 = self.imdb_directors(tconst), self.imdb_directors(known[0])
                chk["directors_disjoint"] = bool(d1 and d2 and not d1 & d2)
                chk["runtime_far"] = bool(row[5] and other[5] and abs(row[5] - other[5]) > RR.RUNTIME_FAR_MIN)
            checks.append(chk)
        cls = RR.release_class([self.kind_of.get(w, "") for w in cands], verdict == "same_director", checks)
        if cls is None:
            return "reconciliation_hold_same_title_and_year_in_cinema", None
        self.separate["released_from_hold"].append({"imdb": tconst, "class": cls, "cinema_candidates": cands[:5], "director_verdict": verdict})
        self.counts[f"released_from_hold:{cls.split('_')[0]}"] += 1
        return None, cls

    def select_new_works(self) -> list[dict]:
        index = self.cinema_title_index()
        chosen: dict[str, dict] = {}
        have = set(self.imdb_work)
        # route 1: MovieLens links
        ml = util.open_ro(self.inp.movielens)
        tmdb_work = {v: e for e, v in self.db.execute("SELECT entity_id, value FROM external_id WHERE scheme = 'tmdb_movie'")}
        ml_tmdb = collections.Counter(str(x).strip() for (x,) in ml.execute("SELECT tmdb_id FROM links WHERE tmdb_id IS NOT NULL AND tmdb_id <> ''"))
        for movie_id, imdb, title, tmdb, ml_year in ml.execute("SELECT l.movie_id, l.imdb_id, m.title, l.tmdb_id, m.year FROM links l JOIN movies m USING(movie_id) ORDER BY l.movie_id"):
            t = util.imdb_tt(imdb)
            if not t or t in have:
                continue
            tmdb = str(tmdb).strip() if tmdb not in (None, "") else None
            owner = tmdb_work.get(tmdb) if tmdb and ml_tmdb[tmdb] == 1 else None
            if owner is not None:  # two independent local sources (MovieLens and the catalogue) give the same TMDb id: the same film under another IMDb id
                if self.add_external(owner, "imdb_title", t, f"movielens:{movie_id}:tmdb_id", primary=False):
                    self.counts["imdb_alias_attached_through_the_same_tmdb_id"] += 1
                    self.imdb_alias[t] = owner
                    self.alias_claims(owner, t)
                    have.add(t)  # the Italian-page route must not create a second work for this same IMDb id
                continue
            row = self.title_row(t)
            reason = released = None
            if row is None:
                reason = "not_identifiable_via_imdb"
            elif row[0] not in ENTRY_TYPES:
                reason = f"outside_entry_rule:{row[0]}"
            elif row[3]:
                reason = "flagged_adult"
            elif not row[4]:
                reason = "no_year"
            else:
                reason, released = self.hold_check(index, row, t)
            if reason:
                self.separate["not_entered"].append({"imdb": t, "route": "movielens", "movielens_title": title, "imdb_type": row[0] if row else None, "reason": reason,
                                                     **self.hold_detail(index, row, t, (), reason)})
                self.counts[f"not_entered:{reason.split(':')[0]}"] += 1
            else:
                if t in chosen:
                    chosen[t]["ml"].append((movie_id, title, ml_year))
                else:
                    chosen[t] = {"tconst": t, "route": "imdb_movielens", "identification": "imdb_id_given_by_movielens", "page": None, "mixed": None, "released": released,
                                 "ml": [(movie_id, title, ml_year)]}
        # route 2: Italian film pages without a plot (identified by title, year, director; or by the calibrated unique-title rule)
        pages = self.ctx.dump_records() or []
        rejected = self.ctx.pages["rejected"]
        pnames = {n: nn for n, nn in self.st.execute("SELECT nconst, nnorm FROM name")}
        crew = {t: d for t, d, _ in self.st.execute("SELECT tconst, directors, writers FROM crew")}
        dsum, darchive, drecovered = AS.dubious_pages(self.ctx, self.st) if pages else ({}, [], [])
        self.dubious_summary = dsum
        self.separate["dubious_pages"] = darchive  # candidates and the reason of the doubt, outside the catalogue
        recovered_t = {r["page_id"]: r["tconst"] for r in drecovered}
        recovered_reason = {r["page_id"]: r["reason"] for r in drecovered}
        for rec in pages:
            if rec["kind"] != "film_page" or rec["page_id"] not in rejected or not rec.get("year"):
                continue
            tier, t, cands = AS.classify_page(rec, self.st, pnames, crew)
            how, route = "imdb_title_year_director_confirmed", "imdb_itwiki_page"
            if tier == "dubious" and rec["page_id"] in recovered_t:
                t, how, route, tier = recovered_t[rec["page_id"]], RR.identification_for_rule(recovered_reason[rec["page_id"]]), "imdb_itwiki_page_rule", "identified_without_plot"
            if tier != "identified_without_plot":
                continue
            if t in have:
                self.counts["page_identifier_already_in_cinema"] += 1
                continue
            row = self.title_row(t)
            reason = released = None
            if row is None:
                reason = "not_identifiable_via_imdb"
            elif row[0] not in ENTRY_TYPES:
                reason = f"outside_entry_rule:{row[0]}"
            elif row[3]:
                reason = "flagged_adult"
            else:
                reason, released = self.hold_check(index, row, t, (rec["title"], rec.get("original_title")))
            if reason:
                self.separate["not_entered"].append({"imdb": t, "route": "itwiki_page", "page": rec["title"], "imdb_type": row[0] if row else None, "reason": reason,
                                                     **self.hold_detail(index, row, t, (rec["title"], rec.get("original_title")), reason)})
                self.counts[f"not_entered:{reason.split(':')[0]}"] += 1
                continue
            previous = chosen.get(t)
            if previous and previous["route"] != "imdb_movielens":
                continue
            if previous and not RR.weak_page_replaces_movielens(how, RR.movielens_confirms_identity(previous["ml"], [row[1], row[2]], row[4])):
                # a weak page never lowers an identification MovieLens already gives and its own title and year support: the page stays a CLAIM (below)
                previous.setdefault("weak_pages", []).append({"title": rec["title"], "page_id": rec["page_id"], "director": rec.get("director"), "how": how})
                self.counts["weak_page_kept_as_claim_over_movielens"] += 1
                continue
            chosen[t] = {"tconst": t, "route": route, "identification": how, "page": rec, "mixed": None, "released": released}
        # route 3: mixed-media pages (kept out of the series catalogue) whose IMDb id is a film-like work that IMDb confirms
        path = self.inp.s5_dir / "series.jsonl"
        if path.is_file():
            for d in util.iter_jsonl(path):
                if d.get("default_search_eligible", True) or d.get("catalog_class") != "franchise_page_mixed_media":
                    continue
                t = util.imdb_tt((d.get("ids") or {}).get("imdb_id"))
                if not t or t in have or t in chosen:
                    continue
                row = self.title_row(t)
                if row is None or row[0] not in ENTRY_TYPES or row[3] or not row[4]:
                    self.counts["mixed_page_not_entered"] += 1
                    continue
                keys = {util.norm_title(d.get("title") or ""), util.norm_title(util.strip_qualifier(d.get("title") or "")), util.norm_title(d.get("original_title") or "")} - {""}
                year = d.get("year")
                if not keys & {row[7], row[8]} or not (str(year).isdigit() and abs(int(year) - row[4]) <= 1):
                    self.counts["mixed_page_not_entered"] += 1
                    continue
                if self.cinema_candidates(index, row, (d.get("title"), d.get("original_title"))):
                    self.counts["mixed_page_not_entered"] += 1
                    continue
                chosen[t] = {"tconst": t, "route": "imdb_recovered_mixed_page", "identification": "imdb_title_year_type_confirmed", "page": None,
                             "mixed": {"title": d.get("title"), "record_id": d.get("record_id")}}
        return [chosen[t] for t in sorted(chosen)]

    def genre_label_for(self, label_en: str) -> int | None:
        norm = normalize_name(label_en)
        lid = self.label_by_norm.get((norm, label_en)) or next((v for (n, e), v in self.label_by_norm.items() if n == norm), None)
        if lid is not None:
            return lid
        lid = self.next_label
        self.next_label += 1
        self.db.execute("INSERT INTO genre_label (label_id, wikidata_id, label_it, label_en, label_norm, source_id, source_ref) VALUES (?,?,?,?,?,?,?)",
                        (lid, None, None, label_en, norm, self.src_imdb, "imdb:genres"))
        self.label_by_norm[(norm, label_en)] = lid
        for code, mapping, rule in G.map_label(None, label_en):
            if code in self.genre_id:
                self.db.execute("INSERT OR IGNORE INTO genre_label_map VALUES (?,?,?,?,?)", (lid, self.genre_id[code], mapping, rule, self.src_imdb))
        return lid

    def person_for(self, nconst: str, names: dict[str, tuple]) -> int | None:
        if nconst in self.person_of_nconst:
            return self.person_of_nconst[nconst]
        info = names.get(nconst)
        if info is None:
            self.counts["credits_skipped_person_unknown_to_name_basics"] += 1
            return None
        name, birth, death = info
        recovered = nconst in self.unattached_nconst
        pid = self.new_entity("person")
        self.db.execute("INSERT INTO person (person_id, birth_year, death_year, source_id, source_ref) VALUES (?,?,?,?,?)",
                        (pid, birth if birth and 1000 <= birth <= 2100 else None, death if death and 1000 <= death <= 2100 else None, self.src_imdb, nconst))
        self.add_name(pid, name, "primary", None, nconst, primary=True)
        self.add_external(pid, "imdb_name", nconst, "layer:new_person", primary=True)
        self.person_of_nconst[nconst] = pid
        self.counts["people_created"] += 1
        if recovered:
            # the IMDb person is only a CANDIDATE of an existing person (weak, conflicting or shared evidence): keep both, never merge, and say so
            # on both sides (the candidate row sits on the existing person; this claim sits on the new one)
            for existing_person, tier in sorted(self.cand_of_nconst.get(nconst, [])):
                self.claim(pid, "imdb_person_possibly_existing_person", existing_person, self.src_imdb, f"{nconst}:{tier}")
            self.counts["people_created_for_candidate_nconst"] += 1
        return pid

    def insert_new_works(self, selected: list[dict]) -> None:
        names = {n: (nm, b, d) for n, nm, b, d in self.st.execute("SELECT nconst, name, birth, death FROM name")}
        # people who could be an existing person under another spelling are only reported (name + birth year is a candidate, not a merge)
        existing = collections.defaultdict(list)
        for p, name, b in self.db.execute("SELECT n.entity_id, n.name_norm, p.birth_year FROM entity_name n JOIN person p ON p.person_id = n.entity_id WHERE n.is_primary = 1 AND p.birth_year IS NOT NULL"):
            existing[(name, b)].append(p)
        for item in selected:
            t = item["tconst"]
            ttype, ptitle, otitle, _adult, start, runtime, genres, _pn, _on = self.title_row(t)
            page = item["page"]
            primary_text = (page["title"].replace("_", " ") if "(" not in page["title"] else util.strip_qualifier(page["title"])) if page else (
                (item["mixed"]["title"] and util.strip_qualifier(item["mixed"]["title"]) or ptitle) if item["mixed"] else ptitle)
            if not normalize_name(" ".join(str(primary_text or "").split())):
                # the schema needs a searchable primary name (`name_norm`): a title made only of symbols (for example "$" or "()") cannot be one.
                # Nothing is invented: the title goes to the archive of titles not entered, with this reason.
                self.separate["not_entered"].append({"imdb": t, "route": item["route"], "imdb_type": ttype, "title": ptitle, "reason": "title_without_searchable_characters"})
                self.counts["not_entered:title_without_searchable_characters"] += 1
                continue
            wid = self.new_entity("work")
            kind = TYPE_TO_KIND[ttype]
            ref = t if not item["page"] else f"{t};page_id={item['page']['page_id']}"
            self.db.execute("INSERT INTO work (work_id, kind, release_year, runtime_min, source_id, source_ref) VALUES (?,?,?,?,?,?)",
                            (wid, kind, start, runtime if runtime and 1 <= runtime <= 3000 else None, self.src_imdb, ref))
            self.kind_of[wid] = kind
            if page:
                self.add_name(wid, page["title"].replace("_", " ") if "(" not in page["title"] else util.strip_qualifier(page["title"]), "primary", "it", ref, primary=True)
                self.add_name(wid, ptitle, "alias", None, t)
            elif item["mixed"]:
                self.add_name(wid, item["mixed"]["title"] and util.strip_qualifier(item["mixed"]["title"]) or ptitle, "primary", "it", item["mixed"]["record_id"], primary=True)
                self.add_name(wid, ptitle, "alias", None, t)
            else:
                self.add_name(wid, ptitle, "primary", None, t, primary=True)
            if otitle and normalize_name(otitle) != normalize_name(ptitle):
                self.add_name(wid, otitle, "original", None, t)
            self.add_external(wid, "imdb_title", t, ref)
            self.register_imdb(wid, t)
            if item.get("released"):
                self.claim(wid, "reconciliation_released_hold", item["released"], self.src_imdb, t)
            for wp in item.get("weak_pages", []):  # Wikipedia's weaker identification is kept as information, never as the identity of the work
                self.claim(wid, "wikipedia_it_page_not_attached", wp["title"], self.src_imdb, f"page_id={wp['page_id']};{wp['how']}")
                if wp["how"] == "imdb_title_year_unique_director_mismatch":
                    self.claim(wid, "wikipedia_it_page_director_conflict", wp["director"] or "", self.src_imdb, f"page_id={wp['page_id']}")
                for movie_id, _title, _year in item["ml"][:3]:
                    self.claim(wid, "identity_confirmed_by", "movielens_link_title_and_year_consistent_with_imdb", self.src_ml, f"movielens:{movie_id}")
            if page:
                self.add_external(wid, "wikipedia_it", page["title"].replace(" ", "_"), ref)
            for g in (genres or "").split(","):
                if g and g not in ("Short", "Adult"):
                    lid = self.genre_label_for(g)
                    if lid is not None:
                        self.db.execute("INSERT OR IGNORE INTO work_genre VALUES (?,?,?,?)", (wid, lid, self.src_imdb, t))
            self.db.execute("INSERT INTO work_status VALUES (?,?,?,?,?)", (wid, item["route"], item["identification"], "without_plot" if page else None, "skeleton"))
            self.counts[f"new_works:{item['route']}"] += 1
            self.counts[f"new_works_kind:{kind}"] += 1
            self.insert_credits(wid, t, names, existing)

    def insert_credits(self, wid: int, tconst: str, names: dict[str, tuple], existing) -> None:
        listed: set[tuple[str, str]] = set()
        rows = self.st.execute("SELECT ordering, nconst, category, characters FROM principal WHERE tconst = ? ORDER BY ordering", (tconst,)).fetchall()
        for ordering, nconst, category, chars in rows:
            role = CATEGORY_ROLE.get(category)
            if not role:
                self.counts[f"credit_category_not_mapped:{category}"] += 1
                continue
            listed.add((nconst, role))
            self.add_credit(wid, nconst, role, ordering, chars, "archive" if category.startswith("archive") else None, names, existing)
        crew = self.st.execute("SELECT directors, writers FROM crew WHERE tconst = ?", (tconst,)).fetchone()
        if crew:
            for field_, role in ((crew[0], "director"), (crew[1], "writer")):
                for nconst in L.split_ids(field_):
                    if (nconst, role) not in listed:
                        self.add_credit(wid, nconst, role, None, None, None, names, existing)

    def add_credit(self, wid, nconst, role, ordering, chars, note, names, existing) -> None:
        pid = self.person_for(nconst, names)
        if pid is None:
            return
        character = " / ".join(L.parse_characters(chars)) or None
        key = (wid, pid, role, character or "")
        if key in self.credit_seen:
            return
        if nconst in self.unattached_nconst:
            self.counts["credits_recovered_through_new_person"] += 1
        self.credit_seen.add(key)
        self.db.execute("INSERT INTO credit (work_id, person_id, role, character_name, billing_order, credit_note, source_id, source_ref) VALUES (?,?,?,?,?,?,?,?)",
                        (wid, pid, role, character, ordering, note, self.src_imdb, nconst))
        self.counts["credits_added_to_new_works"] += 1
        info = names.get(nconst)
        if info and info[1]:
            for other in existing.get((normalize_name(info[0]), info[1]), []):
                if other != pid:
                    self.candidate(other, "imdb_name", nconst, "name_and_birth_year_only", f"same name and birth year as new person {pid}")

    # ----------------------------------------------------------------------------------------- 8. finish
    def canonical_problems(self) -> list[str]:
        """The merge map must be a plain 1-level map of persons: no chains, no self-reference, no non-person, every id of a merged person still present."""
        c = self.db
        out = []
        n = c.execute("SELECT COUNT(*) FROM entity_canonical m JOIN entity_canonical t ON t.entity_id = m.canonical_entity_id").fetchone()[0]
        if n:
            out.append(f"{n} canonical chains")
        n = c.execute("SELECT COUNT(*) FROM entity_canonical m LEFT JOIN person p ON p.person_id = m.entity_id LEFT JOIN person q ON q.person_id = m.canonical_entity_id "
                      "WHERE p.person_id IS NULL OR q.person_id IS NULL").fetchone()[0]
        if n:
            out.append(f"{n} canonical rows that are not person-to-person")
        n = c.execute("SELECT COUNT(*) FROM (SELECT scheme, value FROM external_id GROUP BY scheme, value HAVING COUNT(*) > 1)").fetchone()[0]
        if n:
            out.append(f"{n} duplicated external ids")
        n = c.execute("SELECT COUNT(*) FROM (SELECT entity_id FROM external_id WHERE scheme = 'imdb_title' GROUP BY entity_id HAVING SUM(is_primary) <> 1)").fetchone()[0]
        if n:
            out.append(f"{n} works whose imdb_title ids do not have exactly one primary")
        return out

    def finish(self, out_tmp: Path) -> dict:
        c = self.db
        film_src = self.src_film
        c.execute("INSERT OR IGNORE INTO work_status (work_id, entry_route, identification, plot_status, completeness) "
                  "SELECT work_id, 'catalogue', 'catalogue', CASE WHEN source_id = ? THEN 'with_plot' END, 'skeleton' FROM work", (film_src,))
        c.execute("""UPDATE work_status SET completeness = CASE
              WHEN EXISTS (SELECT 1 FROM credit x WHERE x.work_id = work_status.work_id AND x.role = 'director')
               AND EXISTS (SELECT 1 FROM credit x WHERE x.work_id = work_status.work_id AND x.role = 'cast')
               AND EXISTS (SELECT 1 FROM work_genre g WHERE g.work_id = work_status.work_id)
               AND EXISTS (SELECT 1 FROM work w WHERE w.work_id = work_status.work_id AND w.runtime_min IS NOT NULL) THEN 'rich'
              WHEN EXISTS (SELECT 1 FROM credit x WHERE x.work_id = work_status.work_id AND x.role IN ('director','cast'))
                OR EXISTS (SELECT 1 FROM work_genre g WHERE g.work_id = work_status.work_id)
                OR EXISTS (SELECT 1 FROM work_country g WHERE g.work_id = work_status.work_id)
                OR EXISTS (SELECT 1 FROM work w WHERE w.work_id = work_status.work_id AND w.runtime_min IS NOT NULL) THEN 'basic'
              ELSE 'skeleton' END""")
        for survivor, merged, nconst, evidence in sorted(self.merges):
            c.execute("INSERT INTO entity_canonical VALUES (?,?,?,?,?)", (merged, survivor, "same_person_confirmed_by_imdb_id_and_consistent_dates", evidence, self.src_imdb))
        for name, ddl in V3.VIEWS_V3.items():
            c.execute(f"DROP VIEW {name}")
            c.execute(ddl)
        for ddl in V3.NEW_VIEWS_V3.values():
            c.execute(ddl)
        if self.inp.movielens_layer:
            for ddl in V3.VIEWS_ML.values():
                c.execute(ddl)
        S2.rebuild_fts(c)
        c.execute("ANALYZE")
        c.commit()
        c.execute("PRAGMA foreign_keys = ON")
        fk = c.execute("PRAGMA foreign_key_check").fetchall()
        integrity = c.execute("PRAGMA integrity_check").fetchone()[0]
        problems = S2.check_fts(c) + invariants(c) + self.canonical_problems() + (ML.check(c) if self.inp.movielens_layer else [])
        if fk or integrity != "ok" or problems:
            raise RuntimeError(f"v3 layer failed its own checks: foreign keys {fk[:5]}, integrity {integrity}, other {problems[:5]}")
        digest = content_digest(c)
        base = dict(sqlite3.connect(f"file:{self.inp.base}?mode=ro&immutable=1", uri=True).execute("SELECT key, value FROM build_info").fetchall())
        info = {"schema_version": str(V3.SCHEMA_VERSION_ML if self.inp.movielens_layer else V3.SCHEMA_VERSION_V3), "builder": BUILDER_ML if self.inp.movielens_layer else BUILDER, "layer_base_content_sha256": base.get("content_sha256", ""), "content_sha256": digest,
                "imdb_manifest_sha256": _sha(self.inp.imdb_manifest), "imdb_staging_sha256": _sha(self.inp.staging) if self.inp.staging.stat().st_size < 2_000_000_000 else "skipped",
                "layer_entry_rule": "movielens+itwiki identified; types movie/short/tvShort/tvMovie/tvSpecial; no adult; no year-less; no same-title-year duplicates unless proven distinct (reconcile_rules.release_class)"}
        for k, v in info.items():
            c.execute("INSERT OR REPLACE INTO build_info VALUES (?,?)", (k, v))
        c.commit()
        c.close()
        return {"content_sha256": digest, "counts": dict(sorted(self.counts.items())), "people_matching": {k: v for k, v in self.people_summary.items() if k in ("credits_matched_to_an_imdb_person", "persons_resolved_by_tier", "persons_unresolved")},
                "separate_archives": {k: len(v) for k, v in sorted(self.separate.items())}}


def run_layer(inputs: LayerInputs, out: Path, *, force: bool = False, log=print, select_only: bool = False) -> dict:
    out = Path(out)
    if out.exists() and not force:
        raise FileExistsError(f"{out} exists; pass force=True (the old file is kept as {out.name}.previous)")
    tmp = out.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    sep = out.parent / f"{out.stem}.separate"
    t0 = time.time()
    L_ = Layer(inputs, tmp, sep)
    L_.setup()
    steps = [("recover identifiers", L_.recover_identifiers), ("primary imdb ids", L_.choose_primary_imdb), ("match people", L_.match_people)]
    for name, fn in steps:
        fn()
        log(f"[{name}] {time.time() - t0:.0f}s")
    for w, tconst in sorted(L_.primary_tconst.items()):  # type/year/runtime priority: the PRIMARY id of every existing work with an IMDb id
        L_.apply_priority(w, tconst)
    for tconst, w in sorted(L_.imdb_alias.items()):  # a secondary id never feeds the work: what IMDb says about it is kept as claims
        L_.alias_claims(w, tconst)
    log(f"[priority] {time.time() - t0:.0f}s")
    L_.db.commit()
    selected = L_.select_new_works()
    log(f"[select new works] {len(selected)} {time.time() - t0:.0f}s")
    if select_only:  # dry run: which titles would enter or stay held. Writes only the archives next to `out`; no database is produced.
        sep.mkdir(parents=True, exist_ok=True)
        for name, rows in L_.separate.items():
            util.write_jsonl(sep / f"{name}.jsonl", rows)
        L_.db.close()
        tmp.unlink(missing_ok=True)
        util.write_json(sep / "dry_run_counts.json", {"selected": len(selected), "counts": dict(sorted(L_.counts.items()))})
        return {"selected": len(selected), "counts": dict(L_.counts)}
    L_.insert_new_works(selected)
    log(f"[insert new works] {time.time() - t0:.0f}s")
    L_.match_episodes()
    L_.import_episodes()
    log(f"[episodes] {time.time() - t0:.0f}s")
    L_.add_ratings()
    L_.db.commit()
    log(f"[ratings] {time.time() - t0:.0f}s")
    report = L_.finish(tmp)
    sep.mkdir(parents=True, exist_ok=True)
    for name, rows in L_.separate.items():
        util.write_jsonl(sep / f"{name}.jsonl", rows)
    if out.exists():
        out.replace(out.with_name(out.name + ".previous"))
    tmp.replace(out)
    report["seconds"] = round(time.time() - t0)
    report["bytes"] = out.stat().st_size
    util.write_json(out.parent / f"{out.stem}.layer_report.json", {k: v for k, v in report.items() if k != "seconds"})
    log(f"v3 built: {out} ({report['bytes']} bytes, {report['seconds']}s)")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "cinema_db/data/cinema.v3.sqlite3")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--select-only", action="store_true", help="dry run up to the choice of new works; writes only the JSONL archives")
    ap.add_argument("--movielens", action="store_true", help="schema 4: add every MovieLens film, genre and tag (default: the schema-3 file)")
    args = ap.parse_args(argv)
    run_layer(LayerInputs(movielens_layer=args.movielens), args.out, force=args.force, select_only=args.select_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
