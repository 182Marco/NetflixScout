"""Benchmark of the `cinema_sql` tool on the real local database. Offline, free, no network, no LLM.

    python -m cinema_db.harness.tool_eval.run_benchmark            # writes docs/cinema_db/PHASE5_BENCHMARK.json and .md

For every question of `questions.py` it runs the planned steps through the tool, measures the SQL statements and the wall time (median of
5 runs), and checks the result against independent SQL on the BASE TABLES (not the views the tool reads, not the guard). Then it compares
the 30 baseline questions with `docs/cinema_db/baseline.json`: what could be answered locally in theory, what was verified, and the HTTP
requests that would really be avoided. The planner is not run: plans are written by hand, so which plan a real planner writes is NOT measured.
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import time
from pathlib import Path
from typing import Any

from cinema_db.harness.tool_eval.questions import QUESTIONS, Question, Step
from tool.cinema_db.config import CinemaDbConfig
from tool.cinema_db.tool import CinemaSqlTool

ROOT = Path(__file__).resolve().parents[3]
DB = ROOT / "cinema_db/data/cinema.sqlite3"
BASELINE = ROOT / "docs/cinema_db/baseline.json"
OUT_JSON = ROOT / "docs/cinema_db/PHASE5_BENCHMARK.json"
OUT_MD = ROOT / "docs/cinema_db/PHASE5_BENCHMARK.md"
RUNS = 5
SCREEN = ("film", "short", "tv_film", "series", "miniseries")
FILM = ("film", "short", "tv_film")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


# ---- independent verification: base tables only ----------------------------------------------------------------------------------------
def verify(raw: sqlite3.Connection, args: dict[str, Any], m: dict[str, Any]) -> list[str]:
    """Discrepancies between the tool's answer and a recomputation from the base tables (empty = the answer matches the database)."""
    problems: list[str] = []
    op, status = args["operation"], m["status"]
    subject = m.get("subject") or {}
    one = lambda sql, *p: raw.execute(sql, p).fetchone()[0]  # noqa: E731
    if status != "ok":
        for c in m.get("candidates", []):
            if "work_id" in c and not one("SELECT count(*) FROM work WHERE work_id = ?", c["work_id"]):
                problems.append(f"candidate {c['work_id']} is not a work")
            if "person_id" in c and not one("SELECT count(*) FROM person WHERE person_id = ?", c["person_id"]):
                problems.append(f"candidate {c['person_id']} is not a person")
        return problems
    if op == "find_work" and subject.get("work_id"):
        wid = subject["work_id"]
        if one("SELECT release_year FROM work WHERE work_id = ?", wid) != subject.get("year"):
            problems.append("year differs")
        stored = raw.execute("SELECT value FROM external_id WHERE entity_id = ? AND scheme = 'imdb_title' AND is_primary = 1", (wid,)).fetchone()
        if (stored[0] if stored else None) != subject.get("imdb_id"):
            problems.append("imdb id differs")
        directors = {r[0] for r in raw.execute("SELECT n.name FROM credit c JOIN entity_name n ON n.entity_id = c.person_id AND n.is_primary = 1 WHERE c.work_id = ? AND c.role = 'director'", (wid,))}
        if not set(subject.get("directors", [])) <= directors:
            problems.append("directors differ")
    elif op == "find_person":
        stored = raw.execute("SELECT birth_year FROM person WHERE person_id = ?", (subject["person_id"],)).fetchone()
        if stored is None or stored[0] != subject.get("birth_year"):
            problems.append("birth year differs")
    elif op == "filmography":
        pid = subject["person_id"]
        role = f" AND c.role = '{args['role']}'" if args.get("role") else ""
        kinds = _in(FILM if args.get("type") == "film" else ("series", "miniseries") if args.get("type") == "series" else SCREEN)
        years = (f" AND w.release_year >= {int(args['year_from'])}" if args.get("year_from") else "") + (f" AND w.release_year <= {int(args['year_to'])}" if args.get("year_to") else "")
        expected = {r[0] for r in raw.execute(f"SELECT DISTINCT c.work_id FROM credit c JOIN work w ON w.work_id = c.work_id WHERE c.person_id = ?{role} AND w.kind IN ({kinds}){years}", (pid,))}
        if m["total"] != len(expected):
            problems.append(f"total {m['total']} != {len(expected)}")
        if not {w["work_id"] for w in m["works"]} <= expected:
            problems.append("lists a work the person has no such credit for")
        if len(expected) <= len(m["works"]) and {w["work_id"] for w in m["works"]} != expected:
            problems.append("misses works")
        imdb = {r[0]: r[1] for r in raw.execute("SELECT entity_id, value FROM external_id WHERE scheme = 'imdb_title' AND entity_id IN (%s)" % ",".join(str(w["work_id"]) for w in m["works"]))} if m["works"] else {}
        if any("imdb_id" in w and w["imdb_id"] != imdb.get(w["work_id"]) for w in m["works"]):
            problems.append("imdb id differs")
    elif op == "cast":
        n = one("SELECT count(*) FROM credit WHERE work_id = ? AND role = 'cast'", subject["work_id"])
        if m.get("total", 0) != n:
            problems.append(f"cast total {m.get('total')} != {n}")
    elif op == "crew":
        role = args.get("role")
        expected = {r[0] for r in raw.execute("SELECT n.name FROM credit c JOIN entity_name n ON n.entity_id = c.person_id AND n.is_primary = 1 WHERE c.work_id = ? AND c.role = ?", (subject["work_id"], role))}
        got = {p for g in m["crew"] for p in g["people"]}
        if got != expected:
            problems.append(f"crew {sorted(got)} != {sorted(expected)}")
    elif op == "collaborations":
        a = subject["person_id"]
        if m.get("second_person"):
            b = m["second_person"]["person_id"]
            ra = f" AND x.role = '{args['role']}'" if args.get("role") else ""
            rb = f" AND y.role = '{args['role_b']}'" if args.get("role_b") else ""
            expected = {r[0] for r in raw.execute(f"SELECT DISTINCT x.work_id FROM credit x JOIN credit y ON y.work_id = x.work_id JOIN work w ON w.work_id = x.work_id WHERE x.person_id = ? AND y.person_id = ?{ra}{rb} AND w.kind IN ({_in(SCREEN)})", (a, b))}
            if {w["work_id"] for w in m["shared_works"]} != expected:
                problems.append("shared works differ")
        elif m.get("collaborators"):
            top = m["collaborators"][0]
            ra = f" AND x.role = '{args['role']}'" if args.get("role") else ""
            rb = f" AND y.role = '{args['role_b']}'" if args.get("role_b") else ""
            n = one(f"SELECT count(DISTINCT x.work_id) FROM credit x JOIN credit y ON y.work_id = x.work_id JOIN work w ON w.work_id = x.work_id WHERE x.person_id = ? AND y.person_id = ?{ra}{rb} AND w.kind IN ({_in(SCREEN)})", a, top["person_id"])
            if n != top["works"]:
                problems.append(f"top collaborator count {top['works']} != {n}")
    elif op == "awards":
        key = "work_id" if subject.get("kind") not in (None, "person") and "work_id" in subject else "person_id" if "person_id" in subject else None
        if key:
            extra = (f" AND outcome = '{args['outcome']}'" if args.get("outcome") else "") + (f" AND ceremony_year >= {int(args['year_from'])}" if args.get("year_from") else "") + (
                f" AND ceremony_year <= {int(args['year_to'])}" if args.get("year_to") else "")
            expected = one(f"SELECT count(DISTINCT r.ceremony_id || '|' || r.category_id || '|' || r.outcome || '|' || coalesce(r.work_id, 0)) FROM award_result r JOIN ceremony c ON c.ceremony_id = r.ceremony_id WHERE r.{key} = ?{extra.replace('ceremony_year', 'c.year')}", subject[key])
            if m["total"] != expected:
                problems.append(f"awards total {m['total']} != {expected}")
        else:
            pattern = f"%{args['award'].casefold()}%"
            extra = (f" AND r.outcome = '{args['outcome']}'" if args.get("outcome") else "") + (f" AND c.year >= {int(args['year_from'])}" if args.get("year_from") else "") + (f" AND c.year <= {int(args['year_to'])}" if args.get("year_to") else "")
            expected = one(f"SELECT count(DISTINCT r.ceremony_id || '|' || r.category_id || '|' || r.outcome || '|' || coalesce(r.work_id, 0)) FROM award_result r JOIN ceremony c ON c.ceremony_id = r.ceremony_id JOIN award_category k ON k.category_id = r.category_id JOIN entity_name an ON an.entity_id = k.award_id AND an.is_primary = 1 WHERE (lower(an.name) LIKE ? OR lower(k.name) LIKE ?){extra}", pattern, pattern)
            if m["total"] != expected:
                problems.append(f"awards total {m['total']} != {expected}")
    elif op == "series":
        sid = subject["work_id"]
        if "seasons" in m:
            if len(m["seasons"]) != one("SELECT count(*) FROM work WHERE parent_work_id = ? AND kind = 'season'", sid):
                problems.append("season count differs")
            for s in m["seasons"]:
                n = one("SELECT count(*) FROM work e WHERE e.kind = 'episode' AND e.parent_work_id = (SELECT work_id FROM work WHERE parent_work_id = ? AND kind = 'season' AND season_number = ?)", sid, s["season_number"])
                if n != s["episodes"]:
                    problems.append(f"season {s['season_number']}: {s['episodes']} != {n}")
    elif op == "companies":
        if "companies" in m:
            expected = one("SELECT count(DISTINCT company_id || '-' || role) FROM work_company WHERE work_id = ?", subject["work_id"])
            if sum(len(g["companies"]) for g in m["companies"]) != min(expected, 25):
                problems.append("company count differs")
        else:
            expected = one("SELECT count(DISTINCT work_id) FROM work_company WHERE company_id = ?", subject["company_id"])
            if len(m["works"]) != min(expected, 25):
                problems.append("works of the company differ")
    elif op == "franchise":
        for f in m.get("franchises", []):
            ids = {r[0] for r in raw.execute("SELECT wf.work_id FROM work_franchise wf JOIN entity_name n ON n.entity_id = wf.franchise_id AND n.is_primary = 1 WHERE n.name = ?", (f["franchise"],))}
            listed = {x["work_id"] for x in f["members"]}
            if not listed <= ids or (not f["truncated"] and listed != ids):
                problems.append("franchise members differ")
    elif op == "relations":
        wid = subject["work_id"]
        expected = one("SELECT count(*) FROM work_relation WHERE work_id = ? OR related_work_id = ?", wid, wid)
        if len(m["relations"]) != min(expected, 25):
            problems.append(f"relations {len(m['relations'])} != {expected}")
    elif op == "work_card":
        wid = subject["work_id"]
        for role, key in (("writer", "writers"), ("composer", "composers")):
            expected = {r[0] for r in raw.execute("SELECT n.name FROM credit c JOIN entity_name n ON n.entity_id = c.person_id AND n.is_primary = 1 WHERE c.work_id = ? AND c.role = ?", (wid, role))}
            if set(m[key]) != expected:
                problems.append(f"{key} differ")
    elif op == "sql" and "rows" in m and args.get("params"):
        country, year = args["params"]
        n = one("SELECT count(DISTINCT w.work_id) FROM work w JOIN work_country wc ON wc.work_id = w.work_id JOIN country c ON c.country_id = wc.country_id WHERE c.iso2 = ? AND wc.role = 'origin' AND w.kind = 'film' AND w.release_year = ?", country, year)
        if m["rows"][0]["n"] != n:
            problems.append(f"sql count {m['rows'][0]['n']} != {n}")
    return problems


