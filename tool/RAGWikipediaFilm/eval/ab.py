"""A/B evaluation of the old RAG (`netflix_scout`) against the new one (`wikipedia_films_it_v3`) on `eval/battery.json`.

    python -m tool.RAGWikipediaFilm.eval.ab retrieve       # every strategy on both corpora (+ the old pipeline as the application runs it)
    python -m tool.RAGWikipediaFilm.eval.ab judge          # film-level blind judgments (system-agnostic: each film judged once per question)
    python -m tool.RAGWikipediaFilm.eval.ab answers        # same answer prompt and model over each system's evidence
    python -m tool.RAGWikipediaFilm.eval.ab pairwise       # blind, order-randomised A/B judgments of the answers
    python -m tool.RAGWikipediaFilm.eval.ab report         # aggregates → eval/results/REPORT.md and summary.json

Everything raw is kept in eval/results/*.jsonl. LLM calls and embeddings are cached on disk (eval/cache) so a re-run is reproducible."""
from __future__ import annotations

import hashlib
import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel, Field

from ..retrieval import llm, parser, strategies as S
from ..retrieval.corpus import Film, new_corpus, norm, old_corpus

import os

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "eval" / "results"
SET = os.environ.get("AB_SET", "main")
JUDGE_MODEL = os.environ.get("AB_JUDGE_MODEL", llm.LLM_MODEL)     # set to another model to judge with something other than the parser/answer model      # "main": the 62 questions of eval/battery.json; "extra": the supplementary battery_extra.json
PREFIX = "" if SET == "main" else f"{SET}_"
BATTERY = json.loads((ROOT / "eval" / ("battery.json" if SET == "main" else f"battery_{SET}.json")).read_text())
CASES = {c["id"]: c for c in BATTERY["cases"]}
K = 5
WORKERS = 6
STRATS_BOTH = ["S0", "S1", "S2n", "S3", "S3b", "S4", "S5", "S6"]
STRATS_NEW_ONLY = ["S2f"]
if SET == "extra":
    STRATS_BOTH = ["S0", "S5f", "S6f"]
    STRATS_NEW_ONLY = []
if SET == "opt2":      # the winning family (gpt-5.6-sol without reasoning) with other pool sizes and plot lengths
    STRATS_BOTH = ["S6", "X4", "X5", "X6", "X7", "X8"]
    STRATS_NEW_ONLY = []
if SET == "opt":      # latency / quality variants of the LLM reorder, NEW corpus only, same 62 questions
    STRATS_BOTH = ["S5", "S6", "V1", "V2", "V3", "V4", "V5", "V6", "V7", "V8", "V9", "V10", "C1", "W1", "W2", "W3", "W4", "W5", "W6", "X1", "X2", "X3", "X4"]
    STRATS_NEW_ONLY = []
if SET == "wide":      # S6 with a rerank pool of 50 instead of 25 (same 62 questions)
    STRATS_BOTH = ["S6w"]
    STRATS_NEW_ONLY = []
ANSWER_CONFIGS = [("new", "S0"), ("old", "S0"), ("new", "S5"), ("old", "S5"), ("new", "S6"), ("old", "S6"), ("old", "NATIVE")]
if SET == "extra":
    ANSWER_CONFIGS = [("new", "S0"), ("old", "S0"), ("new", "S5f"), ("old", "S5f"), ("new", "S6f"), ("old", "S6f"), ("old", "NATIVE")]
PAIRS = [(("new", "S0"), ("old", "S0")), (("new", "S5"), ("old", "S5")), (("new", "S6"), ("old", "S6")), (("new", "S6"), ("old", "NATIVE"))]


if SET == "extra":
    PAIRS_EXTRA = [(("new", "S0"), ("old", "S0")), (("new", "S5f"), ("old", "S5f")), (("new", "S6f"), ("old", "S6f")), (("new", "S6f"), ("old", "NATIVE"))]


def jl_read(name: str) -> list[dict]:
    p = RES / (PREFIX + name)
    return [json.loads(l) for l in p.open(encoding="utf-8")] if p.exists() else []


def _pairs():
    return PAIRS_EXTRA if SET == "extra" else PAIRS


def jl_write(name: str, rows: list[dict]) -> None:
    RES.mkdir(parents=True, exist_ok=True)
    (RES / (PREFIX + name)).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def pmap(fn, items, workers=WORKERS):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))


def film_row(f: Film) -> dict:
    return {**f.brief(), "plot": f.plot[:1500], "directors": f.directors[:3], "cast": f.cast[:5]}


