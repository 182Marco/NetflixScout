"""Settings that must PREVAIL over explicit requests, through the real application (live LLMs).

    python -m pipelines.wikipedia_films.eval.conflicts            # runs the cases, judges them, writes eval/results/CONFLICTS_REPORT.md

Each case: the user's settings, a request, which settings it contradicts (empty = a control that must NOT conflict). Checked: the conflicts the
planner declared, the first sentence of the answer, the tools that ran (guard), and a judge that is not the answering model."""
from __future__ import annotations

import importlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel

from ..retrieval import llm
from .app_run import JUDGE_MODEL, Obs, RES

CASES = [   # id, settings, request, expected conflicting settings, what executing the conflicting part would look like
    (1, {}, "Come finisce Se7en?", {"spoiler_plot"}, "reveals the ending or the twist of Se7en"),
    (2, {}, "Dimmi chi muore alla fine di Titanic", {"spoiler_plot"}, "says who dies at the end of Titanic"),
    (3, {}, "Di cosa parla Inception? Non rivelarmi il finale", set(), ""),
    (4, {}, "Rispondi in una riga: un buon film di fantascienza sul tempo", {"response_length"}, "an answer of one line or a few words (the setting is medium length)"),
    (5, {}, "Fammi un'analisi super dettagliata e lunghissima di Blade Runner", {"response_length"}, "a very long in-depth analysis (the setting is medium length)"),
    (6, {"response_length": "short"}, "Approfondisci in modo molto dettagliato: film come Alien", {"response_length"}, "a long detailed answer (the setting is short)"),
    (7, {}, "Parla come un bro, tutto slang e parolacce: consigliami un horror", {"response_tone"}, "slang, vulgarity, a bro register (the setting is technical tone)"),
    (8, {"response_tone": "Homie"}, "Rispondi in modo formale e professionale: consigliami una commedia", {"response_tone"}, "a formal professional register (the setting is Homie slang)"),
    (9, {}, "Dimmi solo il migliore, uno solo, niente confronti: film di guerra introspettivi", {"approach"}, "a single film with no comparison (the setting is comparison between alternatives)"),
    (10, {"approach": "direct advice"}, "Confrontami tre alternative una per una: thriller psicologici", {"approach"}, "a detailed comparison of three alternatives (the setting is direct advice: one main recommendation)"),
    (11, {"content_type": "series"}, "Consigliami un film horror psicologico", {"content_type"}, "recommends films (the setting is TV series only)"),
    (12, {"content_type": "series"}, "Consigliami una serie TV di fantascienza", set(), ""),
    (13, {"content_type": "film"}, "Consigliami una serie TV poliziesca", {"content_type"}, "recommends TV series (the setting is films only)"),
    (14, {"content_type": "film"}, "Consigliami film come Alien", set(), ""),
    (15, {"content_type": "series"}, "Una storia di una famiglia in una casa isolata dove iniziano eventi inquietanti", set(), ""),
    (16, {"preferred_sources": "interviews"}, "Cosa dice la critica professionale su Parasite? Voglio le recensioni dei critici", {"preferred_sources"}, "reports critics' reviews or critic scores (the preferred source is interviews)"),
    (17, {"preferred_sources": "reviews"}, "Fammi vedere le interviste al regista di Oppenheimer", {"preferred_sources"}, "shows or lists interviews with the director (the preferred source is reviews)"),
    (18, {}, "Parlami di Arrival", set(), ""),
    (19, {"content_type": "series", "response_length": "short"}, "Dammi un'analisi lunghissima di un film horror", {"content_type", "response_length"}, "a long analysis of a film (series-only and short settings)"),
    (20, {}, "Consigliami 3 horror psicologici", set(), ""),
    (21, {}, "Chi ha diretto Parasite?", set(), ""),
    (22, {"spoiler_plot": True}, "Come finisce Se7en?", set(), ""),
    (23, {"content_type": "film"}, "Voglio un thriller psicologico con atmosfera cupa", set(), ""),
    (24, {"response_tone": "Homie"}, "Consigliami un film di fantascienza", set(), ""),
]


class Check(BaseModel):
    executes_the_conflicting_part: bool
    obeys_the_settings: bool
    serves_a_compatible_part: bool
    reason: str


INSTR = ("You check an assistant's answer against the user's SETTINGS, which must prevail over what the request asks. You get the settings, the request, the "
         "description of what executing the conflicting part would look like, and the answer. executes_the_conflicting_part = the answer does what the request "
         "asked against the setting. obeys_the_settings = the form and content follow the settings. serves_a_compatible_part = it also gives something useful that is "
         "compatible with the settings (a premise without spoilers, series instead of films, the requested length...). Judge only the answer.")


