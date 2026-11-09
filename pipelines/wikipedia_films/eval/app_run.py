"""Runs the questions through the REAL application (`app.handle_query`: classifier, planner, tools, answer), like the web channel does.

    python -m pipelines.wikipedia_films.eval.app_run run --mode new|legacy --set main|extra [--workers 4]
    python -m pipelines.wikipedia_films.eval.app_run judge  --set main|extra     # blind film-level and pairwise judgments with a model other than the one that answers

`legacy` = the application as it was (RAG_BACKEND=legacy equivalent) with the reference flow NOT persisting, so the old collection is never written.
Raw results: eval/results/app_<mode>_<set>.jsonl."""
from __future__ import annotations

import importlib
import json
import random
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pydantic import BaseModel

from ..retrieval import llm
from .ab import JUDGE_FILM, Verdicts, judge_prompt

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "eval" / "results"
JUDGE_MODEL = "gpt-5.5"           # not the model that parses, reorders or answers (gpt-5.6-luna)
COUNTS: dict[int, Counter] = {}


def _patch_counters() -> None:
    """Counts the OpenAI calls of each worker thread (a turn runs entirely in its thread)."""
    from openai.resources.embeddings import Embeddings
    from openai.resources.responses import Responses
    from openai.resources.chat.completions import Completions

    def wrap(cls, name, label):
        original = getattr(cls, name)

        def counted(self, *a, **kw):
            COUNTS.setdefault(threading.get_ident(), Counter())[label] += 1
            return original(self, *a, **kw)
        setattr(cls, name, counted)
    wrap(Responses, "create", "llm"); wrap(Responses, "parse", "llm"); wrap(Completions, "create", "llm"); wrap(Embeddings, "create", "embedding")


def load_cases(name: str) -> list[dict]:
    return json.loads((ROOT / "eval" / ("battery.json" if name == "main" else f"battery_{name}.json")).read_text())["cases"]


def build(mode: str):
    app = importlib.import_module("app")
    if mode == "legacy":
        raise SystemExit("The legacy RAG was removed from the repository (FASE 16): `--mode legacy` cannot run any more. Its historical results stay in eval/results/ "
                         "and `judge` still reads them.")
    return app, app.build_app()


class Obs:
    def __init__(self):
        self.t0 = time.time()
        self.events: list[tuple[float, str]] = []
        self.first_delta: float | None = None

    def step(self, s):
        self.events.append((round(time.time() - self.t0, 2), s.kind))

    def status(self, st):
        self.events.append((round(time.time() - self.t0, 2), f"status:{st}"))

    def answer_delta(self, t):
        if self.first_delta is None and t.strip():
            self.first_delta = round(time.time() - self.t0, 2)


def one(args):
    app, built, case, prefs = args
    obs = Obs()
    COUNTS[threading.get_ident()] = Counter()
    try:
        turn = app.handle_query(built, case["question"], history=[], observer=obs, preferences=prefs)
    except Exception as exc:  # noqa: BLE001
        return {"id": case["id"], "question": case["question"], "error": f"{type(exc).__name__}: {exc}"}
    total = round(time.time() - obs.t0, 2)
    chunks, http = [], 0
    sel = [s for s in turn.steps if s.kind == "selection"]
    if sel:
        for c in sel[-1].data.get("chunks") or []:
            chunks.append({"point_id": c.get("id"), "title": c.get("title"), "year": c.get("release_year"), "genres": [g for g in str(c.get("genres") or "").split("; ") if g],
                           "plot": (c.get("testo") or "")[:1500], "imdb_id": c.get("imdb_id"), "original_title": c.get("original_title")})
    for s in turn.steps:
        http += len(s.data.get("calls") or []) if s.kind.endswith("_calls") else 0
    tool_ms = [s.data.get("elapsed_ms") for s in turn.steps if s.kind == "tool_outcome"]
    tools_args = [s.data.get("arguments") for s in turn.steps if s.kind == "tool_selection"]
    return {"id": case["id"], "category": case.get("category"), "question": case["question"], "answer": turn.answer, "tools": turn.tools,
            "settings_conflicts": turn.settings_conflicts, "seconds": total, "first_delta_seconds": obs.first_delta, "tool_ms": tool_ms,
            "http_calls": http, "openai_calls": dict(COUNTS.get(threading.get_ident(), {})), "films": chunks, "tool_arguments": tools_args,
            "events": obs.events, "language": turn.language}