# ---- running ------------------------------------------------------------------------------------------------------------------------
def summarize(op: str, m: dict[str, Any]) -> str:
    s = m.get("subject") or {}
    who = s.get("title") or s.get("name") or ""
    if m["status"] != "ok":
        names = [f"{c.get('title') or c.get('name')} ({c.get('year') or c.get('birth_year')})" for c in m.get("candidates", [])]
        return f"{m['status']}" + (f" [{m.get('reason')}]" if m.get("reason") else "") + (": " + "; ".join(names) if names else "")
    if op in {"find_work"}:
        return f"{who} ({s.get('year')}), regia {', '.join(s.get('directors', []))}, imdb {s.get('imdb_id')}"
    if op == "find_person":
        return f"{who} ({s.get('birth_year')}) {s.get('credits_by_role')}"
    if op == "filmography":
        return f"{who}: {m['total']} opere, es. " + "; ".join(f"{w['title']} ({w['year']})" for w in m["works"][:5])
    if op == "cast":
        return f"{who}: {m['total']} nel cast, es. " + ", ".join(p["name"] for p in m["cast"][:4])
    if op == "crew":
        return f"{who}: " + "; ".join(f"{g['role']}: {', '.join(g['people'])}" for g in m["crew"])
    if op == "collaborations":
        if "shared_works" in m:
            return f"{who} + {m['second_person']['name']}: {len(m['shared_works'])} opere: " + "; ".join(f"{w['title']} ({w['year']})" for w in m["shared_works"])
        return f"{who}: " + "; ".join(f"{c['name']} ({c['works']})" for c in m["collaborators"])
    if op == "awards":
        return f"{who or 'per nome'}: {m['total']} risultati, es. " + "; ".join(f"{r['category']} {r['year']} {r['outcome']} {r['work_title']}" for r in m["results"][:3])
    if op == "series":
        if "seasons" in m:
            return f"{who}: {len(m['seasons'])} stagioni " + ", ".join(f"S{x['season_number']}={x['episodes']}/{x['numbered_episodes']}" for x in m["seasons"][:8])
        return f"{who} S{m['season']}: {len(m['episodes'])} episodi " + ", ".join(f"{e['episode_number']}:{e['title']}" for e in m["episodes"][:3])
    if op == "companies":
        return f"{who or s.get('name')}: " + "; ".join(f"{g['role']}: {', '.join(g['companies'])}" for g in m.get("companies", [])) if "companies" in m else f"{s.get('name')}: {len(m['works'])} opere"
    if op == "franchise":
        return "; ".join(f"{f['franchise']}: " + ", ".join(x["title"] for x in f["members"][:6]) for f in m["franchises"])
    if op == "relations":
        return f"{who}: " + "; ".join(f"{r['relation']} {r['title']} ({r['kind']})" for r in m["relations"])
    if op == "work_card":
        return f"{who}: scrittori {m['writers']}, musica {m['composers']}, generi {m['genres']}, paesi {m['countries']}"
    return json.dumps(m.get("rows", m), ensure_ascii=False)[:160]


