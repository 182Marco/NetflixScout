"""Phase 8: offline simulation of the planner-step interventions on the runs already recorded (no API, no network, no database write).

  python -m cinema_db.harness.tool_eval.simulate_phase8        # prints the tables and writes docs/cinema_db/PHASE8_SIMULATION.md

WHAT THE DATA ALLOWS. `phase7_live/runs.jsonl` keeps, per run, the tools in order, the HTTP count and the wall time. It does NOT keep the planner arguments, the planner calls
that only answered "done", or the time of each planner call. So the arguments of a step cannot be read; whether a step depends on the result of the step before is
DECLARED below, once, by reading the question (the table is the only judgement in this file, every row has its reason, and nothing is tuned to the output).

Classes of a step that follows another step:
  A  required and independent: the data is not in the local database (scores, streaming, interviews, lead cast, recent films) and the question names what to ask. The step
     would be there whatever the local answer says, so a first plan that already contains it could skip one planner call.
  B  conditional: the step exists because of a gap or an ambiguity in the previous result (awards of a person, remake, a homonym). It depends on that result.
  C  result-dependent arguments: titles or ids come from an earlier result (the candidates of a list).
  D  not required by the question: an extra step (a local answer already covered it, or the other way round).
  U  not declared (a step that this table does not know).
"""
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
RUNS = ROOT / "cinema_db/data/phase7_live/runs.jsonl"
OUT = ROOT / "docs/cinema_db/PHASE8_SIMULATION.md"

# key -> (class -> {tool}); reason per question. `cinema` = cinema_sql, tools without the `_search` suffix.
DECLARED: dict[str, dict[str, Any]] = {
    "P06": {"A": {"tmdb"}, "why": "streaming is not in the database; the film is named in the question"},
    "P08": {"A": {"omdb"}, "why": "Metascore is not in the database; title and year are in the question"},
    "B15": {"A": {"omdb", "tmdb"}, "why": "critic scores and the lead cast are not in the database; the film is named"},
    "B16": {"A": {"omdb", "movie_db"}, "why": "scores are not in the database; the film is named"},
    "B17": {"A": {"omdb"}, "why": "Metascore is not in the database; the film is named"},
    "B18": {"A": {"youtube"}, "B": {"wikipedia"}, "why": "interviews are not in the database; the awards of a person are a gap of the previous result"},
    "P01": {"A": {"tmdb"}, "B": {"cinema", "wikipedia"}, "why": "lead cast is not in the database; the awards depend on what the local result holds"},
    "X02": {"A": {"tmdb"}, "why": "recent films: the catalogue is incomplete after 2019"},
    "B13": {"C": {"omdb", "tmdb"}, "why": "the candidates (titles, years) come from the earlier results"},
    "B05": {"B": {"wikipedia"}, "why": "remake is not told apart by the stored links: a gap of the previous result"},
    "E06": {"B": {"wikipedia"}, "why": "awards of a person are partial: a gap of the previous result"},
    "P03": {"B": {"wikipedia"}, "why": "awards of a person are partial: a gap of the previous result"},
    "P04": {"B": {"wikipedia"}, "why": "awards of a person are partial: a gap of the previous result"},
    "E02": {"B": {"cinema"}, "why": "homonym: a second search after the alternatives"},
    "X05": {"B": {"cinema"}, "why": "homonym: a second search after the alternatives"},
    "X08": {"B": {"cinema", "wikipedia", "tmdb"}, "why": "writer role and source work are gaps of the previous result"},
    "E08": {"B": {"cinema", "wikipedia"}, "why": "the film is not found: the next step depends on the failure"},
    "X07": {"B": {"tmdb"}, "why": "corrected after checking the real database: a series-only filmography of the person is EMPTY locally (no_credits_in_catalogue, follow_up to tmdb_search), so the external step is the designed fallback of an empty result, not a superfluous one"},
    "E05": {"D": {"tmdb"}, "why": "the question belongs to the external tool; the local step before it is the extra one"},
}
# Weight of one skipped planner call, in seconds, with its source. Neither is a measure of the planner call alone.
PER_STEP_REGRESSION = (4.7, 6.8)   # regression of wall time on tool steps (OFF, ON): a step = planner call + tool + longer answer context
PAIRED_MARGINAL = (0.0, 12.0)      # paired cinema+X against X alone, same question: P06 0.0, X07 5.4, B18 9.3, E05 8.0 (n=1), X02 12.2 (n=1)