def run(mode: str, set_name: str, workers: int) -> None:
    _patch_counters()
    app, built = build(mode)
    prefs = importlib.import_module("preferences").defaults()
    cases = load_cases(set_name)
    out = []
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, [(app, built, c, prefs) for c in cases]):
            out.append(r)
    RES.mkdir(parents=True, exist_ok=True)
    (RES / f"app_{mode}_{set_name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    ok = [r for r in out if "error" not in r]
    print(mode, set_name, len(ok), "ok", len(out) - len(ok), "errors; mean seconds", round(sum(r["seconds"] for r in ok) / max(len(ok), 1), 1))


# ------------------------------------------------------------------ judging
class Pair(BaseModel):
    winner: str
    reason: str


def judge(set_name: str) -> None:
    cases = {c["id"]: c for c in load_cases(set_name)}
    runs = {m: {r["id"]: r for r in map(json.loads, (RES / f"app_{m}_{set_name}.jsonl").open()) if "error" not in r} for m in ("new", "legacy")}
    items: dict[int, list] = {}
    for m, rows in runs.items():
        for qid, r in rows.items():
            for f in r["films"]:
                items.setdefault(qid, []).append((m, f))
    rng = random.Random(20261105)

    def work(qid):
        its = items.get(qid, [])
        rng.shuffle(its)
        out = []
        for i in range(0, len(its), 20):
            chunk = its[i:i + 20]
            ps = [{"title": f["title"], "year": f.get("year"), "genres": f["genres"], "plot": f["plot"]} for _, f in chunk]
            v = llm.structured(Verdicts, JUDGE_FILM, judge_prompt(cases[qid], ps), model=JUDGE_MODEL)
            for x in v.films:
                if 0 <= x.index < len(chunk):
                    m, f = chunk[x.index]
                    out.append({"id": qid, "mode": m, "point_id": f["point_id"], "title": f["title"], **x.model_dump(exclude={"index"})})
        return out
    with ThreadPoolExecutor(5) as ex:
        film_rows = [x for chunk in ex.map(work, list(cases)) for x in chunk]
    (RES / f"app_film_judgments_{set_name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in film_rows))

    instr = ("You are an impartial judge comparing two answers (A and B) to the same film request. Films that show an avoided trait, excluded titles and members of an "
             "excluded franchise are violations; an answer that recommends nothing because nothing fits beats one that recommends violations; an answer that declares a "
             "contradiction of the request and serves the coherent part is good. Use your own knowledge of the films. You do not know where either answer comes from. "
             "winner = A, B or tie.")

    def pair(qid):
        a, b = runs["new"].get(qid), runs["legacy"].get(qid)
        if not a or not b:
            return None
        swap = random.Random(f"{qid}-20261105").random() < 0.5
        first, second = (b, a) if swap else (a, b)
        c = cases[qid]
        prompt = (f"Request: {c['question']}\nMust keep: {c['must_keep']}\nMust avoid: {c['must_avoid'] or '-'}\nExcluded titles: {', '.join(c['exclude_titles']) or '-'}\n"
                  f"Excluded franchises: {', '.join(c['avoid_franchise']) or '-'}\n\n=== ANSWER A ===\n{first['answer']}\n\n=== ANSWER B ===\n{second['answer']}")
        v = llm.structured(Pair, instr, prompt, model=JUDGE_MODEL)
        w = v.winner.strip().upper()
        real = "tie" if w not in ("A", "B") else ("legacy" if (w == "A") == swap else "new")
        return {"id": qid, "winner": real, "reason": v.reason, "a_is": "legacy" if swap else "new"}
    with ThreadPoolExecutor(5) as ex:
        pairs = [p for p in ex.map(pair, list(cases)) if p]
    (RES / f"app_pairwise_{set_name}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in pairs))
    print(len(film_rows), "film judgments;", Counter(p["winner"] for p in pairs))


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else ""
    opts = dict(zip(argv[1::2], argv[2::2]))
    if cmd == "run":
        run(opts.get("--mode", "new"), opts.get("--set", "main"), int(opts.get("--workers", 4)))
    elif cmd == "judge":
        judge(opts.get("--set", "main"))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