def run_step(tool: CinemaSqlTool, arguments: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], float, int]:
    times = []
    result = None
    for _ in range(RUNS):
        started = time.perf_counter()
        result = tool.run(query="benchmark", params=dict(arguments))
        times.append((time.perf_counter() - started) * 1000)
    assert result is not None
    data = result["trace"][0]["data"] if result["trace"] else {"queries": [], "elapsed_ms": 0}
    return result, result["metadata"]["cinema_db"], statistics.median(times), len(data["queries"])


def evaluate(q: Question, tool: CinemaSqlTool, raw: sqlite3.Connection) -> dict[str, Any]:
    record: dict[str, Any] = {"key": q.key, "question": q.text, "baseline_no": q.baseline_no, "coverage": q.coverage, "reason": q.reason, "external": list(q.external), "manual": q.manual, "steps": [],
                              "expected_status": q.expect.get("status"), "settles_the_question": q.settles_the_question}
    if q.coverage == "none":
        record.update(verdict="not_applicable", queries=0, wall_ms=0.0, answer="— (non risponde il database locale)", problems=[])
        return record
    previous: dict[str, Any] | None = None
    problems: list[str] = []
    for index, step in enumerate(q.steps):
        arguments = dict(step.arguments)
        if step.pick is not None:
            candidates = (previous or {}).get("candidates", [])
            chosen = [c for c in candidates if all(c.get(k) == v for k, v in step.pick.items())]
            if len(chosen) != 1:
                problems.append("could not pick the intended candidate")
                break
            arguments["work_id"] = chosen[0]["work_id"]
        result, m, wall, n_queries = run_step(tool, arguments)
        found = verify(raw, arguments, m)
        problems += found
        record["steps"].append({"arguments": arguments, "status": m["status"], "reason": m.get("reason") or m.get("error"), "queries": n_queries, "sql_ms": sum(c["ms"] for c in result["trace"][0]["data"]["queries"]) if result["trace"] else 0,
                                "wall_ms": round(wall, 1), "answer": summarize(arguments["operation"], m), "problems": found,
                                "total": m.get("total"), "shown": m.get("shown"), "notes": [n["code"] for n in m.get("notes", [])]})
        previous = m
    final = record["steps"][-1] if record["steps"] else None
    problems += check_expectations(q, record, previous)
    record["queries"] = sum(s["queries"] for s in record["steps"])
    record["wall_ms"] = round(sum(s["wall_ms"] for s in record["steps"]), 1)
    record["answer"] = " → ".join(s["answer"] for s in record["steps"][-2:]) if len(record["steps"]) > 1 else (final["answer"] if final else "")
    record["problems"] = problems
    if problems:
        record["verdict"] = "incorrect"
    elif final and final["status"] == "ok":
        record["verdict"] = "needs_disambiguation" if record["steps"][0]["status"] == "ambiguous" and len(record["steps"]) > 1 else "correct"
    elif final and final["status"] in {"ambiguous", "not_found", "unverified", "empty"}:
        record["verdict"] = "honest_" + final["status"]
    else:
        record["verdict"] = "error"
    return record