def short(tool: str) -> str:
    return tool.replace("_search", "").replace("_sql", "")


def classify(key: str, tool: str) -> str:
    row = DECLARED.get(key, {})
    for cls in "ABCD":
        if tool in row.get(cls, set()):
            return cls
    return "U"


def load() -> list[dict[str, Any]]:
    return [json.loads(line) for line in RUNS.read_text(encoding="utf-8").splitlines()]


def simulate() -> dict[str, Any]:
    runs = [r for r in load() if r["mode"] == "on"]
    wall_total = sum(r["wall_s"] for r in load() if r["mode"] == "on")
    transitions = Counter()
    by_key: dict[str, Counter] = defaultdict(Counter)
    omdb_saved = 0
    omdb_turns: list[tuple[str, int, int, float]] = []
    for r in runs:
        tools = [short(t) for t in r["tools"]]
        for i in range(1, len(tools)):
            cls = classify(r["key"], tools[i])
            transitions[cls] += 1
            by_key[r["key"]][cls] += 1
        k = tools.count("omdb")
        if k >= 2:
            omdb_saved += k - 1
            omdb_turns.append((r["key"], r["rep"], k, r["wall_s"]))
    total = sum(transitions.values())
    awards_person = sum(1 for r in runs if r["key"] in {"E06", "P03", "P04"} and "wikipedia_search" in r["tools"])
    return {"runs": len(runs), "wall_total": round(wall_total), "next_plan_calls_lower_bound": total, "transitions": dict(transitions), "by_key": {k: dict(v) for k, v in sorted(by_key.items())},
            "omdb_saved": omdb_saved, "omdb_turns": omdb_turns, "awards_person_steps": awards_person}


def seconds(n: int, low: float, high: float) -> str:
    return f"{n * low:.0f}-{n * high:.0f} s"


