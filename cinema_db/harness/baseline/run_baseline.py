"""Phase 0 baseline of the cinema DB plan: HTTP requests, planner steps and latencies per question. Offline, free.

    python -m cinema_db.harness.baseline.run_baseline          # writes docs/cinema_db/BASELINE.md and baseline.json

What is MEASURED: the number of HTTP requests the real tool code sends for one operation, run against the fake
transports of the test suite (`tests/*_support.py`); and the latency of real read-only queries on the MovieLens DB.
What is ESTIMATED: the tool sequence of each question (the planner is an LLM and is not run: no credits), the
planner calls, the network latencies (taken from the live notes of AGENTS.md), and the operations without a fixture.
Nothing here touches the network, OpenAI, or any original data (MovieLens is opened `mode=ro`).
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import omdb_support as om  # noqa: E402
import tmdb_support as tm  # noqa: E402
import tvmaze_support as tv  # noqa: E402
import wikidata_support as wd  # noqa: E402

OUT_JSON = ROOT / "docs/cinema_db/baseline.json"
OUT_MD = ROOT / "docs/cinema_db/BASELINE.md"


# ---------------------------------------------------------------- measured unit costs (requests actually sent)
def _tmdb_title() -> int:
    tool, t = tm.make_tool({"/search/movie": tm.search_movie_payload(), f"/movie/{tm.MOVIE_ID}": tm.movie_payload()})
    tm.run(tool, {"operation": "movie_details", "title": "Interstellar"})
    return len(t.paths)


def _tmdb_id() -> int:
    tool, t = tm.make_tool({f"/movie/{tm.MOVIE_ID}": tm.movie_payload()})
    tm.run(tool, {"operation": "movie_details", "tmdb_id": tm.MOVIE_ID})
    return len(t.paths)


def _tmdb_imdb() -> int:
    tool, t = tm.make_tool({"/find/tt0816692": {"movie_results": [{"id": tm.MOVIE_ID, "title": "Interstellar"}]}, f"/movie/{tm.MOVIE_ID}": tm.movie_payload()})
    tm.run(tool, {"operation": "movie_details", "external_id": "tt0816692", "external_source": "imdb"})
    return len(t.paths)


def _omdb(by_title: bool) -> int:
    ID = "tt1000001"
    handler = om.by_endpoint(search=om.search_answer(om.search_hit(ID, "Sample Movie", "2016")), by_id={ID: om.record()})
    tool, t = om.make_tool(handler)
    params = {"title": "Sample Movie"} if by_title else {"imdb_id": ID}
    tool.run(query="q", params=params, conversation_history=[])
    return len(t.calls)


def _tvmaze(facets: list[str], **extra) -> int:
    tool, t = tv.make_tool(tv.routes_for())
    tool.run(query="q", params={"title": "Sample Show", "facets": facets, **extra})
    return len(t.calls)


def _wikidata(op: str, **kw) -> int:
    tool, t = wd.make_tool(wd.routes_for())
    tool.run(query="q", params={"operation": op, **kw}, conversation_history=[])
    return len(t.calls)


def measure_units() -> dict[str, dict]:
    m = lambda n, how: {"requests": n, "basis": how}  # noqa: E731
    return {
        "tmdb.details_by_title": m(_tmdb_title(), "measured"),
        "tmdb.details_by_tmdb_id": m(_tmdb_id(), "measured"),
        "tmdb.details_by_imdb_id": m(_tmdb_imdb(), "measured"),
        "omdb.by_title": m(_omdb(True), "measured"),
        "omdb.by_imdb_id": m(_omdb(False), "measured"),
        "tvmaze.info": m(_tvmaze(["info"]), "measured"),
        "tvmaze.seasons_episodes": m(_tvmaze(["seasons", "episodes"], season=2), "measured"),
        "tvmaze.next_episode": m(_tvmaze(["next"]), "measured"),
        "wikidata.resolve_by_title": m(_wikidata("resolve", title="Sample Film", year=1982), "measured"),
        "wikidata.resolve_by_imdb_id": m(_wikidata("resolve", imdb_id="tt9000001"), "measured"),
        "wikidata.relations_by_title": m(_wikidata("relations", title="Sample Film", year=1982), "measured"),
        "wikidata.relations_by_imdb_id": m(_wikidata("relations", imdb_id="tt9000001"), "measured"),
        # No fixture in the test suite: derived from the code/config, NOT measured.
        "tmdb.person_then_discover": m(2, "estimated: person search + discover (tool/tmdb/operations/discovery.py)"),
        "tmdb.collection": m(2, "estimated: movie_details + collection_details"),
        "tmdb.providers_or_trailer": m(1, "estimated: movie_details with append_to_response on an id already known"),
        "tmdb.trending_or_upcoming": m(1, "estimated: one list endpoint"),
        "rag.enrich_5_films": m(5, "estimated: one /find per returned film (by_imdb_only, max_candidates 5)"),
        "wikipedia.search_and_article": m(2, "estimated: generator=search then the whole article (cache hit afterwards)"),
        "youtube.one_kind": m(2, "estimated: one search.list + one videos.list"),
        "movielens.sql_with_type_check": m(10, "estimated: up to 12 /find to drop series (work_type_checker budget)"),
        "movielens.sql": m(0, "measured: local SQL"),
        "local.sql": m(0, "local, planned"),
    }


# ---------------------------------------------------------------- the 30 questions (tool sequence = ESTIMATE)
# (question, current sequence, proposed sequence). A step is a unit key; "(plan)" counts are derived below.
Q = [
    ("Quali film ha diretto Denis Villeneuve?", ["tmdb.person_then_discover"], ["local.sql"]),
    ("Chi ha scritto la sceneggiatura di Blade Runner?", ["tmdb.details_by_title"], ["local.sql"]),
    ("Film con Cillian Murphy diretti da Christopher Nolan", ["tmdb.person_then_discover"], ["local.sql"]),
    ("Da quale libro è tratto Blade Runner?", ["wikidata.relations_by_title"], ["local.sql"]),
    ("Esiste un remake di The Thing?", ["wikidata.relations_by_title"], ["local.sql"]),
    ("Quali film fanno parte della saga di Alien?", ["wikidata.relations_by_title"], ["local.sql"]),
    ("Quanti Oscar ha vinto Parasite?", ["wikipedia.search_and_article"], ["local.sql"]),
    ("Chi ha vinto l'Oscar come miglior film nel 1995?", ["wikipedia.search_and_article"], ["local.sql"]),
    ("Distingui i film intitolati Crash (anno, regista, ID)", ["wikidata.resolve_by_title"], ["local.sql"]),
    ("Qual è l'ID IMDb di Parasite?", ["tmdb.details_by_title"], ["local.sql"]),
    ("Quanti film ha diretto Federico Fellini?", ["tmdb.person_then_discover"], ["local.sql"]),
    ("Chi ha composto la colonna sonora di Inception?", ["tmdb.details_by_title"], ["local.sql"]),
    ("Punteggi della critica per i film di Villeneuve (preferenza reviews, 5 candidati)",
     ["tmdb.person_then_discover"] + ["omdb.by_title"] * 5, ["local.sql"] + ["omdb.by_imdb_id"] * 5),
    ("Che Rotten Tomatoes ha Oppenheimer?", ["omdb.by_title"], ["local.sql", "omdb.by_imdb_id"]),
    ("Regista, cast e punteggi della critica di Oppenheimer", ["tmdb.details_by_title", "omdb.by_title"], ["local.sql", "omdb.by_imdb_id"]),
    ("Da cosa è tratto Oppenheimer e che punteggi ha?", ["wikidata.relations_by_title", "omdb.by_title"], ["local.sql", "omdb.by_imdb_id"]),
    ("Remake di Solaris e relativo punteggio Metascore", ["wikidata.relations_by_title", "omdb.by_title"], ["local.sql", "omdb.by_imdb_id"]),
    ("Interviste a Villeneuve su Dune e suoi premi", ["wikipedia.search_and_article", "youtube.one_kind"], ["local.sql", "youtube.one_kind"]),
    # unchanged by the new tool (the expected sequence is the same)
    ("Dove vedo Dune in streaming in Italia?", ["tmdb.details_by_title"], ["tmdb.details_by_title"]),
    ("Mostrami il trailer di Aftersun", ["tmdb.details_by_title"], ["tmdb.details_by_title"]),
    ("Quali film escono questo mese?", ["tmdb.trending_or_upcoming"], ["tmdb.trending_or_upcoming"]),
    ("Che voto medio ha Pulp Fiction?", ["movielens.sql"], ["movielens.sql"]),
    ("Quali sono i 10 film più votati di sempre?", ["movielens.sql_with_type_check"], ["movielens.sql_with_type_check"]),
    ("Consigliami un film malinconico ambientato in Giappone", ["rag.enrich_5_films"], ["rag.enrich_5_films"]),
    ("Film come Arrival ma senza alieni", ["rag.enrich_5_films"], ["rag.enrich_5_films"]),
    ("Quante stagioni ha Breaking Bad?", ["tvmaze.seasons_episodes"], ["tvmaze.seasons_episodes"]),
    ("Quando esce il prossimo episodio di Severance?", ["tvmaze.next_episode"], ["tvmaze.next_episode"]),
    ("Storia della Nouvelle Vague", ["wikipedia.search_and_article"], ["wikipedia.search_and_article"]),
    ("Interviste al regista di Parasite", ["youtube.one_kind"], ["youtube.one_kind"]),
    ("Cast e episodi della seconda stagione di Dark", ["tvmaze.info", "tvmaze.seasons_episodes"], ["tvmaze.info", "tvmaze.seasons_episodes"]),
]
# Follow-up offered by the tool (AGENTS.md: Wikipedia almost always offers `more_in_page`): +1 planner call. ESTIMATE.
FOLLOW_UP = {"wikipedia.search_and_article"}
# Latency of one external step in seconds, from the live notes of AGENTS.md / PLAN (ESTIMATES, not measured here).
NET_S = {"tmdb": 0.4, "omdb": 0.4, "tvmaze": 0.4, "wikidata": 2.5, "wikipedia": 0.8, "youtube": 0.8, "rag": 3.5}
PLANNER_S = 2.0  # one planner call (ESTIMATE; the live runs of AGENTS.md do not report it)


def _cost(seq: list[str], units: dict) -> dict:
    http = sum(units[k]["requests"] for k in seq)
    external = [k for k in seq if units[k]["requests"] > 0 or k.startswith("rag")]
    planner = len(seq) + sum(1 for k in seq if k in FOLLOW_UP)  # first plan + one plan_next per extra step (+ follow-up)
    net = sum(NET_S.get(k.split(".")[0], 0.0) * max(units[k]["requests"], 1 if k.startswith("rag") else 0) for k in seq)
    return {"http": http, "planner_calls": planner, "steps": len(seq), "external_steps": len(external),
            "latency_s_est": round(net + PLANNER_S * planner, 1)}


def sql_latency() -> dict:
    """Real read-only queries on MovieLens (never written). Skipped if the DB is not there."""
    db = ROOT / "movie_db/data/movielens32m.sqlite3"
    if not db.is_file():
        return {"available": False}
    from movie_db.config import MovieDbConfig  # noqa: F401
    from tool.movie_db.sql.connection import readonly_connection
    sqls = {
        "top_rated_50": "SELECT m.movie_id, m.clean_title, s.avg_rating FROM movies m JOIN movie_stats s ON s.movie_id=m.movie_id WHERE s.n_ratings>=50 ORDER BY s.avg_rating DESC, s.n_ratings DESC LIMIT 10",
        "by_title": "SELECT movie_id, clean_title, year FROM movies WHERE clean_title LIKE 'Pulp%' LIMIT 10",
        "genre_stats": "SELECT g.genre, count(*), avg(s.avg_rating) FROM movie_genres g JOIN movie_stats s ON s.movie_id=g.movie_id GROUP BY g.genre",
    }
    out = {"available": True, "queries": {}}
    for name, sql in sqls.items():
        times = []
        with readonly_connection(db, timeout_ms=5000) as conn:
            for _ in range(20):
                t0 = time.perf_counter()
                conn.execute(sql).fetchall()
                times.append((time.perf_counter() - t0) * 1000)
        out["queries"][name] = {"p50_ms": round(statistics.median(times), 2), "max_ms": round(max(times), 2), "runs": 20}
    return out


def main() -> None:
    units = measure_units()
    rows = []
    for q, cur, new in Q:
        rows.append({"question": q, "current": cur, "proposed": new, "now": _cost(cur, units), "after": _cost(new, units)})
    tot = lambda key, side: sum(r[side][key] for r in rows)  # noqa: E731
    changed = [r for r in rows if r["current"] != r["proposed"]]
    summary = {k: {"now": tot(k, "now"), "after": tot(k, "after")} for k in ("http", "planner_calls", "external_steps", "latency_s_est")}
    summary["questions"] = len(rows)
    summary["questions_changed"] = len(changed)
    data = {"units": units, "rows": rows, "summary": summary, "sql_latency": sql_latency()}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    OUT_MD.write_text(render(data), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def render(d: dict) -> str:
    L = ["# Baseline Fase 0 (offline, gratuita)", "",
         "Generata da `python -m cinema_db.harness.baseline.run_baseline`. **MISURATO** = eseguito sul codice reale dei tool con i transport finti dei test (nessuna rete). **STIMATO** = sequenza dei tool, chiamate del planner e latenze di rete (il planner è un LLM e non è stato eseguito: nessun credito). Il campo `basis` di ogni costo dice quale dei due.", "",
         "## 1. Richieste HTTP per operazione", "", "| Operazione | Richieste | Base |", "|---|---|---|"]
    for k, v in d["units"].items():
        L.append(f"| `{k}` | {v['requests']} | {v['basis']} |")
    L += ["", "## 2. 30 domande: oggi vs comportamento desiderato (sequenze STIMATE)", "",
          "| # | Domanda | HTTP oggi | HTTP dopo | Planner oggi | Planner dopo | Lat. oggi (s, stima) | Lat. dopo (s, stima) |", "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(d["rows"], 1):
        n, a = r["now"], r["after"]
        L.append(f"| {i} | {r['question']} | {n['http']} | {a['http']} | {n['planner_calls']} | {a['planner_calls']} | {n['latency_s_est']} | {a['latency_s_est']} |")
    s = d["summary"]
    L += ["", "## 3. Totali", "", "| Metrica | Oggi | Dopo |", "|---|---|---|"]
    for k, label in (("http", "Richieste HTTP"), ("planner_calls", "Chiamate del planner (stima)"), ("external_steps", "Passi con tool esterno"), ("latency_s_est", "Latenza stimata (s)")):
        L.append(f"| {label} | {s[k]['now']} | {s[k]['after']} |")
    L += ["", f"Domande la cui sequenza cambia: {s['questions_changed']} su {s['questions']}.", "",
          "## 4. Latenza SQL locale (MISURATA, MovieLens aperto in sola lettura, 20 esecuzioni)", ""]
    sl = d["sql_latency"]
    if sl.get("available"):
        L += ["| Query | p50 (ms) | max (ms) |", "|---|---|---|"] + [f"| {k} | {v['p50_ms']} | {v['max_ms']} |" for k, v in sl["queries"].items()]
    else:
        L.append("DB MovieLens non presente: non misurata.")
    u = d["units"]
    L += ["", "## 5. Cosa dice la misura sul passaggio degli ID (correzione del piano)", "",
          f"- OMDb: per titolo {u['omdb.by_title']['requests']} richieste, per IMDb id {u['omdb.by_imdb_id']['requests']}: **risparmio reale di 1 per titolo**.",
          f"- TMDb: per titolo {u['tmdb.details_by_title']['requests']}, per IMDb id {u['tmdb.details_by_imdb_id']['requests']} (`/find` + dettagli), per TMDb id {u['tmdb.details_by_tmdb_id']['requests']}: l'IMDb id **non** risparmia nulla, solo il `tmdb_id` risparmia 1.",
          f"- Wikidata: relazioni per titolo {u['wikidata.relations_by_title']['requests']}, per IMDb id {u['wikidata.relations_by_imdb_id']['requests']}; `resolve` {u['wikidata.resolve_by_title']['requests']} contro {u['wikidata.resolve_by_imdb_id']['requests']}: **l'ID non risparmia nulla** quando l'etichetta esatta basta (il ripiego a 3 richieste è raro). Il vantaggio di Wikidata è sostituire l'intero tool con SQL locale (3 richieste fino a 15 s ciascuna), non passare l'ID.",
          "- Una chiamata `cinema_sql` solo per ottenere un ID costa un passo del planner (stimato ~2 s) per risparmiare una richiesta (~0,4 s): **non conviene da sola**. Conviene quando il DB risponde già alla domanda (nessun tool esterno) o quando alimenta una catena che comunque lo richiede (es. OMDb per più candidati).", "",
          "## 6. Limiti", "",
          "- Le sequenze dei tool vengono dalle regole di routing, non da un planner eseguito; il vantaggio reale dipende da cosa il planner sceglierà.",
          "- «Dopo» assume che il DB abbia la risposta (premi e incassi hanno copertura parziale: in quel caso si ripiega sul tool online, e il guadagno si perde).",
          "- Le latenze di rete sono stime dalle note live di AGENTS.md; non sono state misurate in questa fase.",
          "- Le operazioni marcate «estimated» non hanno fixture nei test: il loro costo è letto dal codice, non misurato.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