def check_expectations(q: Question, record: dict[str, Any], m: dict[str, Any] | None) -> list[str]:
    e, out = q.expect, []
    if m is None:
        return ["no result"] if q.steps else []
    s = m.get("subject") or {}
    first = record["steps"][0] if record["steps"] else {}
    if e.get("first_ambiguous") and first.get("status") != "ambiguous":
        out.append("first step was expected to be ambiguous")
    if "status" in e and m["status"] != e["status"]:
        out.append(f"status {m['status']} != {e['status']}")
    if "min_candidates" in e and len(m.get("candidates", [])) < e["min_candidates"]:
        out.append("fewer alternatives than expected")
    for key, field in (("subject_name", "name"), ("subject_title", "title"), ("subject_year", "year"), ("imdb_id", "imdb_id")):
        if key in e and s.get(field) != e[key]:
            out.append(f"{field} {s.get(field)!r} != {e[key]!r}")
    if "directors" in e and s.get("directors") != e["directors"]:
        out.append("directors differ from the expectation")
    if "people" in e and {p for g in m.get("crew", []) for p in g["people"]} != e["people"]:
        out.append("crew differs from the expectation")
    if "total" in e and m.get("total") != e["total"]:
        out.append(f"total {m.get('total')} != {e['total']}")
    if "seasons" in e and len(m.get("seasons", [])) != e["seasons"]:
        out.append("season count differs from the expectation")
    if "episodes" in e and m.get("total") != e["episodes"]:
        out.append("episode total differs from the expectation")
    if "first_result_work" in e and (m.get("results") or [{}])[0].get("work_title") != e["first_result_work"]:
        out.append("first result differs")
    if "first_collaborator" in e and (m.get("collaborators") or [{}])[0].get("name") != e["first_collaborator"]:
        out.append("first collaborator differs")
    if e.get("ids_for_chain") and not all(w.get("imdb_id") for w in m.get("works", [])):
        out.append("a listed work has no imdb id for the next step")
    return out