# ------------------------------------------------------------------ retrieve
def old_native(question: str) -> dict:
    """The old pipeline exactly as the application runs it (parser, Cohere / LLM rerank), but WITHOUT the reference flow:
    that flow writes TMDb films into the collection, which this evaluation must never do."""
    import importlib   # by name: this offline harness reads the application, which the tool packages must not import statically
    app = importlib.import_module("app")
    RagTool = importlib.import_module("tool.rag.FromQueryEmbeddingToRes.tool_interface").RagTool
    cfg = app.build_runtime_config({"rag": {"backend": "legacy"}})["rag"]
    tool = RagTool(config=cfg, reference_flow=None)
    for attempt in range(6):
        try:
            res = tool.run(query=question, params={"k_finale": K})
            break
        except Exception as exc:  # noqa: BLE001  (Cohere trial key: 10 calls a minute)
            if attempt == 5:
                raise
            time.sleep(20 * (attempt + 1))
    films = []
    for c in res["chunks"][:K]:
        year = c.get("release_year")
        films.append(Film(str(c.get("id")), c.get("title") or "", None, int(str(year)[:4]) if year and str(year)[:4].isdigit() else None,
                          [g.strip() for g in str(c.get("genres") or "").split(";") if g.strip()], c.get("testo") or "", [], [], [], None, False,
                          float(c.get("score") or 0)))
    return {"films": films, "trace": {"engine": res["trace"][1]["data"]["backend"]}}


def retrieve_one(job):
    qid, corpus_key, strat = job
    case = CASES[qid]
    corpus = new_corpus() if corpus_key == "new" else old_corpus()
    t = time.time()
    try:
        if strat == "NATIVE":
            out = old_native(case["question"])
            sig = None
        else:
            signals = parser.parse(case["question"])
            ctx = S.build_context(corpus, signals)
            fn = S.STRATEGIES[strat]
            out = fn(ctx, S.K, request=case["question"]) if strat.startswith(("S6", "V", "C1")) else fn(ctx, S.K)
            if out is None:
                return None
            out["trace"] = {**out["trace"], "coverage": ctx.coverage, "contradictory": signals.contradictory}
        return {"id": qid, "corpus": corpus_key, "strategy": strat, "seconds": round(time.time() - t, 2),
                "films": [film_row(f) for f in out["films"]], "trace": out["trace"]}
    except Exception as exc:  # noqa: BLE001
        return {"id": qid, "corpus": corpus_key, "strategy": strat, "error": f"{type(exc).__name__}: {exc}", "films": [], "trace": {}}


def cmd_retrieve():
    corpora = ("new",) if SET in ("opt", "opt2") else ("new", "old")
    jobs = [(q, c, s) for q in CASES for c in corpora for s in STRATS_BOTH] + [(q, "new", s) for q in CASES for s in STRATS_NEW_ONLY]
    pmap(lambda q: parser.parse(CASES[q]["question"]), list(CASES))   # parse once up front (cached) so the workers do not repeat it
    rows = [r for r in pmap(retrieve_one, jobs) if r]
    native = []
    for q in (CASES if SET in ("main", "extra") else []):  # sequential: the Cohere trial key allows 10 calls a minute
        native.append(retrieve_one((q, "old", "NATIVE")))
    jl_write("retrieval.jsonl", rows + native)
    parsed = [{"id": q, "question": CASES[q]["question"], "signals": parser.parse(CASES[q]["question"]).model_dump()} for q in CASES]
    jl_write("parsed_signals.jsonl", parsed)
    print(len(rows) + len(native), "retrievals;", sum(1 for r in rows + native if r.get("error")), "errors;", llm.USAGE)


# ------------------------------------------------------------------ film-level blind judgments
class FilmVerdict(BaseModel):
    index: int
    matches_positive: bool = Field(description="the film clearly has the wanted genre and characteristics")
    shows_avoid: bool = Field(description="the film shows ANY of the things the user wants to avoid (in its plot or as you know the film)")
    is_excluded: bool = Field(description="it is an excluded title, or a sequel/prequel/remake/spin-off of an excluded title or franchise")
    genre_ok: bool = Field(description="it belongs to the main genre that was requested, whatever its other traits")
    reason: str = Field(description="one short sentence in English")


class Verdicts(BaseModel):
    films: list[FilmVerdict]