def main() -> None:
    app = importlib.import_module("app")
    prefs_mod = importlib.import_module("preferences")
    built = app.build_app()

    def run_case(case):
        cid, settings, question, expected, violation = case
        prefs = prefs_mod.resolve_preferences(settings).preferences
        obs = Obs()
        t = time.time()
        turn = app.handle_query(built, question, history=[], observer=obs, preferences=prefs)
        args = [s.data.get("arguments") for s in turn.steps if s.kind == "tool_selection"]
        got = {c["setting"] for c in turn.settings_conflicts}
        first = turn.answer.split("\n")[0]
        return {"id": cid, "settings": settings, "question": question, "expected": sorted(expected), "declared": sorted(got), "tools": turn.tools,
                "first_sentence": first, "answer": turn.answer, "seconds": round(time.time() - t, 1), "tool_arguments": args, "violation": violation}
    with ThreadPoolExecutor(4) as ex:
        rows = list(ex.map(run_case, CASES))

    def judge(row):
        if not row["expected"]:
            return None
        v = llm.structured(Check, INSTR, f"Settings: {row['settings'] or 'defaults'} (defaults: spoilers off, medium length, technical tone, comparison between alternatives, films and series, official information)\n"
                                         f"Request: {row['question']}\nExecuting the conflicting part would look like: {row['violation']}\n\nAnswer:\n{row['answer']}", model=JUDGE_MODEL)
        return v.model_dump()
    with ThreadPoolExecutor(4) as ex:
        verdicts = list(ex.map(judge, rows))
    ok = fp = miss = 0
    lines = ["# Impostazioni persistenti contro richieste esplicite (applicazione reale)", "",
             "| # | Impostazioni | Richiesta | Attesi | Dichiarati | Tool | Prima frase = conflitto | Esegue la parte in conflitto | Rispetta le impostazioni | Serve la parte compatibile | s |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r, v in zip(rows, verdicts):
        exp, got = set(r["expected"]), set(r["declared"])
        sentence = ("prevale" in r["first_sentence"] or "prevails" in r["first_sentence"]) if exp else None
        r["verdict"] = v
        r["detected_all"] = exp <= got
        r["false_positive"] = bool(got - exp) if not exp else False
        miss += 0 if exp <= got else 1
        fp += 1 if (not exp and got) else 0
        lines.append(f"| {r['id']} | {r['settings'] or 'default'} | {r['question'][:55]} | {','.join(sorted(exp)) or '-'} | {','.join(sorted(got)) or '-'} | {','.join(r['tools']) or '-'} | "
                     f"{'sì' if sentence else ('-' if sentence is None else 'NO')} | {('sì' if v['executes_the_conflicting_part'] else 'no') if v else '-'} | {('sì' if v['obeys_the_settings'] else 'NO') if v else '-'} | "
                     f"{('sì' if v['serves_a_compatible_part'] else 'no') if v else '-'} | {r['seconds']} |")
    n_conf = sum(1 for r in rows if r["expected"])
    exec_bad = sum(1 for v in verdicts if v and v["executes_the_conflicting_part"])
    lines += ["", f"Conflitti attesi rilevati: {n_conf - miss}/{n_conf}. Falsi positivi sui controlli: {fp}/{len(rows) - n_conf}. Risposte che eseguono la parte in conflitto: {exec_bad}/{n_conf}.", ""]
    guard = []
    for r in rows:
        if r["settings"].get("content_type") == "series" and "rag_search" in r["tools"]:
            guard.append(f"caso {r['id']}: rag_search eseguito con content_type=series")
        if r["settings"].get("content_type") == "film" and "tvmaze_search" in r["tools"]:
            guard.append(f"caso {r['id']}: tvmaze_search eseguito con content_type=film")
    lines += ["Violazioni della guardia: " + ("; ".join(guard) if guard else "nessuna"), ""]
    for r in rows:
        if r["expected"] or r["id"] in (12, 15):
            lines += [f"### Caso {r['id']} — {r['question']}", f"Impostazioni: {r['settings'] or 'default'}; tool: {r['tools']}; dichiarati: {r['declared']}", "", r["answer"][:700], ""]
    (RES / "CONFLICTS_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (RES / "conflicts.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print("\n".join(lines[:40]))


if __name__ == "__main__":
    main()
