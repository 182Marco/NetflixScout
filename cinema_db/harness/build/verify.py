"""Verification of a built cinema database against its sources: integrity, coverage, quality, gaps, real queries.

    python -m cinema_db.harness.build.verify                       # reads the database read-only; writes docs/cinema_db/BUILD_REPORT.md/.json
    python -m cinema_db.harness.build.verify --reproduce           # also rebuilds into a temp folder and compares the content digest

Everything is recomputed independently of the builder: the spot check re-derives the expected values of a random sample of films
directly from the catalogue and the snapshot, and the coverage numbers come from SQL on the finished file.
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import tempfile
import time
from pathlib import Path
from typing import Any

from cinema_db.harness.build import sources as S
from cinema_db.harness.build.build import Inputs, content_digest, invariants, jsonl, run_build
from cinema_db.harness.build.common import normalize_name
from cinema_db.harness.build.snapshot import Snapshot
from cinema_db.schema import check_fts
from tool.cinema_db.approved_views import POLICY
from tool.cinema_db.connection import open_database
from tool.cinema_db.executor import execute
from tool.cinema_db.validator import validate

ROOT = S.ROOT
OUT_JSON = ROOT / "docs/cinema_db/BUILD_REPORT.json"
OUT_MD = ROOT / "docs/cinema_db/BUILD_REPORT.md"


def one(conn: sqlite3.Connection, sql: str, *p: Any) -> Any:
    return conn.execute(sql, p).fetchone()[0]


def integrity(conn: sqlite3.Connection, db: Path) -> dict[str, Any]:
    out = {
        "foreign_key_check_rows": len(conn.execute("PRAGMA foreign_key_check").fetchall()), "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
        "fts_problems": check_fts_readonly(conn), "invariant_problems": invariants(conn), "triggers": one(conn, "SELECT count(*) FROM sqlite_master WHERE type='trigger'"),
        "content_sha256_stored": one(conn, "SELECT value FROM build_info WHERE key='content_sha256'"),
    }
    out["content_sha256_recomputed"] = content_digest(conn)
    out["content_digest_matches"] = out["content_sha256_stored"] == out["content_sha256_recomputed"]
    open_database(db, POLICY).close()  # the approved-view policy accepts this very file
    out["policy_accepts_the_file"] = True
    return out


def check_fts_readonly(conn: sqlite3.Connection) -> list[str]:
    names = one(conn, "SELECT count(*) FROM entity_name")
    indexed = one(conn, "SELECT count(*) FROM entity_name_fts_docsize")
    return [] if names == indexed else [f"fts has {indexed} rows, entity_name {names}"]


def counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'entity_name_fts_%' ORDER BY name")]
    return {t: one(conn, f'SELECT count(*) FROM "{t}"') for t in tables}


def coverage(conn: sqlite3.Connection) -> dict[str, Any]:
    films = one(conn, "SELECT count(*) FROM work WHERE source_id = (SELECT source_id FROM source WHERE name='film-catalog-v3') AND kind IN ('film','short','tv_film','other') AND parent_work_id IS NULL")
    c: dict[str, Any] = {"film_catalog_works": films}

    def pct(n: int, d: int) -> str:
        return f"{n:,} ({100 * n / d:.1f}%)" if d else f"{n:,}"

    film_where = "w.source_id = (SELECT source_id FROM source WHERE name='film-catalog-v3')"
    for label, sql in {
        "with_year": f"SELECT count(*) FROM work w WHERE {film_where} AND release_year IS NOT NULL",
        "with_release_date": f"SELECT count(*) FROM work w WHERE {film_where} AND release_date IS NOT NULL",
        "with_runtime": f"SELECT count(*) FROM work w WHERE {film_where} AND runtime_min IS NOT NULL",
        "with_original_title": f"SELECT count(DISTINCT n.entity_id) FROM entity_name n JOIN work w ON w.work_id = n.entity_id WHERE {film_where} AND n.kind = 'original'",
        "with_imdb": f"SELECT count(DISTINCT x.entity_id) FROM external_id x JOIN work w ON w.work_id = x.entity_id WHERE {film_where} AND x.scheme = 'imdb_title'",
        "with_tmdb": f"SELECT count(DISTINCT x.entity_id) FROM external_id x JOIN work w ON w.work_id = x.entity_id WHERE {film_where} AND x.scheme IN ('tmdb_movie','tmdb_tv')",
        "with_eidr": f"SELECT count(DISTINCT x.entity_id) FROM external_id x JOIN work w ON w.work_id = x.entity_id WHERE {film_where} AND x.scheme = 'eidr'",
        "with_wikidata_id": f"SELECT count(DISTINCT x.entity_id) FROM external_id x JOIN work w ON w.work_id = x.entity_id WHERE {film_where} AND x.scheme = 'wikidata'",
        "with_director": f"SELECT count(DISTINCT c.work_id) FROM credit c JOIN work w ON w.work_id = c.work_id WHERE {film_where} AND c.role = 'director'",
        "with_cast": f"SELECT count(DISTINCT c.work_id) FROM credit c JOIN work w ON w.work_id = c.work_id WHERE {film_where} AND c.role = 'cast'",
        "with_genre_label": f"SELECT count(DISTINCT g.work_id) FROM work_genre g JOIN work w ON w.work_id = g.work_id WHERE {film_where}",
        "with_canonical_genre": f"SELECT count(DISTINCT g.work_id) FROM v_work_genre g JOIN work w ON w.work_id = g.work_id WHERE {film_where}",
        "with_country": f"SELECT count(DISTINCT g.work_id) FROM work_country g JOIN work w ON w.work_id = g.work_id WHERE {film_where}",
        "with_language": f"SELECT count(DISTINCT g.work_id) FROM work_language g JOIN work w ON w.work_id = g.work_id WHERE {film_where}",
        "with_company": f"SELECT count(DISTINCT g.work_id) FROM work_company g JOIN work w ON w.work_id = g.work_id WHERE {film_where}",
        "with_franchise": f"SELECT count(DISTINCT g.work_id) FROM work_franchise g JOIN work w ON w.work_id = g.work_id WHERE {film_where}",
        "with_relation": f"SELECT count(DISTINCT r.work_id) FROM work_relation r JOIN work w ON w.work_id = r.work_id WHERE {film_where}",
        "with_release_by_country": f"SELECT count(DISTINCT r.work_id) FROM work_release r JOIN work w ON w.work_id = r.work_id WHERE {film_where}",
        "with_money": f"SELECT count(DISTINCT r.work_id) FROM work_financial r JOIN work w ON w.work_id = r.work_id WHERE {film_where}",
    }.items():
        n = one(conn, sql)
        c[label] = {"n": n, "pct_of_films": round(100 * n / films, 1) if films else None, "text": pct(n, films)}
    genre = conn.execute("SELECT count(*), sum(CASE WHEN EXISTS (SELECT 1 FROM genre_label_map m WHERE m.label_id = wg.label_id) THEN 1 ELSE 0 END) FROM work_genre wg").fetchone()
    c["genre_assertions"] = {"total": genre[0], "mapped": genre[1], "pct_mapped": round(100 * genre[1] / genre[0], 1) if genre[0] else None}
    lab = conn.execute("SELECT count(*), sum(CASE WHEN EXISTS (SELECT 1 FROM genre_label_map m WHERE m.label_id = l.label_id) THEN 1 ELSE 0 END) FROM genre_label l").fetchone()
    c["genre_labels"] = {"total": lab[0], "mapped": lab[1]}
    c["credits_by_role"] = dict(conn.execute("SELECT role, count(*) FROM credit GROUP BY role ORDER BY 2 DESC").fetchall())
    c["works_by_kind"] = dict(conn.execute("SELECT kind, count(*) FROM work GROUP BY kind ORDER BY 2 DESC").fetchall())
    c["relations_by_type"] = dict(conn.execute("SELECT relation, count(*) FROM work_relation GROUP BY relation").fetchall())
    c["names_by_kind"] = dict(conn.execute("SELECT kind, count(*) FROM entity_name GROUP BY kind ORDER BY 2 DESC").fetchall())
    c["ids_by_scheme"] = dict(conn.execute("SELECT scheme, count(*) FROM external_id GROUP BY scheme ORDER BY 2 DESC").fetchall())
    c["homonym_works_same_title_and_year"] = one(conn, "SELECT count(*) FROM (SELECT 1 FROM v_work WHERE year IS NOT NULL AND kind IN ('film','short','tv_film') GROUP BY title, year HAVING count(*) > 1)")
    c["homonym_titles_different_years"] = one(conn, "SELECT count(*) FROM (SELECT 1 FROM v_work WHERE kind IN ('film','short','tv_film') GROUP BY title HAVING count(DISTINCT year) > 1)")
    c["persons_with_birth_data"] = one(conn, "SELECT count(*) FROM person WHERE birth_year IS NOT NULL")
    c["countries_with_iso2"] = [one(conn, "SELECT count(*) FROM country WHERE iso2 IS NOT NULL"), one(conn, "SELECT count(*) FROM country")]
    c["series_works"] = {k: one(conn, "SELECT count(*) FROM work WHERE kind = ?", k) for k in ("series", "miniseries", "season", "episode")}
    c["episodes_with_number"] = one(conn, "SELECT count(*) FROM work WHERE kind='episode' AND episode_number IS NOT NULL")
    c["episodes_with_date"] = one(conn, "SELECT count(*) FROM work WHERE kind='episode' AND release_date IS NOT NULL")
    c["seasons_with_number"] = one(conn, "SELECT count(*) FROM work WHERE kind='season' AND season_number IS NOT NULL")
    return c


def spot_check(conn: sqlite3.Connection, sample: int = 400, seed: int = 20261105) -> dict[str, Any]:
    """Re-derive the expected values of a random sample of films straight from the catalogue and the snapshot, then compare."""
    catalog = {r["film_id"]: r for r in jsonl(S.FILM_CATALOG)}
    rng = random.Random(seed)
    ids = sorted(k for k, r in catalog.items() if r.get("wikidata_id"))
    chosen = rng.sample(ids, min(sample, len(ids)))
    snap = Snapshot(S.FILM_SNAPSHOT)
    labels = snap.labels()
    wanted = set(chosen)
    entities = {q: e for q, e in snap.entities() if q in wanted}
    problems: list[dict[str, Any]] = []
    checked = {"title": 0, "year": 0, "runtime": 0, "imdb": 0, "directors": 0, "wikidata_id": 0, "countries": 0}
    for fid in chosen:
        r, e = catalog[fid], entities.get(fid)
        row = conn.execute("SELECT work_id, title, year, runtime_min, imdb_id, wikidata_id FROM v_work WHERE wikidata_id = ?", (fid,)).fetchone()
        if row is None:
            problems.append({"film": fid, "problem": "missing from the database"})
            continue
        wid, title, year, runtime, imdb, qid = row
        expect_title = (e or {}).get("labels", {}).get("it", {}).get("value") or r["title"]
        checked["title"] += 1
        if title != expect_title:
            problems.append({"film": fid, "field": "title", "db": title, "expected": expect_title})
        checked["year"] += 1
        if year != r.get("year"):
            problems.append({"film": fid, "field": "year", "db": year, "expected": r.get("year")})
        checked["runtime"] += 1
        if r.get("duration_minutes") and runtime != r["duration_minutes"]:
            problems.append({"film": fid, "field": "runtime", "db": runtime, "expected": r["duration_minutes"]})
        checked["imdb"] += 1
        if r.get("imdb_id") and imdb != r["imdb_id"]:
            problems.append({"film": fid, "field": "imdb", "db": imdb, "expected": r["imdb_id"]})
        checked["wikidata_id"] += 1
        if qid != fid:
            problems.append({"film": fid, "field": "wikidata_id", "db": qid})
        # directors: every director the catalogue names (with a Wikidata id) must be a director credit of this work
        want = {normalize_name(p["name"]) for p in (r.get("director") or []) if p.get("wikidata_id") and p.get("name")}
        got = {normalize_name(n) for (n,) in conn.execute("SELECT person_name FROM v_credit WHERE work_id = ? AND role = 'director'", (wid,))}
        checked["directors"] += 1
        if want and not want <= got:
            problems.append({"film": fid, "field": "directors", "db": sorted(got), "expected_at_least": sorted(want)})
        # countries: the P495 items of the snapshot that have a label
        if e:
            from cinema_db.harness.build.extract import items as _items

            want_c = {(labels.get(q, {}).get("en") or labels.get(q, {}).get("it")) for q in _items(e, "P495") if labels.get(q)}
            got_c = {n for (n,) in conn.execute("SELECT country FROM v_work_country WHERE work_id = ? AND role = 'origin'", (wid,))}
            checked["countries"] += 1
            if want_c != got_c:
                problems.append({"film": fid, "field": "countries", "db": sorted(got_c), "expected": sorted(x for x in want_c if x)})
    return {"sampled": len(chosen), "seed": seed, "fields_checked": checked, "mismatches": len(problems), "samples": problems[:20]}


QUERIES: list[tuple[str, str, list[Any]]] = [
    ("film diretti da una persona (nome esatto)", "SELECT work_title, work_year FROM v_credit WHERE person_name = ? AND role = 'director' ORDER BY work_year", ["Federico Fellini"]),
    ("film in cui recita una persona", "SELECT work_title, work_year, character_name FROM v_credit WHERE person_name = ? AND role = 'cast' ORDER BY work_year LIMIT 10", ["Monica Vitti"]),
    ("collaborazioni: film con regista A e attore B", "SELECT d.work_title, d.work_year FROM v_credit d JOIN v_credit a ON a.work_id = d.work_id WHERE d.person_name = ? AND d.role = 'director' AND a.person_name = ? AND a.role = 'cast' ORDER BY d.work_year", ["Federico Fellini", "Marcello Mastroianni"]),
    ("registi con più film nel catalogo", "SELECT person_name, count(*) AS n FROM v_credit WHERE role = 'director' AND work_kind = 'film' GROUP BY person_id ORDER BY n DESC LIMIT 10", []),
    ("ricerca testuale di un titolo (FTS)", "SELECT entity_id, name, work_year FROM v_title_search WHERE search MATCH ? AND entity_type = 'work' ORDER BY rank LIMIT 10", ["padrino"]),
    ("ricerca per alias in inglese", "SELECT entity_id, name, name_kind FROM v_title_search WHERE search MATCH ? ORDER BY rank LIMIT 10", ["\"the godfather\""]),
    ("ricerca esatta per ID IMDb", "SELECT work_id, title, year FROM v_work WHERE imdb_id = ?", ["tt0068646"]),
    ("tratto da / basato su", "SELECT work_title, related_title, related_kind FROM v_work_relation WHERE relation = 'based_on' AND direction = 'forward' AND work_title = ? ", ["Il nome della rosa"]),
    ("seguiti e precedenti in una serie di film", "SELECT work_title, relation_label, related_title FROM v_work_relation WHERE relation = 'follows' AND work_title = ?", ["Il padrino - Parte II"]),
    ("film di un franchise in ordine", "SELECT work_title, work_year FROM v_franchise WHERE franchise = ? ORDER BY work_year LIMIT 15", ["Star Wars"]),
    ("film per genere canonico e paese", "SELECT w.title, w.year FROM v_work w JOIN v_work_genre g ON g.work_id = w.work_id JOIN v_work_country c ON c.work_id = w.work_id WHERE g.genre_code = ? AND c.country = ? AND c.role = 'origin' AND w.kind = 'film' ORDER BY w.year LIMIT 10", ["horror", "Italy"]),
    ("film più lunghi", "SELECT title, year, runtime_min FROM v_work WHERE kind = 'film' ORDER BY runtime_min DESC LIMIT 5", []),
    ("episodi di una stagione", "SELECT e.title, e.episode_number, e.release_date FROM v_work e JOIN v_work s ON s.work_id = e.parent_work_id JOIN v_work p ON p.work_id = s.parent_work_id WHERE p.title = ? AND s.season_number = 1 AND e.kind = 'episode' ORDER BY e.episode_number LIMIT 12", ["Breaking Bad"]),
    ("conteggio film per decennio", "SELECT (year / 10) * 10 AS decade, count(*) FROM v_work WHERE kind = 'film' AND year IS NOT NULL GROUP BY decade ORDER BY decade", []),
    ("incassi dichiarati (USD)", "SELECT work_title, amount, scope FROM v_work_financial WHERE kind = 'box_office' AND currency = 'USD' ORDER BY amount DESC LIMIT 5", []),
    ("termini d'uso delle fonti", "SELECT name, license, usage_scope, attribution_required FROM v_source", []),
]


def run_queries(db: Path) -> list[dict[str, Any]]:
    g = open_database(db, POLICY)
    out = []
    try:
        for label, sql, params in QUERIES:
            t = time.perf_counter()
            try:
                res = execute(g, validate(sql, params, POLICY))
                out.append({"label": label, "ms": round((time.perf_counter() - t) * 1000, 1), "rows": len(res.rows), "truncated": res.truncated, "sample": [list(r) for r in res.rows[:3]]})
            except Exception as exc:  # a refused or failing query is a finding, not a crash
                out.append({"label": label, "error": f"{type(exc).__name__}: {getattr(exc, 'code', '')}", "ms": round((time.perf_counter() - t) * 1000, 1)})
    finally:
        g.close()
    return out


def verify(db: Path, *, reproduce: bool = False, log=print) -> dict[str, Any]:
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        report: dict[str, Any] = {"database": str(db.relative_to(ROOT)) if db.is_relative_to(ROOT) else str(db), "bytes": db.stat().st_size}
        log("integrity …")
        report["integrity"] = integrity(conn, db)
        report["counts"] = counts(conn)
        log("coverage …")
        report["coverage"] = coverage(conn)
        log("spot check …")
        report["spot_check"] = spot_check(conn)
    finally:
        conn.close()
    log("queries …")
    report["queries"] = run_queries(db)
    build_report = db.with_name(db.stem + ".build_report.json")
    if build_report.is_file():
        br = json.loads(build_report.read_text(encoding="utf-8"))
        report["build"] = {"seconds": br["seconds"], "counts": br["counts"], "skipped": br["skipped"], "samples": br["samples"], "inputs": br["inputs"]}
    if reproduce:
        log("reproducing (a full second build) …")
        with tempfile.TemporaryDirectory() as tmp:
            uses_phase4 = sqlite3.connect(f"file:{db}?mode=ro", uri=True).execute("SELECT count(*) FROM build_info WHERE key='phase4_snapshot_index_sha256'").fetchone()[0]
            again = run_build(Path(tmp) / "again.sqlite3", Inputs(phase4=S.PHASE4_SNAPSHOT if uses_phase4 else None), log=lambda *_: None)
        report["reproducible"] = {"first": report["integrity"]["content_sha256_stored"], "second": again["content_sha256"], "identical": again["content_sha256"] == report["integrity"]["content_sha256_stored"], "second_build_seconds": again["seconds"]}
    return report


def markdown(r: dict[str, Any], survey: dict[str, Any] | None) -> str:
    c, i = r["coverage"], r["integrity"]
    L = ["# Rapporto della prima build offline (fase 3)", "",
         "Generato da `python -m cinema_db.harness.build.verify` sul file reale, in sola lettura. Nessuna rete, nessun credito. Le fonti sono quelle locali (snapshot Wikidata di film e serie, catalogo film v3, catalogo serie s5), non modificate.", "",
         "## 1. Integrità", "",
         f"- File: **{r['bytes'] / 1e6:,.0f} MB**; build in {r.get('build', {}).get('seconds', '?')} s.",
         f"- `foreign_key_check`: {i['foreign_key_check_rows']} righe; `integrity_check`: {i['integrity_check']}; indice FTS5: {'coerente' if not i['fts_problems'] else i['fts_problems']}; regole (un solo nome primario per entità): {'rispettate' if not i['invariant_problems'] else i['invariant_problems']}; trigger: {i['triggers']}.",
         f"- Digest del contenuto ricalcolato = memorizzato: **{i['content_digest_matches']}** (`{i['content_sha256_stored'][:16]}…`). La policy delle viste approvate accetta il file: **{i['policy_accepts_the_file']}**."]
    if "reproducible" in r:
        rep = r["reproducible"]
        L.append(f"- Riproducibilità: una seconda build completa ({rep['second_build_seconds']} s) dà lo stesso digest: **{rep['identical']}**.")
    L += ["", "## 2. Righe per tabella", "", "| Tabella | Righe |", "|---|---|"] + [f"| {t} | {n:,} |" for t, n in r["counts"].items() if n]
    L += ["", "## 3. Copertura dei film importati", "", f"Film, cortometraggi e film TV del catalogo importati: **{c['film_catalog_works']:,}**.", "", "| Campo | Film | % |", "|---|---|---|"]
    for k in ("with_year", "with_release_date", "with_runtime", "with_original_title", "with_imdb", "with_tmdb", "with_eidr", "with_wikidata_id", "with_director", "with_cast", "with_genre_label", "with_canonical_genre", "with_country", "with_language", "with_company", "with_franchise", "with_relation", "with_release_by_country", "with_money"):
        L.append(f"| {k} | {c[k]['n']:,} | {c[k]['pct_of_films']} |")
    ga = c["genre_assertions"]
    L += ["", f"Generi: {c['genre_labels']['total']:,} etichette originali, {c['genre_labels']['mapped']:,} mappate; asserzioni etichetta→opera mappate **{ga['pct_mapped']}%** ({ga['mapped']:,} su {ga['total']:,}). Le etichette non mappate restano leggibili in `v_work_genre_label`.", "",
          "Tipi di opera: " + ", ".join(f"{k} {v:,}" for k, v in c["works_by_kind"].items()) + ".", "",
          "Crediti: " + ", ".join(f"{k} {v:,}" for k, v in c["credits_by_role"].items()) + ".", "",
          "Relazioni: " + ", ".join(f"{k} {v:,}" for k, v in c["relations_by_type"].items()) + ".", "",
          "Nomi: " + ", ".join(f"{k} {v:,}" for k, v in c["names_by_kind"].items()) + ".", "",
          "Identificativi: " + ", ".join(f"{k} {v:,}" for k, v in c["ids_by_scheme"].items()) + ".", "",
          f"Omonimie: {c['homonym_works_same_title_and_year']:,} coppie titolo+anno ripetute (opere diverse o duplicati da esaminare), {c['homonym_titles_different_years']:,} titoli usati da film di anni diversi.", "",
          "## 4. Serie, stagioni, episodi", "", "Importate: " + ", ".join(f"{k} {v:,}" for k, v in c["series_works"].items()) + f"; episodi con numero {c['episodes_with_number']:,}, con data {c['episodes_with_date']:,}; stagioni con numero {c['seasons_with_number']:,}.", "",
          "## 5. Verifica a campione indipendente", "",
          f"{r['spot_check']['sampled']} film estratti a caso (seme {r['spot_check']['seed']}); per ognuno si sono ricalcolati dal catalogo e dallo snapshot titolo, anno, durata, ID IMDb, ID Wikidata, registi e paesi, e confrontati con il database. **Differenze: {r['spot_check']['mismatches']}.**"]
    for p in r["spot_check"]["samples"][:10]:
        L.append(f"- {p}")
    L += ["", "## 6. Cosa non è stato importato e perché (lacune per la fase 4)", ""]
    sk = r.get("build", {}).get("skipped", {})
    names = {
        "credit_unnamed_person": "Crediti il cui nome non è nei file locali (solo il QID)", "company_without_name": "Società senza nome", "franchise_without_name": "Franchise senza nome",
        "relation_target_without_label": "Relazioni verso opere senza etichetta", "genre_without_label": "Generi senza etichetta", "country_without_label": "Paesi senza etichetta",
        "language_without_label": "Lingue senza etichetta", "release_place_not_a_known_country": "Date di uscita con un luogo che non è un paese noto", "money_unit_not_imported": "Importi in valute diverse da USD (codice ISO non verificabile offline)",
    }
    L += ["| Motivo | Occorrenze |", "|---|---|"]
    grouped: dict[str, int] = {}
    for k, v in sk.items():
        grouped[k.split(":")[0]] = grouped.get(k.split(":")[0], 0) + v
    for k, v in sorted(grouped.items(), key=lambda kv: -kv[1]):
        L.append(f"| {names.get(k, k)} | {v:,} |")
    cnt = r.get("build", {}).get("counts", {})
    L += ["", f"Premi e candidature non importati (servono i nomi dei premi): **{cnt.get('award_statements_not_imported', 0):,}** asserzioni. Persone importate: senza date di vita ({c['persons_with_birth_data']} con anno di nascita) né paese di nascita; paesi con codice ISO: {c['countries_with_iso2'][0]} su {c['countries_with_iso2'][1]} (i codici ISO non si deducono a memoria).", ""]
    if survey:
        est = survey["phase4_estimate"]
        L += ["Stima delle richieste della fase 4 (da `SURVEY.md`, 50 id per richiesta; **stima**, nulla è stato richiesto): persone senza nome " + f"{est['persons_without_name']['requests']:,}, premi e cerimonie {est['award_and_ceremony_items']['requests']:,}, valute {est['currency_units']['requests']:,}, bersagli di relazioni {est['relation_targets_without_label']['requests']:,}, società {est['companies_without_name']['requests']:,}, franchise {est['franchises_without_name']['requests']:,}; tutto, comprese le date di vita di ogni persona: {est['_total_requests_if_everything']:,}.", ""]
    L += ["## 7. Interrogazioni reali attraverso il validatore e l'authorizer", "", "| Domanda | Righe | ms | Esempio |", "|---|---|---|---|"]
    for q in r["queries"]:
        if "error" in q:
            L.append(f"| {q['label']} | **{q['error']}** | {q['ms']} | |")
        else:
            L.append(f"| {q['label']} | {q['rows']}{'+' if q['truncated'] else ''} | {q['ms']} | {str(q['sample'][:1])[:90]} |")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=S.DEFAULT_DB)
    ap.add_argument("--reproduce", action="store_true")
    ap.add_argument("--report-name", default="BUILD_REPORT", help="basename of the report written in docs/cinema_db (the phase-3 report keeps its name)")
    args = ap.parse_args(argv)
    out_json, out_md = ROOT / "docs/cinema_db" / f"{args.report_name}.json", ROOT / "docs/cinema_db" / f"{args.report_name}.md"
    report = verify(args.db, reproduce=args.reproduce)
    survey = json.loads((ROOT / "docs/cinema_db/SURVEY.json").read_text(encoding="utf-8")) if (ROOT / "docs/cinema_db/SURVEY.json").is_file() else None
    out_json.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    out_md.write_text(markdown(report, survey), encoding="utf-8")
    print(f"wrote {out_json.relative_to(ROOT)} and {out_md.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