JUDGE_FILM = ("You are a strict, impartial film expert judging candidate films for a recommendation request. You see the request, what the film must keep, "
              "what it must avoid, and the films to exclude. For each candidate decide the four booleans using the plot given AND your own knowledge of the film. "
              "A film that has ANY avoided trait is a violation (shows_avoid=true) even if it is otherwise a perfect match for the positive part and even if it has "
              "nothing to do with the reference film. A film without the avoided trait that has the wanted characteristics is pertinent even if its story is very "
              "different from the reference. Judge only the film, never where it comes from. If a trait to avoid is only marginal in the film, say false. "
              "Return one verdict per candidate, with its index.")


def judge_prompt(case: dict, items: list[dict]) -> str:
    head = (f"Request: {case['question']}\nMust keep: {case['must_keep']}\nMust avoid: {case['must_avoid'] or '-'}\n"
            f"Excluded titles: {', '.join(case['exclude_titles']) or '-'}\nExcluded franchises: {', '.join(case['avoid_franchise']) or '-'}\n")
    body = "\n\n".join(f"[{i}] {it['title']}" + (f" ({it['year']})" if it.get("year") else "") + f" | genres: {', '.join(it['genres'][:5])}\nPlot: {it['plot'][:900]}"
                       for i, it in enumerate(items))
    return head + "\nCandidates:\n" + body


def cmd_judge():
    rows = jl_read("retrieval.jsonl")
    per_q: dict[int, dict[tuple, dict]] = {}
    for r in rows:
        for f in r["films"]:
            per_q.setdefault(r["id"], {})[(r["corpus"], f["point_id"])] = f
    jobs = []
    rng = random.Random(20261104)
    for qid, films in per_q.items():
        keys = sorted(films)
        rng.shuffle(keys)
        for i in range(0, len(keys), 20):
            jobs.append((qid, keys[i:i + 20]))

    def work(job):
        qid, keys = job
        items = [per_q[qid][k] for k in keys]
        v = llm.structured(Verdicts, JUDGE_FILM, judge_prompt(CASES[qid], items), model=JUDGE_MODEL)
        out = {}
        for x in v.films:
            if 0 <= x.index < len(keys):
                out[keys[x.index]] = x
        return [{"id": qid, "corpus": k[0], "point_id": k[1], **out[k].model_dump(exclude={"index"})} for k in keys if k in out]
    out = [x for chunk in pmap(work, jobs) for x in chunk]
    jl_write("film_judgments.jsonl", out)
    print(len(out), "film judgments for", sum(len(v) for v in per_q.values()), "distinct films;", llm.USAGE)


# ------------------------------------------------------------------ answers
class Answer(BaseModel):
    answer: str
    recommended: list[int] = Field(description="numbers of the evidence films you recommend (the [n] of the list)")


ANSWER_INSTR = ("Sei un assistente cinematografico. Rispondi in italiano usando SOLO i film dell'elenco di evidenza (titolo, anno, generi, trama). "
                "Consiglia al massimo 5 film pertinenti alla richiesta, rispettando le esclusioni. Se un film dell'elenco viola un'esclusione, appartiene a una saga "
                "esclusa, è un film citato o non è pertinente, NON consigliarlo. Se la richiesta contiene una contraddizione, dichiarala e servi solo la parte coerente. "
                "Se nessun film dell'elenco è adatto, dillo senza inventare titoli. Per ogni film consigliato una frase sul perché. Non nominare fonti o database. "
                "Massimo 150 parole. In `recommended` metti i numeri [n] dei film che consigli.")


def evidence_text(films: list[dict]) -> str:
    return "\n\n".join(f"[{i + 1}] {f['title']}" + (f" ({f['year']})" if f.get("year") else "") + f" | generi: {', '.join(f['genres'][:4])}\n{f['plot'][:500]}"
                       for i, f in enumerate(films))


def cmd_answers():
    ret = {(r["id"], r["corpus"], r["strategy"]): r for r in jl_read("retrieval.jsonl")}
    jobs = [(q, c, s) for q in CASES for c, s in ANSWER_CONFIGS if (q, c, s) in ret and ret[(q, c, s)]["films"]]

    def work(job):
        q, c, s = job
        r = ret[job]
        a = llm.structured(Answer, ANSWER_INSTR, f"Richiesta: {CASES[q]['question']}\n\nEvidenza:\n{evidence_text(r['films'])}")
        rec = [r["films"][i - 1]["point_id"] for i in a.recommended if 1 <= i <= len(r["films"])]
        return {"id": q, "corpus": c, "strategy": s, "answer": a.answer, "recommended_point_ids": rec, "recommended_titles": [r["films"][i - 1]["title"] for i in a.recommended if 1 <= i <= len(r["films"])]}
    out = pmap(work, jobs)
    jl_write("answers.jsonl", out)
    print(len(out), "answers;", llm.USAGE)