def render(s: dict[str, Any]) -> str:
    t = s["transitions"]
    a, b, c, d, u = (t.get(x, 0) for x in "ABCDU")
    o = s["omdb_saved"]
    p = s["awards_person_steps"]
    lines = [
        "# Fase 8 — simulazione offline degli interventi 3 e 4 (generata da `simulate_phase8.py`)",
        "",
        f"Dati: {s['runs']} esecuzioni con DB acceso del secondo giro (`phase7_live/runs.jsonl`), {s['wall_total']} s totali. Nessuna API. **[M]** misurato · **[C]** classificazione dichiarata a mano dal testo della domanda (tabella `DECLARED`) · **[S]** stima.",
        "",
        "## Cosa i dati NON permettono",
        "- Gli **argomenti** dei passi non sono registrati: l'indipendenza dal risultato locale è una classificazione [C], non una lettura.",
        "- Le chiamate del planner che rispondono solo «fatto» e il tempo di ogni chiamata non sono registrati (i `timings` esistono solo dai run futuri): i passi sotto sono un **limite inferiore**.",
        "- Il peso in secondi di UNA chiamata del planner non è misurato. Due indizi in conflitto: la regressione del tempo sui passi dà 4,7 s (spento) e 6,8 s (acceso) per passo, ma un passo comprende anche il tool e una risposta con più contesto; il confronto a coppie `cinema+X` contro `X` solo sulla stessa domanda dà da 0,0 s (P06) a 12 s (X02, n=1). Il tempo risparmiato è quindi un **intervallo largo [S]**.",
        "",
        "## Passi successivi al primo, per classe [C]",
        f"Passi dopo il primo (ognuno costa almeno una chiamata `_plan_next`): **{s['next_plan_calls_lower_bound']}**. A (richiesti e indipendenti) {a} · B (condizionati) {b} · C (argomenti da risultati) {c} · D (non richiesti dalla domanda) {d} · U (non dichiarati) {u}.",
        "",
        "| Domanda | Classi dei passi successivi (3 ripetizioni) |",
        "|---|---|",
        *[f"| {k} | {', '.join(f'{c}×{n}' for c, n in v.items())} |" for k, v in s["by_key"].items()],
        "",
        "## Intervento 3 — passi già pianificati eseguiti senza `_plan_next`",
        f"- Candidati: la classe A, **{a}** passi su {s['next_plan_calls_lower_bound']} [C]. Risparmio: **{a} chiamate di planner** (−{a / max(s['next_plan_calls_lower_bound'], 1) * 100:.0f} % dei passi successivi), **0 chiamate esterne** (i tool partono comunque), {seconds(a, 0.0, PER_STEP_REGRESSION[1])} su {s['wall_total']} s ({a * 0 / s['wall_total'] * 100:.1f}-{a * PER_STEP_REGRESSION[1] / s['wall_total'] * 100:.1f} %) [S].",
        "- Non applicabile ai passi B, C e D: dipendono dal risultato o non servono.",
        "- **Costo non simulabile**: il primo planner dovrebbe scrivere gli argomenti di TUTTI i passi (lo schema di TMDb è 12.232 caratteri; un argomento sbagliato fa rifiutare l'intera richiesta). L'output cresce e il rischio si sposta sulla prima chiamata. Contraddice la scelta D7 solo se i passi diventano paralleli: qui restano in sequenza.",
        "- **Rischio DB-first**: la stessa meccanica, applicata a un passo D (E05), lo renderebbe obbligatorio. Va limitata ai dati che il DB non ha.",
        "",
        "## Intervento 4b — OMDb per più titoli in un passo",
        f"- Turni con ≥2 passi OMDb (DB acceso): {len(s['omdb_turns'])} ({', '.join(f'{k} r{r}: {n} passi, {w:.0f} s' for k, r, n, w in s['omdb_turns'])}). Risparmio: **{o} chiamate di planner**, **0 richieste HTTP** (stessi titoli, stesso costo di budget), {seconds(o, 0.0, PER_STEP_REGRESSION[1])} [S]. Un solo caso di domanda (B13) con 3 ripetizioni: campione piccolo.",
        "- Completezza: invariata se tutti i titoli sono elaborati; il budget di 10 richieste per turno copre 5 titoli per titolo (2 richieste ciascuno), 10 per id. Ogni titolo deve riportare il proprio stato (ambiguo, non trovato) invece di fallire insieme agli altri.",
        "",
        "## Intervento 4a — meno completamenti per campi `partial`",
        f"- Passi interessati: i premi di una persona (E06, P03, P04), **{p}** esecuzioni con un passo Wikipedia dopo `cinema_sql`. Risparmio teorico: {p} chiamate di planner e {p} passi Wikipedia (le richieste HTTP registrate sono poche per la cache del tool: non misurabile qui).",
        "- **Completezza persa [M]**: `awards` di Christopher Nolan con `award: Oscar` dà 6 risultati (5 candidature, 1 vittoria: regia di *Oppenheimer*); la vittoria come produttore del miglior film (*Oppenheimer*) non c'è, quindi «quanti Oscar ha vinto» direbbe 1 invece di 2. Denis Villeneuve: 1 candidatura (*Arrival*, regia); manca *Dune* come miglior film [conoscenza generale, non verificata con una fonte in questa sessione]. Dato noto già in `PHASE5_REPORT.md` §6.2.",
        "- Il campo `partial` con righe presenti NON significa «completo»: soglia sulla sola presenza di righe = risposte sbagliate con tono sicuro. **Da scartare** come regola generale. Resta possibile togliere il completamento solo quando la richiesta non riguarda il totale o l'elenco (es. «ha vinto un Oscar per la regia?»), ma questo è un giudizio del planner e non una soglia: nessun guadagno certo.",
        "",
        "## Passi extra non richiesti (classe D) — osservazione",
        f"- {d} passi D: un passo `cinema_sql` prima di TMDb dove la domanda è di TMDb (E05, E08) (solo E05 è rimasto D). X07 NON è un passo superfluo: era stato classificato D per errore, e controllando il database reale la filmografia solo-serie di Nolan è vuota (`no_credits_in_catalogue`, `follow_up` verso TMDb), quindi il passo TMDb è il ripiego previsto di un risultato vuoto (B). Confronto a coppie [M]: X07 `cinema>tmdb` 15,2 s contro `tmdb` 9,8 s (n=3, ma `tmdb` da solo non può sapere che il locale è vuoto); E05 15,0 s (n=1) contro 7,0 s; stesso percorso su P06: 10,3 contro 10,3 s. Qui il guadagno possibile è nella regola di routing (1g contro 1), non nel ciclo.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    s = simulate()
    text = render(s)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    print(json.dumps({k: s[k] for k in ("transitions", "omdb_saved", "awards_person_steps")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
