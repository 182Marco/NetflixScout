"""LIVE evaluation of the integration: the REAL application (classifier, planner, tools, final answer) with the cinema_sql flag OFF and ON.

    python -m cinema_db.harness.tool_eval.run_live plan                  # offline: the list of runs
    python -m cinema_db.harness.tool_eval.run_live run --live            # runs every missing (question, mode): spends API credits, calls TMDb/OMDb/YouTube/Wikipedia/TVmaze/Wikidata
    python -m cinema_db.harness.tool_eval.run_live judge --live          # an independent model compares the two answers of each question (spends credits)
    python -m cinema_db.harness.tool_eval.run_live report                # offline: writes docs/cinema_db/PHASE6_LIVE.json and .md from the runs

Measured per run: the tools called, the HTTP requests actually sent (the `calls` of every tool step), the SQL queries, the wall time, the answer. The correctness of the answer is
checked against facts that must appear (`MUST`, from the database and my knowledge of the films), compared between the two modes, judged blind by a second model and read by me;
those three are different things and the report keeps them apart. Questions that would use embeddings (B24, B25: the film index) are not run: the RAG is not touched by this phase.
No embedding is ever made: `rag_search` is removed from the allowed tools of the runs.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cinema_db.harness.tool_eval.questions import QUESTIONS

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "cinema_db/data/phase6_live/runs.jsonl"
JUDGMENTS = ROOT / "cinema_db/data/phase6_live/judgments.jsonl"
OUT_JSON = ROOT / "docs/cinema_db/PHASE6_LIVE.json"
OUT_MD = ROOT / "docs/cinema_db/PHASE6_LIVE.md"
SKIPPED = {"B24": "film index (embeddings): not touched by this phase", "B25": "film index (embeddings): not touched by this phase"}
JUDGE_MODEL = "gpt-5.5"  # not the model that plans or answers (gpt-5.6-luna), like the film evaluation
PAUSE_SECONDS = 2.0
RUN_TIMEOUT_SECONDS = 300  # one hung API call must not stall the evaluation for hours (seen once): a run that exceeds it is recorded as an error


@dataclass(frozen=True)
class Live:
    key: str
    turns: tuple[str, ...]
    kind: str                       # local | partial | external | guard | multi | language
    preferences: dict[str, Any] | None = None
    must: tuple[tuple[str, ...], ...] = ()   # each group: at least one of its words in the (last) answer
    expect_local: bool | None = None         # whether cinema_sql SHOULD be the tool when it is on (None = no expectation)
    note: str = ""


# Facts that must appear in the answer. Groups are alternatives; matching is case-insensitive.
MUST: dict[str, tuple[tuple[str, ...], ...]] = {
    "B01": (("Prisoners",), ("Arrival",), ("Dune",)), "B02": (("Fancher",), ("Peoples",)), "B03": (("Batman Begins",), ("Inception",), ("Oppenheimer",)),
    "B04": (("androidi",),), "B06": (("Prometheus",), ("Covenant",), ("Aliens", "Scontro finale")), "B08": (("Forrest Gump",),), "B11": (("La strada",), ("Amarcord", "8½", "Otto e mezzo")),
    "B12": (("Zimmer",),), "B13": (("Dune",), ("Arrival",)), "B14": (("Rotten", "Tomatoes", "%"),), "B15": (("Nolan",), ("Murphy",)), "B16": (("Prometheus", "Prometeo", "Oppenheimer", "Bird", "Sherwin"),),
    "B18": (("Arrival", "Oscar", "candidatura", "nomination"),), "B26": (("5", "cinque", "five"),), "B29": (("Bong",),), "B30": (("Dark",),),
    "E01": (("Caine",), ("Murphy",)), "E03": (("Pacino",), ("Brando", "Caan", "Duvall")), "E04": (("Paramount",),), "E06": (("Oscar",), ("Inception", "Dunkirk", "Memento")),
    "E07": (("Tutto cambia", "Seven Thirty-Seven", "episodi", "episodes"),), "E09": (("99", "novantanove"),),
    "X01": (("Villeneuve",), ("Spaihts", "Roth")), "X03": (("Nolan",),), "X04": (("Parte II", "Part II", "Il padrino - Parte II"), ("Parte III", "Part III")),
    "X05": (("4", "quattro", "four"),), "X08": (("Nolan",), ("Goyer", "Fratelli", "Jonathan")), "X10": (("La strada",), ("Amarcord", "8½", "La dolce vita", "I vitelloni")), "X11": (("Zimmer",),),
}
EXPECT_LOCAL = {"B01": True, "B02": True, "B03": True, "B04": True, "B06": True, "B08": True, "B09": True, "B11": True, "B12": True, "B13": True, "B26": True, "E01": True, "E03": True, "E04": True,
                "E06": True, "E08": True, "E09": None, "X01": True, "X03": True, "X04": True, "X10": True, "X11": True}
EXTRA = (
    Live("X01", ("Chi ha diretto Dune del 2021 e chi ha scritto la sceneggiatura?",), "local"),
    Live("X02", ("Quali sono gli ultimi film con Timothée Chalamet?",), "external", note="recent works: not the local archive"),
    Live("X03", ("Con quali registi ha lavorato di più Michael Caine?",), "local"),
    Live("X04", ("Elencami i film della saga de Il padrino",), "local"),
    Live("X05", ("Quanti Oscar ha vinto Parasite?", "Intendevo quello del 2019 di Bong Joon-ho"), "multi", note="the namesake is asked, then settled by the user"),
    Live("X06", ("Quali film ha diretto Denis Villeneuve?",), "guard", preferences={"preferred_sources": "reviews"}, note="the reviews preference is not a conflict for a filmography"),
    Live("X07", ("Quali film ha diretto Christopher Nolan?",), "guard", preferences={"content_type": "series"}, note="the content type prevails over the request"),
    Live("X08", ("Chi ha scritto Il cavaliere oscuro e da quale opera è tratto?",), "partial"),
    Live("X10", ("Which films did Federico Fellini direct?",), "language"),
    Live("X11", ("Wer hat die Musik zu Inception komponiert?",), "language"),
)


def live_questions() -> list[Live]:
    out: list[Live] = []
    for q in QUESTIONS:
        if q.key in SKIPPED:
            continue
        out.append(Live(q.key, (q.text,), "local" if q.coverage == "full" else q.coverage if q.coverage != "none" else "external", must=MUST.get(q.key, ()),
                        expect_local=EXPECT_LOCAL.get(q.key)))
    out += [Live(x.key, x.turns, x.kind, x.preferences, MUST.get(x.key, ()), EXPECT_LOCAL.get(x.key), x.note) for x in EXTRA]
    return out


# ---- running --------------------------------------------------------------------------------------------------------------------------
def build(mode: str):
    from app import build_ready_app

    # `fallback_tool` is the film index by default: a failed plan would embed a query, so it points at tmdb_search for these runs.
    overrides: dict[str, Any] = {"orchestrator": {"fallback_tool": "tmdb_search", "allowed_tools": ["movie_db_search", "tmdb_search", "youtube_search", "wikipedia_search", "omdb_search", "tvmaze_search", "wikidata_search"]}}
    if mode == "on":
        overrides["orchestrator"]["allowed_tools"].append("cinema_sql")
        overrides["cinema_db"] = {"enabled": True}
    app = build_ready_app(overrides)
    assert ("cinema_sql" in app["orchestrator"].tools) == (mode == "on")
    assert "rag_search" not in app["orchestrator"]._allowed_tool_names(), "no embedding may be made"
    return app


def measure(result, wall: float) -> dict[str, Any]:
    http = sum(len(s.data.get("calls") or []) for s in result.steps if isinstance(s.data, dict))
    sql = sum(int(s.data.get("queries_count") or 0) for s in result.steps if s.kind == "cinema_sql_calls")
    return {"tools": list(result.tools), "tool_steps": sum(1 for s in result.steps if s.kind == "tool_selection"), "http": http, "sql_queries": sql, "wall_s": round(wall, 2),
            "answer": result.answer, "language": result.language, "conflicts": [c.get("setting") for c in (getattr(result, "settings_conflicts", None) or []) if isinstance(c, dict)],
            "step_kinds": [s.kind for s in result.steps],
            "tool_ms": [[s.data.get("tool"), s.data.get("elapsed_ms")] for s in result.steps if s.kind == "tool_outcome" and isinstance(s.data, dict)],
            "timings": dict(getattr(result, "timings", None) or {})}


def run_one(app, live: Live) -> dict[str, Any]:
    from app import handle_query
    from preferences import resolve_preferences

    prefs = resolve_preferences(live.preferences).preferences if live.preferences else None
    history: list[dict[str, str]] = []
    turns, totals = [], Counter()
    for text in live.turns:
        started = time.perf_counter()
        result = handle_query(app, text, history, preferences=prefs)
        wall = time.perf_counter() - started
        history = result.history
        m = measure(result, wall)
        turns.append({"query": text, **m})
        totals.update({k: m[k] for k in ("tool_steps", "http", "sql_queries")})
        totals["wall_s"] += m["wall_s"]
    last = turns[-1]
    return {"turns": turns, "tools": [t for turn in turns for t in turn["tools"]], "tool_steps": totals["tool_steps"], "http": totals["http"], "sql_queries": totals["sql_queries"],
            "wall_s": round(totals["wall_s"], 2), "answer": last["answer"], "conflicts": last["conflicts"]}


def done() -> set[tuple[str, str]]:
    if not RUNS.is_file():
        return set()
    return {(r["key"], r["mode"]) for r in map(json.loads, RUNS.read_text(encoding="utf-8").splitlines()) if "error" not in r}


def cmd_run(args: argparse.Namespace) -> None:
    if not args.live:
        raise SystemExit("run needs --live: it calls the OpenAI API and the external services of the tools")
    from dotenv import load_dotenv

    load_dotenv()
    RUNS.parent.mkdir(parents=True, exist_ok=True)
    apps = {mode: build(mode) for mode in ("off", "on")}
    todo = [(q, m) for q in live_questions() for m in ("off", "on") if (q.key, m) not in done() and (not args.only or q.key in args.only)]
    print(f"{len(todo)} runs to do", flush=True)
    for i, (q, mode) in enumerate(todo, 1):
        record: dict[str, Any] = {"key": q.key, "mode": mode, "kind": q.kind, "turns_text": list(q.turns), "preferences": q.preferences}
        import signal

        def _timeout(signum, frame):  # noqa: ARG001
            raise TimeoutError(f"run exceeded {RUN_TIMEOUT_SECONDS} s")

        signal.signal(signal.SIGALRM, _timeout)
        signal.alarm(RUN_TIMEOUT_SECONDS)
        try:
            record.update(run_one(apps[mode], q))
        except Exception as exc:  # noqa: BLE001 - a failed run is data, not a reason to stop the evaluation
            record["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        finally:
            signal.alarm(0)
        with RUNS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(f"[{i}/{len(todo)}] {q.key} {mode}: {record.get('tools') or record.get('error')} http={record.get('http')} sql={record.get('sql_queries')} {record.get('wall_s')}s", flush=True)
        time.sleep(PAUSE_SECONDS)


# ---- judging --------------------------------------------------------------------------------------------------------------------------
def latest() -> dict[tuple[str, str], dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}
    if RUNS.is_file():
        for r in map(json.loads, RUNS.read_text(encoding="utf-8").splitlines()):
            if "error" not in r:
                out[(r["key"], r["mode"])] = r
    return out


JUDGE_INSTRUCTIONS = (
    "You are an impartial judge comparing two answers (A and B) from a film assistant to the same user request. Judge the FACTS with your own knowledge of cinema: names, years, titles, "
    "counts, awards, credits. Penalise anything invented or wrong, reward completeness, and reward honesty about uncertainty: saying that data may be incomplete, or asking which of "
    "two same-name works is meant when the request is ambiguous, is good; presenting a partial list as complete is bad. Do not reward length. You do not know where either answer comes from. "
    'Reply with JSON only: {"winner":"A"|"B"|"tie","a_errors":[...],"b_errors":[...],"reason":"one sentence"}.'
)


def cmd_judge(args: argparse.Namespace) -> None:
    if not args.live:
        raise SystemExit("judge needs --live: it calls the OpenAI API")
    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()
    client = OpenAI()
    runs = latest()
    existing = {j["key"] for j in map(json.loads, JUDGMENTS.read_text(encoding="utf-8").splitlines())} if JUDGMENTS.is_file() else set()
    JUDGMENTS.parent.mkdir(parents=True, exist_ok=True)
    for key in sorted({k for k, _ in runs}):
        off, on = runs.get((key, "off")), runs.get((key, "on"))
        if not off or not on or key in existing:
            continue
        swap = random.Random(f"{key}-20261106").random() < 0.5
        a, b = (on, off) if swap else (off, on)
        question = " / ".join(off["turns_text"])
        prompt = f"Request: {question}\n\n=== ANSWER A ===\n{a['answer']}\n\n=== ANSWER B ===\n{b['answer']}"
        try:
            reply = client.responses.create(model=JUDGE_MODEL, instructions=JUDGE_INSTRUCTIONS, input=prompt)
            text = reply.output_text.strip()
            verdict = json.loads(text[text.index("{"): text.rindex("}") + 1])
            winner = str(verdict.get("winner", "tie")).strip().upper()
            real = "tie" if winner not in ("A", "B") else ("on" if (winner == "A") == swap else "off")
            row = {"key": key, "winner": real, "on_errors": verdict.get("a_errors" if swap else "b_errors", []), "off_errors": verdict.get("b_errors" if swap else "a_errors", []), "reason": verdict.get("reason", "")}
        except Exception as exc:  # noqa: BLE001
            row = {"key": key, "winner": "error", "reason": f"{type(exc).__name__}: {str(exc)[:200]}", "on_errors": [], "off_errors": []}
        with JUDGMENTS.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(key, row["winner"], row["reason"][:100], flush=True)


# ---- report ---------------------------------------------------------------------------------------------------------------------------
def has_facts(answer: str, groups: tuple[tuple[str, ...], ...]) -> bool:
    low = answer.casefold()
    return all(any(word.casefold() in low for word in group) for group in groups)


def report() -> dict[str, Any]:
    runs = latest()
    judgments = {j["key"]: j for j in map(json.loads, JUDGMENTS.read_text(encoding="utf-8").splitlines())} if JUDGMENTS.is_file() else {}
    rows = []
    for q in live_questions():
        off, on = runs.get((q.key, "off")), runs.get((q.key, "on"))
        if not off or not on:
            continue
        row = {"key": q.key, "question": " / ".join(q.turns), "kind": q.kind, "preferences": q.preferences, "note": q.note, "expect_local": q.expect_local}
        for mode, r in (("off", off), ("on", on)):
            row[mode] = {k: r[k] for k in ("tools", "tool_steps", "http", "sql_queries", "wall_s", "answer", "conflicts")}
            row[mode]["facts"] = has_facts(r["answer"], q.must) if q.must else None
        row["cinema_used"] = "cinema_sql" in on["tools"]
        row["judge"] = judgments.get(q.key)
        rows.append(row)
    both = [r for r in rows]
    summary = {
        "questions": len(rows), "skipped": SKIPPED,
        "totals": {m: {"http": sum(r[m]["http"] for r in both), "tool_steps": sum(r[m]["tool_steps"] for r in both), "sql_queries": sum(r[m]["sql_queries"] for r in both),
                       "wall_s": round(sum(r[m]["wall_s"] for r in both), 1)} for m in ("off", "on")},
        "cinema_used": sum(r["cinema_used"] for r in both), "judge": dict(Counter((r["judge"] or {}).get("winner", "not judged") for r in both)),
        "facts": {m: {"present": sum(r[m]["facts"] is True for r in both), "missing": sum(r[m]["facts"] is False for r in both)} for m in ("off", "on")},
    }
    return {"summary": summary, "rows": rows}


# My own reading of each pair of real answers (written AFTER reading them; not an automated check). Filled in from `docs/cinema_db/PHASE6_LIVE.json`.
MANUAL_LIVE: dict[str, str] = {
    "B01": "Locale: 9 film, corretto rispetto al database e dichiarato «potrebbe essere incompleto» (nel mondo reale ne mancano 2); con TMDb l'elenco era sbagliato (cortometraggi e documentari, «44 risultati»). Miglioramento netto.",
    "B02": "Pari: gli stessi due sceneggiatori.", "B03": "Locale: i 6 film giusti; con TMDb il fatto atteso mancava.",
    "B04": "Locale dà il titolo italiano del romanzo («Il cacciatore di androidi»), Wikidata quello originale: leggermente meno preciso.",
    "B05": "Locale + Wikipedia: dice che il film del 2011 è un prequel; il flag spento inventava un «The Thing (1990) di Nanni Moretti» da un omonimo sbagliato. Miglioramento.",
    "B06": "Locale: 7 film più un cortometraggio e una serie dichiarati come tali; corretto rispetto al database.",
    "B07": "Dopo la correzione del filtro sul premio il planner chiede quale Parasite si intende (1982 o 2019), come voluto; prima della correzione la richiesta era rifiutata e la risposta inutile.",
    "B09": "Locale: i due film principali con ID IMDb, TMDb e Wikidata (prima della correzione citava l'ID interno); mancano omonimi minori; il flag spento ne dava 4 ma senza il film di Haggis.",
    "B11": "Locale: «22 film più un film TV, 23 opere» come registrati; il flag spento non rispondeva. Il giudice preferisce il silenzio prudente al numero di un catalogo incompleto: giudizio discutibile, la risposta locale dichiara i limiti.",
    "B13": "Invariata (TMDb + OMDb per cinque candidati); la differenza di richieste è variabilità del planner, non del tool.",
    "B15": "Locale per regia e cast, TMDb per il resto: 1 richiesta invece di 2.", "B17": "Il tool locale non distingue il remake: la risposta locale dice «adattamento del film del 1972», impreciso (è un nuovo adattamento del romanzo); entrambe sbagliano il Metascore secondo il giudice (la fonte dà 67).",
    "B18": "Regressione di completezza: il locale ha una sola candidatura di Villeneuve (Arrival) e lo dice; con Wikipedia la risposta sui premi è molto più ricca. Limite dei dati, già noto (premi per persona).",
    "B26": "Locale: 5 stagioni e 7/13/13/13/16 episodi (esatti dopo la correzione), con l'avvertenza che possono differire.",
    "E01": "Locale: Caine 8, Murphy 7 (senza role=director conta anche Transcendence, prodotto da Nolan: corretto per «lavorato con»).",
    "E02": "Il planner ha scelto Wikipedia invece del locale: variabilità.", "E04": "Locale: «prodotto da Albert S. Ruddy», corretto; il flag spento aggiungeva Coppola e Evans.",
    "E06": "Regressione di completezza dichiarata: 5 candidature all'Oscar attribuite a Nolan, mancano quelle di Oppenheimer (premi registrati sul film, non sul nominato); Wikipedia ne dà 8 e 2 vittorie. La regola chiede di aggiungere i premi del film: il planner non lo ha fatto in questa esecuzione.",
    "E09": "Locale: 99 film italiani del 1960 (come registrati); il flag spento non sapeva rispondere.",
    "X01": "Dopo la correzione di crew senza role: regista e i tre sceneggiatori; prima della correzione la risposta diceva che gli sceneggiatori non compaiono.",
    "X03": "Prima esecuzione: nessun collaboratore (planner con argomenti diversi); rilanciata a mano la stessa domanda il planner usa role_b=director e la risposta è giusta (Nolan 8, Gilbert 3...). Variabilità del planner.",
    "X04": "Locale: 3 film della saga, con l'avvertenza che l'elenco può essere parziale.", "X05": "Dopo la correzione: «4 Oscar» con le quattro categorie, in due passi (omonimo, poi anno).",
    "X06": "Con la preferenza «recensioni» la filmografia usa il locale senza conflitto e dice che non ha punteggi.",
    "X07": "La frase di conflitto sul tipo di contenuto è la prima della risposta in entrambe le modalità; il locale ha ricevuto type=series dalla guardia.",
    "X08": "Locale elenca anche Bill Finger e Bob Kane tra gli scrittori (Wikidata) ma avverte che l'elenco comprende gli autori del materiale d'origine; TMDb dava solo i Nolan: meno preciso, dichiarato.",
    "X10": "Risposta in inglese, 23 opere: la lingua dell'ultimo messaggio è rispettata.", "X11": "Risposta in tedesco: la lingua è rispettata.",
}


def _tools(r: dict[str, Any]) -> str:
    return " → ".join(t.replace("_search", "").replace("cinema_sql", "CINEMA") for t in r["tools"]) or "—"


def _fact(value: bool | None) -> str:
    return {True: "sì", False: "NO", None: "—"}[value]


def markdown(data: dict[str, Any]) -> str:
    s, rows = data["summary"], data["rows"]
    off, on = s["totals"]["off"], s["totals"]["on"]
    L = ["# Valutazione live della Fase 6: l'applicazione reale con `cinema_sql` spento e acceso", "",
         "Generata da `python -m cinema_db.harness.tool_eval.run_live` con il **planner, il classificatore, i tool e il modello di risposta reali** (OpenAI, TMDb, OMDb, YouTube, Wikipedia, "
         "TVmaze, Wikidata): ogni domanda è eseguita due volte, con il flag spento (come prima della fase) e acceso. Nessun embedding: `rag_search` è tolto dai tool ammessi e le due domande "
         "che lo userebbero (B24, B25) non sono eseguite. **Misurato**: tool chiamati, richieste HTTP realmente inviate (le `calls` di ogni passo dei tool), query SQL, secondi. "
         "**Controllo dei fatti**: parole chiave che devono comparire nella risposta (da database e dalla mia conoscenza), controllo meccanico. **Giudizio**: un secondo modello (`gpt-5.5`, diverso da quello "
         "che risponde) confronta alla cieca le due risposte. **Lettura manuale**: la mia, dopo aver letto le risposte. Sono quattro cose diverse e restano separate.", "",
         "Limiti: una sola esecuzione per domanda e modalità (il planner è stocastico: un'altra esecuzione può scegliere altro); i tempi dipendono dalla rete e dalle API del momento; le richieste HTTP "
         "interne del controllo del tipo di opera di MovieLens non sono nelle `calls`; il giudice usa la propria conoscenza e può sbagliare.", "",
         "## 1. Totali (misurati)", "", "| | Flag spento | Flag acceso | Differenza |", "|---|---|---|---|",
         f"| Domande | {s['questions']} | {s['questions']} | |",
         f"| Richieste HTTP | {off['http']} | {on['http']} | {on['http'] - off['http']:+d} |",
         f"| Passi di tool (tool_selection) | {off['tool_steps']} | {on['tool_steps']} | {on['tool_steps'] - off['tool_steps']:+d} |",
         f"| Query SQL locali | {off['sql_queries']} | {on['sql_queries']} | {on['sql_queries'] - off['sql_queries']:+d} |",
         f"| Tempo totale (s) | {off['wall_s']} | {on['wall_s']} | {on['wall_s'] - off['wall_s']:+.1f} |", "",
         f"`cinema_sql` è stato scelto dal planner in **{s['cinema_used']}** domande su {s['questions']}. Fatti attesi presenti: spento {s['facts']['off']['present']} (assenti {s['facts']['off']['missing']}), "
         f"acceso {s['facts']['on']['present']} (assenti {s['facts']['on']['missing']}). Giudice (a ciechi): {s['judge']}.", "",
         "## 1b. Prima esecuzione completa e correzioni", "",
         "La prima esecuzione completa (flag acceso) ha mostrato tre difetti di integrazione, corretti subito (commit «fix what the live evaluation found»): (1) `awards` rifiutava un titolo o una persona "
         "insieme a un nome di premio («quanti Oscar ha vinto X»: il planner li dà insieme) e la risposta diceva solo «richiesta non riuscita»; (2) con `crew` e più ruoli il planner chiedeva solo `role=director` e "
         "la risposta diceva che gli sceneggiatori non comparivano; (3) il modello citava l'ID interno invece degli ID IMDb e TMDb. Sono state rieseguite le 10 domande interessate (modalità accesa); "
         "il confronto sopra e sotto usa le esecuzioni dopo le correzioni. Prima delle correzioni: richieste HTTP acceso 56, query 87, giudice a favore dell'acceso 23, parità 12, a favore dello spento 12; "
         "dopo: query 98, a favore dell'acceso 23, parità 14, a favore dello spento 10. Le esecuzioni originali restano in `cinema_db/data/phase6_live/runs_first.jsonl` (ignorato da git).", "",
         "## 2. Per domanda", "", "| Chiave | Domanda | Tool spento | Tool acceso | HTTP s/a | SQL | s s/a | Fatti s/a | Giudice | Lettura manuale |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        j = r["judge"]
        L.append(f"| {r['key']} | {r['question'][:90].replace('|', '/')} | {_tools(r['off'])} | {_tools(r['on'])} | {r['off']['http']}/{r['on']['http']} | {r['on']['sql_queries']} | "
                 f"{r['off']['wall_s']:.0f}/{r['on']['wall_s']:.0f} | {_fact(r['off']['facts'])}/{_fact(r['on']['facts'])} | {j['winner'] if j else '—'} | {MANUAL_LIVE.get(r['key'], '').replace('|', '/')} |")
    return "\n".join(L) + "\n"


def cmd_report(args: argparse.Namespace) -> None:
    data = report()
    OUT_JSON.write_text(json.dumps(data, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    OUT_MD.write_text(markdown(data), encoding="utf-8")
    print(json.dumps(data["summary"], ensure_ascii=False, indent=1))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("plan", "run", "judge", "report"))
    ap.add_argument("--live", action="store_true", help="authorise the paid / external calls")
    ap.add_argument("--only", nargs="*", help="keys to run")
    args = ap.parse_args(argv)
    if args.command == "plan":
        for q in live_questions():
            print(q.key, q.kind, q.preferences or "", "|", " / ".join(q.turns))
        print(f"{len(live_questions())} questions x 2 modes; skipped: {SKIPPED}")
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "judge":
        cmd_judge(args)
    else:
        cmd_report(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
