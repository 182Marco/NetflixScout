"""End-to-end check of `series_rag_search` through the real application (`app.handle_query`: classifier, planner, tool, final answer) with Qdrant on and the
feature flag enabled IN THIS PROCESS ONLY. Records quality inputs, latency, HTTP calls and LLM consumption per turn.

    python -m movie_db.harness.evaluation.run_series_e2e run     # PAID (cents) + a few real TMDb/TVmaze calls -> data/s8/e2e_run.jsonl
    python -m movie_db.harness.evaluation.run_series_e2e judge   # PAID (cents): blind gpt-5.5 judge of each answer against the tool results -> data/s8/e2e_judge.jsonl
    python -m movie_db.harness.evaluation.run_series_e2e report  # offline -> data/s8/e2e_summary.json
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

from typing import Literal

from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
OUT = REPO / "tool" / "wikipedia_series" / "data" / "s8"
# `run S6 A1 …` runs only those cases and writes the *_changes files (the 17-turn results of the first session stay untouched)
ONLY = [a for a in sys.argv[2:] if not a.startswith("-")]
SUFFIX = "_changes" if ONLY else ""
RUN, JUDGE, SUMMARY = OUT / f"e2e_run{SUFFIX}.jsonl", OUT / f"e2e_judge{SUFFIX}.jsonl", OUT / f"e2e_summary{SUFFIX}.json"

# id, question, expected first tool(s), preferences (None = web defaults off), history from a previous case
CASES = [
    ("S1", "Consigliami una serie TV su un gruppo di detective che indagano su casi irrisolti in una piccola città di provincia", "series_rag_search", None, None),
    ("S2", "Serie come Dark, ma senza viaggi nel tempo", "series_rag_search", None, None),
    ("S3", "Qual è la puntata in cui un personaggio scopre di essere stato sostituito da un sosia?", "series_rag_search", None, None),
    ("S4", "Nei Simpson, l'episodio in cui Homer diventa famoso per caso", "series_rag_search", None, None),
    ("S5", "Di cosa parla la seconda stagione di Lost?", "series_rag_search", None, None),
    ("S6", "Quali sono gli episodi della prima stagione di Stargate SG-1?", "tvmaze_search", None, None),
    ("S7", "Un film per la televisione drammatico tratto da una storia vera di un processo", "series_rag_search", None, None),
    ("S8", "Consigliami una serie animata per adulti con umorismo nero", "series_rag_search", None, None),
    ("S9", "Series about a lighthouse keeper who discovers a mysterious creature", "series_rag_search", None, None),
    ("S10", "Serie britanniche degli anni 2010 con detective", "series_rag_search", None, None),
    ("S11", "Quali sono gli episodi della seconda stagione di Serie Immaginaria Che Non Esiste Zeta?", "series_rag_search|tvmaze_search|tmdb_search", None, None),
    ("S12", "Consigliami una serie come Dark e dimmi dove posso vederla in streaming", "series_rag_search", None, None),
    ("S13", "Quando esce il prossimo episodio di The Bear?", "tvmaze_search", None, None),
    ("S14", "e una più recente?", "series_rag_search", None, "S2"),
    ("S15", "Consigliami serie come Dark", "(blocked)", {"content_type": "film"}, None),
    ("S16", "Consigliami film come Interstellar", "(blocked)", {"content_type": "series"}, None),
    ("S17", "Consigliami una serie di fantascienza", "series_rag_search", {"content_type": "series", "spoiler_plot": False}, None),
    # third session: the anime classifier fix and the lists-of-episodes rule
    ("A1", "Consigliami un anime di avventura", "series_rag_search", None, None),
    ("A2", "Elencami gli episodi della seconda stagione di Lost", "tvmaze_search", None, None),
    ("A3", "Cerco un anime di avventura con un ragazzo che vuole diventare il più forte spadaccino", "series_rag_search", None, None),
    ("A4", "Nella seconda stagione di Lost, in quale episodio i sopravvissuti trovano la botola?", "series_rag_search", None, None),
]


class Verdict(BaseModel):
    relevance: Literal[0, 1, 2]   # 0 no, 1 partly, 2 yes: the answer serves the request
    grounded: Literal[0, 1, 2]    # 0 invents, 1 minor unsupported details, 2 every claim is in the tool results
    unsupported_claims: list[str]
    names_a_source: bool    # the answer names Wikipedia, a database, a tool or an API


def run() -> int:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    import app as A
    from preferences import resolve_preferences
    from turn import NullObserver

    OUT.mkdir(parents=True, exist_ok=True)
    application = A.build_app({"series_rag": {"enabled": True}})
    A.ensure_series_rag_ready(application["config"]["series_rag"])
    tool = application["orchestrator"].tools["series_rag_search"]
    captured: list[dict] = []
    original = tool.run

    def spy(**kw):
        result = original(**kw)
        captured.append({"usage": result.get("usage"), "items": (result.get("metadata", {}).get("series_rag") or {}).get("items"),
                         "notes": (result.get("metadata", {}).get("series_rag") or {}).get("notes"), "outcome": result.get("outcome")})
        return result
    tool.run = spy
    histories: dict[str, list[dict]] = {}
    with RUN.open("w") as f:
        for cid, question, expected, prefs, hist_from in (c for c in CASES if not ONLY or c[0] in ONLY):
            captured.clear()
            history = list(histories.get(hist_from, [])) if hist_from else []
            started = time.monotonic()
            try:
                turn = A.handle_query(application, question, history, observer=NullObserver(),
                                      preferences=resolve_preferences(prefs).preferences if prefs else None)
                err = None
            except Exception as exc:  # noqa: BLE001
                turn, err = None, f"{type(exc).__name__}: {str(exc)[:200]}"
            wall = int((time.monotonic() - started) * 1000)
            row = {"id": cid, "question": question, "expected": expected, "preferences": prefs, "error": err, "wall_ms": wall}
            if turn is not None:
                histories[cid] = [*history, {"role": "user", "content": question}, {"role": "assistant", "content": turn.answer}]
                http = 0
                for st in turn.steps:
                    http += len(st.data.get("calls") or []) if isinstance(st.data, dict) else 0
                row.update(answer=turn.answer, tools=turn.tools, blocked=turn.blocked, settings_conflicts=turn.settings_conflicts,
                           timings=turn.timings, http_calls=http, tool_runs=list(captured),
                           step_kinds=[s.kind for s in turn.steps])
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n"); f.flush()
            print(cid, row.get("tools"), f"{wall} ms", err or "")
    return 0


def judge() -> int:
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env")
    from openai import OpenAI
    client = OpenAI(max_retries=3, timeout=120)
    with JUDGE.open("w") as f:
        for line in RUN.open():
            r = json.loads(line)
            runs = [t for t in r.get("tool_runs") or [] if t.get("items")]
            if not r.get("answer") or r.get("blocked") or not runs:
                f.write(json.dumps({"id": r["id"], "skipped": True}) + "\n"); continue
            data = json.dumps([t["items"] for t in runs], ensure_ascii=False)[:12000]
            prompt = (f"Richiesta: {r['question']}\n\nRisultati che il sistema aveva (titoli e trame):\n{data}\n\nRisposta data all'utente:\n{r['answer']}\n\n"
                      "Giudica: relevance (la risposta serve la richiesta), grounded (ogni affermazione su trama, anno, personaggi è nei risultati; 0 se inventa), "
                      "l'elenco unsupported_claims (punteggi SOLO 0, 1 o 2), e se la risposta nomina una fonte, un database, un tool o un'API.")
            resp = client.responses.parse(model="gpt-5.5", instructions="You are a strict blind judge.", input=prompt, text_format=Verdict)
            f.write(json.dumps({"id": r["id"], **resp.output_parsed.model_dump()}, ensure_ascii=False) + "\n"); f.flush()
    return 0


def report() -> int:
    rows = [json.loads(l) for l in RUN.open()]
    judged = {json.loads(l)["id"]: json.loads(l) for l in JUDGE.open()} if JUDGE.exists() else {}
    out = []
    for r in rows:
        t = r.get("timings") or {}
        tr = [x.get("usage") or {} for x in r.get("tool_runs") or []]
        tool_tokens = {}
        for u in tr:
            for stage, d in (u.get("tokens") or {}).items():
                a = tool_tokens.setdefault(stage, {"input": 0, "output": 0, "total": 0, "calls": 0})
                for k in a:
                    a[k] += d.get(k, 0)
        expected = r["expected"].split("|")
        used = r.get("tools") or []
        out.append({"id": r["id"], "wall_ms": r["wall_ms"], "tools": used, "expected": r["expected"],
                    "routing_ok": ((r.get("blocked") or bool(r.get("settings_conflicts")) or not used) if expected == ["(blocked)"] else bool(used and used[0] in expected)),
                    "http_calls": r.get("http_calls"), "error": r.get("error"), "timings": t, "series_tool_tokens": tool_tokens,
                    "series_tool_ms": [(x.get("timings_ms") or {}) for x in tr], "judge": judged.get(r["id"])})
    wall = [o["wall_ms"] for o in out if not o["error"]]
    series_turns = [o for o in out if "series_rag_search" in o["tools"]]
    tool_total = [m.get("total") for o in series_turns for m in o["series_tool_ms"] if m.get("total")]
    j = [o["judge"] for o in out if o["judge"] and not o["judge"].get("skipped")]
    summary = {"turns": len(out), "errors": sum(1 for o in out if o["error"]), "routing_ok": sum(1 for o in out if o["routing_ok"]),
               "wall_ms_median": int(statistics.median(wall)) if wall else None, "wall_ms_max": max(wall) if wall else None,
               "series_tool_ms_median": int(statistics.median(tool_total)) if tool_total else None, "series_tool_ms_max": max(tool_total) if tool_total else None,
               "http_calls_total": sum(o["http_calls"] or 0 for o in out),
               "judged": len(j), "relevance_mean": round(sum(x["relevance"] for x in j) / len(j), 2) if j else None,
               "grounded_mean": round(sum(x["grounded"] for x in j) / len(j), 2) if j else None,
               "answers_naming_a_source": [k for k, v in judged.items() if v.get("names_a_source")], "rows": out}
    SUMMARY.write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    cmd = {"run": run, "judge": judge, "report": report}.get(sys.argv[1] if len(sys.argv) > 1 else "")
    sys.exit(cmd() if cmd else (print(__doc__) or 2))