# ------------------------------------------------------------------ pairwise blind judgments
class Scores(BaseModel):
    respects_exclusions: int = Field(description="1-5: no recommended film shows an avoided trait or is an excluded title/franchise")
    pertinence: int = Field(description="1-5: the recommended films have the wanted genre and characteristics")
    honesty: int = Field(description="1-5: no invented facts; contradictions and missing matches are declared")
    usefulness: int = Field(description="1-5: overall usefulness to the user")


class Pair(BaseModel):
    winner: str = Field(description="A, B or tie")
    a: Scores
    b: Scores
    reason: str


JUDGE_PAIR = ("You are an impartial judge comparing two answers (A and B) to the same film request. Judge with the SAME criteria the request implies: films that "
              "show an avoided trait, excluded titles and members of an excluded franchise are violations, even if otherwise great matches; an answer that "
              "recommends nothing because nothing fits is better than one that recommends violations. Use your own knowledge of the films. You do not know "
              "where either answer comes from and must not guess. Answer winner = A, B or tie.")


def cmd_pairwise():
    tag = os.environ.get("AB_PAIR_TAG", "")      # a second pass with another random order, to measure how stable the judge is
    ans = {(a["id"], a["corpus"], a["strategy"]): a for a in jl_read("answers.jsonl")}
    ret = {(r["id"], r["corpus"], r["strategy"]): r for r in jl_read("retrieval.jsonl")}
    jobs = [(q, p) for q in CASES for p in _pairs()]

    def work(job):
        q, (x, y) = job
        ax, ay = ans.get((q, *x)), ans.get((q, *y))
        if not ax or not ay:
            return None
        rng = random.Random(f"{q}-{x}-{y}-20261104{tag}")
        swap = rng.random() < 0.5
        first, second = (ay, ax) if swap else (ax, ay)

        def desc(a):
            r = ret[(a["id"], a["corpus"], a["strategy"])]
            by = {f["point_id"]: f for f in r["films"]}
            cites = "; ".join(f"{by[p]['title']} ({by[p]['year']}): {by[p]['plot'][:300]}" for p in a["recommended_point_ids"] if p in by)
            return f"{a['answer']}\n[Recommended films with plot excerpts: {cites or 'none'}]"
        c = CASES[q]
        prompt = (f"Request: {c['question']}\nMust keep: {c['must_keep']}\nMust avoid: {c['must_avoid'] or '-'}\nExcluded titles: {', '.join(c['exclude_titles']) or '-'}\n"
                  f"Excluded franchises: {', '.join(c['avoid_franchise']) or '-'}\n\n=== ANSWER A ===\n{desc(first)}\n\n=== ANSWER B ===\n{desc(second)}")
        v = llm.structured(Pair, JUDGE_PAIR + (f' (pass {tag})' if tag else ''), prompt, model=JUDGE_MODEL)
        w = v.winner.strip().upper()
        w = "tie" if w not in ("A", "B") else w
        # un-swap: report the winner as the system of `x` or `y`
        sysx, sysy = list(x), list(y)
        real = {"A": (sysy if swap else sysx), "B": (sysx if swap else sysy)}
        winner = "tie" if w == "tie" else "/".join(real[w])
        sa, sb = v.a.model_dump(), v.b.model_dump()
        score_x = sb if swap else sa
        score_y = sa if swap else sb
        return {"id": q, "pair": ["/".join(x), "/".join(y)], "a_is": "/".join(y if swap else x), "winner": winner, "scores": {"/".join(x): score_x, "/".join(y): score_y},
                "reason": v.reason}
    out = [r for r in pmap(work, jobs) if r]
    jl_write(f"pairwise{tag}.jsonl", out)
    print(len(out), "pairwise judgments;", llm.USAGE)


def main(argv):
    cmd = argv[0] if argv else ""
    fn = {"retrieve": cmd_retrieve, "judge": cmd_judge, "answers": cmd_answers, "pairwise": cmd_pairwise}.get(cmd)
    if cmd == "report":
        from .report import main as rep
        return rep()
    if not fn:
        print(__doc__); return 2
    fn()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