def baseline_comparison(records: list[dict[str, Any]]) -> dict[str, Any]:
    base = json.loads(BASELINE.read_text(encoding="utf-8"))["rows"]
    by_no = {r["baseline_no"]: r for r in records if r["baseline_no"]}
    rows, totals = [], {"now": 0, "assumed_after": 0, "verified_after": 0}
    for no, b in enumerate(base, 1):
        r = by_no[no]
        now, after = b["now"]["http"], b["after"]["http"]
        # answered by the local database: a correct result, or the alternatives / not-found that the question itself asks for
        local_ok = (r["verdict"] in {"correct", "needs_disambiguation"} or (r["expected_status"] is not None and r["verdict"] == "honest_" + r["expected_status"])) and r["settles_the_question"]
        verified = after if (r["coverage"] != "none" and local_ok and b["proposed"] != b["current"]) else now
        rows.append({"no": no, "question": b["question"], "coverage": r["coverage"], "verdict": r["verdict"], "http_now": now, "http_assumed_after": after, "http_verified_after": verified,
                     "answered_locally": r["coverage"] != "none" and local_ok, "current": b["current"], "proposed": b["proposed"], "external_still_needed": r["external"], "cinema_sql_steps": len(r["steps"]), "queries": r["queries"], "wall_ms": r["wall_ms"]})
        totals["now"] += now
        totals["assumed_after"] += after
        totals["verified_after"] += verified
    return {"rows": rows, "totals": totals}


def _cell(text: Any) -> str:
    return str(text).replace("|", "/").replace("\n", " ")


def markdown(summary: dict[str, Any], records: list[dict[str, Any]], comparison: dict[str, Any]) -> str:
    totals = comparison["totals"]
    verdict_names = {"correct": "corretta", "needs_disambiguation": "corretta dopo la scelta tra omonimi", "honest_ambiguous": "alternative (è la risposta)", "honest_not_found": "non trovato (corretto)",
                     "not_applicable": "non applicabile", "incorrect": "SBAGLIATA", "error": "errore"}
    L = ["# Benchmark della fase 5: `cinema_sql` sul database reale", "",
         "Generato da `python -m cinema_db.harness.tool_eval.run_benchmark` (offline, gratuito, nessuna rete, nessun LLM). **Misurato**: query SQL eseguite dal tool e tempi (mediana di "
         f"{summary['runs_per_step']} esecuzioni, connessione aperta a ogni esecuzione); correttezza rispetto al database, ricalcolata con SQL indipendente sulle **tabelle di base** (non sulle viste "
         "e non attraverso la guardia). **Non misurato**: il planner. Le sequenze di passi sono scritte a mano (come le scriverebbe un planner), quindi quale piano scriva davvero un planner LLM "
         "**non** è provato qui. La colonna «lettura manuale» è la mia lettura del risultato contro ciò che so del mondo, scritta dopo aver visto l'output: non è un controllo automatico.", "",
         f"Database: digest `{summary['database_digest'][:16]}…`. Domande: {summary['questions']} ({summary['executed']} eseguite, {summary['not_applicable']} non applicabili al database locale).", "",
         "## 1. Esiti", "", "| Esito | Domande |", "|---|---|"]
    L += [f"| {verdict_names.get(v, v)} | {n} |" for v, n in summary["verdicts"].items()]
    L += ["", f"Query SQL totali sulle {summary['executed']} domande eseguite: **{summary['queries_total']}** (mediana {summary['queries_median_per_question']:.0f} per domanda). Tempo di una domanda (tutti i passi, "
          f"connessione compresa): mediana **{summary['wall_ms_median']:.0f} ms**, massimo **{summary['wall_ms_max']:.0f} ms**.", "",
          "## 2. Domande, risposte e verifica", "", "| Chiave | Domanda | Risposta ottenuta (sintesi) | Esito | Passi | Query | ms | Lettura manuale e limiti dei dati |", "|---|---|---|---|---|---|---|---|"]
    for r in records:
        L.append(f"| {r['key']} | {_cell(r['question'])} | {_cell(r['answer'][:260])} | {verdict_names.get(r['verdict'], r['verdict'])} | {len(r['steps'])} | {r['queries']} | {r['wall_ms']:.0f} | {_cell(r['manual'] or r['reason'])} |")
    L += ["", "## 3. Confronto con la baseline (30 domande di `BASELINE.md`)", "",
          "«Copertura teorica» = cosa il tool può dare per costruzione (completa, parziale, nessuna). «Verificato» = esito del benchmark. Le richieste HTTP «oggi» e «dopo (baseline)» sono quelle di "
          "`baseline.json` (per le operazioni con fixture sono misurate sui transport finti, per le altre stimate dal codice); «dopo (verificato)» applica la stessa riduzione solo alle domande "
          "con copertura non nulla il cui risultato locale è stato verificato corretto (anche dopo la scelta tra omonimi) **e** risolve davvero la domanda secondo la mia lettura manuale (B05 e B17 no: il database non dice «remake»), altrimenti resta il valore di oggi.", "",
          "| # | Domanda | Copertura teorica | Verificato | HTTP oggi | HTTP dopo (baseline) | HTTP dopo (verificato) | Tool esterni ancora necessari | Passi cinema_sql | Query | ms |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in comparison["rows"]:
        L.append(f"| {row['no']} | {_cell(row['question'])} | {row['coverage']} | {verdict_names.get(row['verdict'], row['verdict'])} | {row['http_now']} | {row['http_assumed_after']} | {row['http_verified_after']} | "
                 f"{', '.join(row['external_still_needed']) or '—'} | {row['cinema_sql_steps']} | {row['queries']} | {row['wall_ms']:.0f} |")
    full = [r for r in comparison["rows"] if r["coverage"] == "full"]
    partial = [r for r in comparison["rows"] if r["coverage"] == "partial"]
    none = [r for r in comparison["rows"] if r["coverage"] == "none"]
    L += ["", "### Totali", "", "| Metrica | Valore |", "|---|---|",
          f"| Richieste HTTP oggi (baseline) | {totals['now']} |", f"| Richieste HTTP dopo, assunte dalla baseline | {totals['assumed_after']} |",
          f"| Richieste HTTP dopo, **verificate** | {totals['verified_after']} |",
          f"| Domande con copertura completa / parziale / nessuna | {len(full)} / {len(partial)} / {len(none)} |",
          f"| Copertura completa, verificata e che risolve la domanda (senza tool esterno) | {sum(r['answered_locally'] for r in full)} su {len(full)} |",
          f"| Domande con almeno un omonimo da risolvere (un passo in più) | {sum(r['cinema_sql_steps'] > 1 and r['verdict'] == 'needs_disambiguation' for r in comparison['rows'])} |",
          f"| Query locali per le 21 domande con copertura completa o parziale (mediana) | {statistics.median(r['queries'] for r in full + partial):.0f} |", "",
          "Cosa dice il confronto, con i limiti:", "",
          f"- La baseline assumeva {totals['assumed_after']} richieste dopo; con i piani scritti a mano il conteggio verificato è {totals['verified_after']} ({'tutte le riduzioni assunte sono confermate' if totals['verified_after'] == totals['assumed_after'] else 'in più rispetto alla stima: sono le domande in cui il risultato locale non basta o non risolve la domanda'}): sono {totals['now'] - totals['verified_after']} richieste in meno su {totals['now']}, ma contando solo il lato HTTP.",
          "- **Passi di pianificazione**: 5 domande (B05, B07, B10, B17, B29) hanno un titolo omonimo e richiedono un secondo passo dopo le alternative; la baseline le contava a un solo passo. È un costo reale non incluso nella stima (un secondo passo del planner, stimato circa 2 s).",
          "- **Dove il fallback esterno resta indispensabile**: punteggi (OMDb), interviste (YouTube), streaming, trailer, uscite recenti, classifiche per voto e consigli semantici (nessun dato locale); numerazione degli episodi (TVmaze); «remake» (B05, B17): il database non distingue remake, prequel e adattamento.",
          "- **Dati incompleti**: il catalogo non ha tutti i film (mancano due film di Villeneuve), i premi assegnati alla persona sono solo quelli con il nominato registrato (le vittorie di Oppenheimer non compaiono tra quelle di Nolan), i conteggi degli episodi non sono affidabili (Breaking Bad S1, S4, S5). In questi casi una risposta locale può essere incompleta senza saperlo: per questo il tool la dichiara nelle note e non la presenta come completa.",
          "- La riduzione delle richieste è la differenza di conteggio tra due piani scritti a mano: non è una misura di un turno reale con planner e modello.", ""]
    return "\n".join(L)


def main() -> int:
    if not DB.is_file():
        raise SystemExit(f"{DB} is missing: build it first (python -m cinema_db.harness.build.build)")
    tool = CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(DB), max_queries_per_turn=40, default_limit=25))
    raw = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    records = [evaluate(q, tool, raw) for q in QUESTIONS]
    raw.close()
    comparison = baseline_comparison(records)
    executed = [r for r in records if r["coverage"] != "none"]
    summary = {
        "questions": len(records), "executed": len(executed), "not_applicable": len(records) - len(executed),
        "verdicts": {v: sum(r["verdict"] == v for r in records) for v in sorted({r["verdict"] for r in records})},
        "queries_total": sum(r["queries"] for r in executed), "queries_median_per_question": statistics.median(r["queries"] for r in executed),
        "wall_ms_median": statistics.median(r["wall_ms"] for r in executed), "wall_ms_max": max(r["wall_ms"] for r in executed),
        "runs_per_step": RUNS, "database_digest": sqlite3.connect(f"file:{DB}?mode=ro", uri=True).execute("SELECT value FROM build_info WHERE key='content_sha256'").fetchone()[0],
    }
    OUT_JSON.write_text(json.dumps({"summary": summary, "records": records, "baseline_comparison": comparison}, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    OUT_MD.write_text(markdown(summary, records, comparison), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    for r in records:
        print(f"{r['key']} {r['verdict']:22} q={r['queries']} {r['wall_ms']:7}ms  {r['answer'][:110]}" + (f"  PROBLEMS {r['problems']}" if r["problems"] else ""))
    print(comparison["totals"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
