"""Semantic quality of the two RAGs for FREE-TEXT requests, through the REAL application path (docs/cinema_db/LIVE_EVALUATION_PLAN.md, part B).

Film  -> `RagTool.run` (backend `wikipedia`: LLM parser -> embedding -> Qdrant with filters/penalty -> LLM reorder), exactly as the orchestrator calls it.
Series-> `SeriesRagTool.run` (same stages on `wikipedia_series_it_v1`), with the OpenAI client replaced only by a RECORDING proxy of the same client.
Nothing in retrieval is stubbed: the proxy only measures (stage, ms, tokens, error). A failure is attributed to the stage that raised it:
parser | embedding | retrieval (Qdrant/filters) | reranking. The parser and the reorder swallow their own errors by design (the tool falls back and notes it); the proxy
still sees the exception, so those are reported too.

    python -m movie_db.harness.evaluation.run_rag_semantic_smoke plan [--set smoke|full]              # offline: cases, calls, token-free estimate
    python -m movie_db.harness.evaluation.run_rag_semantic_smoke validate                             # offline, Qdrant read only: every expected title exists
    RAG_SEMANTIC_AUTHORIZED=yes python -m movie_db.harness.evaluation.run_rag_semantic_smoke run --live --set smoke --label trial   # PAID: 4 requests ~ 12 calls
    RAG_SEMANTIC_AUTHORIZED=yes python -m movie_db.harness.evaluation.run_rag_semantic_smoke run --live --set full --label full     # PAID: 24 requests ~ 72 calls
    python -m movie_db.harness.evaluation.run_rag_semantic_smoke report --label trial [--price MODEL=IN:OUT ...]                      # offline

Results go to `cinema_db/data/rag_semantic/<label>/` (ignored by git): `run.jsonl` (one row per case, written as it happens, resumable) and `summary.json`.
The automatic verdict is only against an ACCEPTABLE set per case (`rag_semantic_cases.json`); a miss means "read the top results", the report prints them.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import statistics
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
CASES_PATH = Path(__file__).with_name("rag_semantic_cases.json")
OUT_ROOT = ROOT / "cinema_db/data/rag_semantic"
AUTH_ENV = "RAG_SEMANTIC_AUTHORIZED"
from cinema_db.harness.candidate import EXPECTED_PATH as CINEMA_DB  # noqa: E402  (the one definition of the schema-4 target)
STAGES = ("parser", "embedding", "retrieval", "reranking")
THRESHOLDS = {"film": 10, "series": 9}  # valid cases out of 12 (full set only)
MAX_CONSECUTIVE_FAILURES = 3
EMBEDDING_USD_PER_MILLION = 0.13  # text-embedding-3-large, the figure recorded in pipelines/wikipedia_series/PROGRESS.md; LLM prices are NOT known here: pass --price


def load_cases(subset: str = "full", only: list[str] | None = None) -> list[dict[str, Any]]:
    cases = json.loads(CASES_PATH.read_text())["cases"]
    if subset == "smoke":
        cases = [c for c in cases if c.get("smoke")]
    if only:
        cases = [c for c in cases if c["id"] in only]
    return cases


# ----------------------------------------------------------------------------------------------------------------------------------------- recording
def _usage_of(usage: Any) -> dict[str, int]:
    if usage is None:
        return {"input": 0, "output": 0, "total": 0}
    pick = lambda *names: next((int(getattr(usage, n)) for n in names if getattr(usage, n, None) is not None), 0)  # noqa: E731
    i, o = pick("input_tokens", "prompt_tokens"), pick("output_tokens", "completion_tokens")
    return {"input": i, "output": o, "total": pick("total_tokens") or i + o}


@dataclass
class Recorder:
    """Every model call made while a case runs: stage, model, milliseconds, tokens, error type. `events` is reset per case."""

    inner: Any = None  # the real OpenAI client (built lazily, only in `run --live`)
    events: list[dict[str, Any]] = field(default_factory=list)

    def reset(self) -> None:
        self.events = []

    def _call(self, stage_of: Callable[[dict], str], fn_name: tuple[str, str]) -> Callable:
        def call(**kwargs: Any) -> Any:
            stage, t0 = stage_of(kwargs), time.perf_counter()
            event = {"stage": stage, "model": kwargs.get("model"), "ok": True, "error": None}
            try:
                target = getattr(self.inner, fn_name[0])
                response = getattr(target, fn_name[1])(**kwargs)
                event["usage"] = _usage_of(getattr(response, "usage", None))
                return response
            except Exception as exc:  # noqa: BLE001  (recorded, then raised again for the tool's own handling)
                event.update(ok=False, error=type(exc).__name__)
                raise
            finally:
                event["ms"] = round((time.perf_counter() - t0) * 1000)
                self.events.append(event)
        return call

    @property
    def client(self) -> Any:
        rec = self

        class _Namespace:
            def __init__(self, **fns: Callable) -> None:
                self.__dict__.update(fns)

        class _Client:
            embeddings = _Namespace(create=rec._call(lambda kw: "embedding", ("embeddings", "create")))
            responses = _Namespace(parse=rec._call(lambda kw: "reranking" if getattr(kw.get("text_format"), "__name__", "") == "Order" else "parser", ("responses", "parse")))

            def __getattr__(self, name: str) -> Any:  # anything else goes straight to the real client
                return getattr(rec.inner, name)
        return _Client()


def real_openai() -> Any:
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv()  # the key comes from .env, as for the application
    return OpenAI(max_retries=2, timeout=90)


# ----------------------------------------------------------------------------------------------------------------------------------------- grading
def norm(text: Any) -> str:
    from tool.rag.film.retrieval.index import norm as _norm
    return _norm(text)


def base_title(text: Any) -> str:
    """The catalogue disambiguates with a trailing qualifier ('Il grande Gatsby (film 2013)', 'Chernobyl (miniserie televisiva)'): compare without it."""
    return norm(re.sub(r"\s*\([^)]*\)\s*$", "", str(text or "")))


def matches(expected: dict[str, Any], item: dict[str, Any]) -> bool:
    """`expected` = {title?, year?, series?, season?, level?}; every key given must agree. Titles are compared normalised, whole."""
    if "title" in expected and norm(expected["title"]) not in {norm(item.get("title")), base_title(item.get("title")), norm(item.get("original_title"))}:
        return False
    if "series" in expected and norm(expected["series"]) not in {norm(item.get("series")), base_title(item.get("series"))}:
        return False
    if "year" in expected and expected["year"] != item.get("year"):
        return False
    if "season" in expected and expected["season"] != item.get("season"):
        return False
    return not ("level" in expected and expected["level"] != item.get("level"))


def _filter_violations(filters: dict[str, Any], items: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for n, it in enumerate(items, start=1):
        year, label = it.get("year"), it.get("title")
        if "year_from" in filters and not (year and year >= filters["year_from"]):
            out.append(f"#{n} {label}: year {year} < {filters['year_from']}")
        if "year_to" in filters and not (year and year <= filters["year_to"]):
            out.append(f"#{n} {label}: year {year} > {filters['year_to']}")
        if "country" in filters and not any(norm(filters["country"]) == norm(c) for c in it.get("countries") or []):
            out.append(f"#{n} {label}: countries {it.get('countries')} lack {filters['country']}")
        if "director" in filters and not any(norm(filters["director"]) in norm(d) for d in it.get("directors") or []):
            out.append(f"#{n} {label}: directors {it.get('directors')} lack {filters['director']}")
        # The retriever filters on the COMPLETE cast (`actor_names_norm`); the shown cast is cut to 8 names, so the complete one is used when the run attached it.
        if "actor" in filters and not any(norm(filters["actor"]) in norm(a) for a in [*(it.get("cast") or []), *(it.get("cast_full") or [])]):
            out.append(f"#{n} {label}: cast lacks {filters['actor']}" + ("" if it.get("cast_full") else " (complete cast not available: only the shown names were checked)"))
        if "level" in filters and it.get("level") != filters["level"]:
            out.append(f"#{n} {label}: level {it.get('level')} != {filters['level']}")
    return out


def grade(case: dict[str, Any], items: list[dict[str, Any]], notes: dict[str, Any]) -> dict[str, Any]:
    """Pure: the automatic verdict of one case from its normalised results and the tool notes."""
    k = int(case.get("k", 5))
    top = items[:k]
    out: dict[str, Any] = {"n_results": len(top)}
    expected = case.get("expect_any") or []
    rank = next((i for i, it in enumerate(top, start=1) if any(matches(e, it) for e in expected)), None) if expected else None
    out["hit_rank"] = rank
    out["forbidden"] = [it["title"] for it in top
                        if any(t in norm(it.get("title")) or t in norm(it.get("original_title")) or t in norm(it.get("series")) for t in map(norm, case.get("forbid_title_contains") or []))
                        or any(norm(t) in norm(d) for t in case.get("forbid_director_contains") or [] for d in it.get("directors") or [])]
    out["filter_violations"] = _filter_violations(case.get("filters") or {}, top)
    checks = {"no_forbidden": not out["forbidden"], "filters": not out["filter_violations"]}
    if case.get("expect_empty"):
        checks["empty"] = not top
    elif expected:
        checks["hit"] = rank is not None
    elif not case.get("expect_note"):
        checks["has_results"] = bool(top)
    if case.get("expect_note"):
        checks["note"] = case["expect_note"] in notes
    out["checks"] = checks
    out["valid"] = all(checks.values())
    return out


def attribute_failure(events: list[dict[str, Any]], exception: str | None) -> str | None:
    """The stage that made the case fail. With an exception: the last model call that failed (the tool swallows a parser error and goes on, so a later embedding error is the
    cause), or retrieval (Qdrant, filters) when no model call failed. Without one: the first model call that failed and was swallowed (parser or reranking), else None."""
    failed = [e["stage"] for e in events if not e["ok"]]
    if exception:
        return failed[-1] if failed else "retrieval"
    return failed[0] if failed else None


# ----------------------------------------------------------------------------------------------------------------------------------------- execution
def film_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"title": c.get("title"), "original_title": c.get("original_title"), "year": int(c["release_year"]) if str(c.get("release_year") or "").isdigit() else None,
             "imdb_id": c.get("imdb_id"), "directors": c.get("directors") or [], "countries": c.get("countries") or [],
             "cast": [x.strip() for x in (c.get("cast") or "").split(";") if x.strip()], "level": "film", "score": c.get("score")}
            for c in result.get("chunks") or []]


def full_cast_lookup(index: Any) -> Callable[[list[str]], dict[str, list[str]]]:
    """imdb id -> every normalised actor name of that film, read from the film collection with the SAME field the retriever filters on
    (`actor_names_norm`). Read only: one `scroll` per call, no model."""
    from qdrant_client import models

    def lookup(imdb_ids: list[str]) -> dict[str, list[str]]:
        ids = sorted({i for i in imdb_ids if i})
        if not ids:
            return {}
        points, _ = index.client.scroll(index.collection, scroll_filter=models.Filter(must=[models.FieldCondition(key="imdb_id", match=models.MatchAny(any=ids))]),
                                        limit=len(ids) * 3, with_payload=["imdb_id", "actor_names_norm"], with_vectors=False)
        return {(p.payload or {}).get("imdb_id"): list((p.payload or {}).get("actor_names_norm") or []) for p in points}
    return lookup


def attach_full_cast(case: dict[str, Any], items: list[dict[str, Any]], lookup: Callable[[list[str]], dict[str, list[str]]] | None) -> None:
    """Only for a case with an actor filter: give each film its complete cast so the check judges what the filter judged. Without `lookup` or an id: unchanged."""
    if lookup is None or "actor" not in (case.get("filters") or {}):
        return
    cast = lookup([it.get("imdb_id") for it in items])
    for it in items:
        if cast.get(it.get("imdb_id")):
            it["cast_full"] = cast[it["imdb_id"]]


def series_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    meta = (result.get("metadata") or {}).get("series_rag") or {}
    return [{"title": i.get("title"), "year": i.get("year"), "imdb_id": i.get("imdb_id"), "level": i.get("level"), "series": i.get("series"), "season": i.get("season"),
             "episode": i.get("episode"), "countries": i.get("countries") or []} for i in meta.get("items") or []]


def _interpretation(result: dict[str, Any]) -> dict[str, Any]:
    """What the parser understood and who ranked: from the tool's own trace (nothing is recomputed). Empty when the tool returned no trace."""
    steps = {step.get("kind"): step.get("data") or {} for step in result.get("trace") or []}
    retrieval = steps.get("retrieval") or {}
    series = steps.get("series_index") or {}
    signals = retrieval.get("signals") or series.get("signals") or {}
    return {"signals": signals, "embedded_text": retrieval.get("embedded_text"), "engine": (steps.get("rerank") or {}).get("backend") or series.get("engine")}


def film_notes(result: dict[str, Any]) -> dict[str, Any]:
    return dict((result.get("metadata") or {}).get("search_notes") or {})


def series_notes(result: dict[str, Any]) -> dict[str, Any]:
    return dict(((result.get("metadata") or {}).get("series_rag") or {}).get("notes") or {})


def build_film_tool() -> Any:
    import app as app_module
    from tool.rag.film.tool import RagTool
    config = app_module.build_runtime_config({"rag": {"film_index": {"expose_imdb_id": True}}})
    return RagTool(config=config["rag"])


def build_series_tool(recorder: Recorder) -> Any:
    import app as app_module
    from tool.rag.series import retrieval as R
    from tool.rag.series.config import load_series_rag_config
    from tool.rag.series.tool import SeriesRagTool
    config = load_series_rag_config(app_module.build_runtime_config({"series_rag": {"enabled": True}})["series_rag"])

    def factories(cfg: Any, usage: Any):  # the factories of the real tool with the recording client instead of a bare OpenAI client
        client = recorder.client
        embed = R.make_embed(cfg.embedding_model, cfg.embedding_dimensions, client=client, on_usage=usage.record)
        parse = R.make_parse(cfg.parser_model, None, client=client, on_usage=usage.record)
        reorder = R.make_reorder(cfg.rerank_model, "none", cfg.rerank_plot_chars, client=client, on_usage=usage.record) if cfg.rerank_enabled else None
        return embed, parse, reorder
    return SeriesRagTool(config=config, factories=factories, expose_imdb_id=True)


@contextlib.contextmanager
def film_client_patched(recorder: Recorder) -> Iterator[None]:
    """The film index takes its OpenAI client from `service.openai_client()` at call time: point it at the recorder for the duration of a case."""
    from tool.rag.film.retrieval import service
    with mock.patch.object(service, "openai_client", lambda: recorder.client):
        yield


def run_case(case: dict[str, Any], tools: dict[str, Any], recorder: Recorder, cinema: Any | None, cast_lookup: Callable[[list[str]], dict[str, list[str]]] | None = None) -> dict[str, Any]:
    recorder.reset()
    params = {"query": case["query"], "k_finale": int(case.get("k", 5))}
    row: dict[str, Any] = {"id": case["id"], "kind": case["kind"], "category": case["category"], "query": case["query"], "k": case.get("k", 5)}
    exception, result, t0 = None, {}, time.perf_counter()
    try:
        if case["kind"] == "film":
            with film_client_patched(recorder):
                result = tools["film"].run(query=case["query"], params=params)
        else:
            result = tools["series"].run(query=case["query"], params={"query": case["query"], "k_final": int(case.get("k", 5))})
    except Exception as exc:  # noqa: BLE001  (a stage raised through the tool: film embedding/Qdrant errors are not swallowed)
        exception = type(exc).__name__
    row["total_ms"] = round((time.perf_counter() - t0) * 1000)
    items = (film_items if case["kind"] == "film" else series_items)(result)
    notes = (film_notes if case["kind"] == "film" else series_notes)(result)
    if case["kind"] == "film":
        attach_full_cast(case, items, cast_lookup)
    if case["kind"] == "series":
        status = (((result.get("metadata") or {}).get("series_rag") or {}))
        if status.get("status") == "error":
            exception = exception or str(status.get("error"))
            row["tool_error"] = {k: v for k, v in status.items() if k != "items"}
    row.update(items=items, notes=notes, events=list(recorder.events), exception=exception, **_interpretation(result))
    row["failed_stage"] = attribute_failure(recorder.events, exception)
    # Stage the tool itself reports it fell back from (parser/reorder errors are swallowed on purpose)
    row["degraded"] = [s for s in ("parser", "reranking") if any(e["stage"] == s and not e["ok"] for e in recorder.events)
                       or (s == "parser" and "parser_failed" in notes) or (s == "reranking" and "reorder_failed" in notes)]
    row["grade"] = grade(case, items, notes)
    row["calls"] = {s: sum(1 for e in recorder.events if e["stage"] == s) for s in ("parser", "embedding", "reranking")}
    row["handoff"] = handoff(cinema, items) if cinema is not None else None
    return row


def handoff(cinema: Any, items: list[dict[str, Any]]) -> dict[str, int]:
    """Local SQLite only (no network, no model): does every IMDb id the RAG returned resolve in `cinema_sql` without ambiguity?"""
    out: dict[str, int] = {}
    for imdb in sorted({i["imdb_id"] for i in items if i.get("imdb_id")}):
        status = cinema.run(query="x", params={"operation": "find_work", "imdb_id": imdb})["metadata"]["cinema_db"]["status"]
        out[status] = out.get(status, 0) + 1
    out["without_imdb_id"] = sum(1 for i in items if not i.get("imdb_id"))
    return out


# ----------------------------------------------------------------------------------------------------------------------------------------- commands
def estimate(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Upper bound of model calls: parser + embedding + reorder per request (the reorder is skipped for title/listing hits and tiny pools; a film citing a film absent from
    the index adds one embedding)."""
    per = {"parser": len(cases), "embedding": len(cases), "reranking": len(cases)}
    return {"requests": len(cases), "film": sum(c["kind"] == "film" for c in cases), "series": sum(c["kind"] == "series" for c in cases), "calls_max": sum(per.values()), "by_stage": per}


def cmd_plan(args: argparse.Namespace) -> int:
    cases = load_cases(args.set, args.only)
    est = estimate(cases)
    for c in cases:
        print(f"  {c['id']:4} {c['kind']:6} {c['category']:22} k={c.get('k', 5)}  {c['query'][:90]}")
    print(f"\n{est['requests']} requests ({est['film']} film, {est['series']} series): at most {est['calls_max']} model calls "
          f"({est['by_stage']['parser']} parser, {est['by_stage']['embedding']} embedding, {est['by_stage']['reranking']} reorder). Nothing was called.")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Offline, Qdrant read only: each expected title (and series) exists in its collection (same comparison as the grader), so a miss in the live run means the retriever,
    not the case."""
    from qdrant_client import QdrantClient, models as qm
    client = QdrantClient(url="http://127.0.0.1:6333", timeout=60)

    def exists(collection: str, e: dict[str, Any], levels: list[str] | None) -> bool:
        words = norm(e.get("title") or e.get("series")).split()
        must = [qm.FieldCondition(key="title_norm", match=qm.MatchText(text=w)) for w in words[:4]]
        if levels:
            must.append(qm.FieldCondition(key="entity_type", match=qm.MatchAny(any=levels)))
        pts = client.scroll(collection, scroll_filter=qm.Filter(must=must), limit=60, with_payload=["title", "original_title", "year"])[0]
        probe = {k: v for k, v in e.items() if k in ("title", "year")} if "title" in e else {"title": e["series"]}
        return any(matches(probe, {"title": p.payload.get("title"), "original_title": p.payload.get("original_title"), "year": p.payload.get("year")}) for p in pts)

    missing, total = 0, 0
    for c in load_cases(args.set, args.only):
        for e in c.get("expect_any") or []:
            total += 1
            if c["kind"] == "film":
                ok = exists("wikipedia_films_it_v3", e, None)
            else:
                ok = exists("wikipedia_series_it_v1", e, ["series"] if "series" in e else ["series", "tv_movie"])
            missing += not ok
            if not ok:
                print(f"  not found  {c['id']}  {e}")
    print(f"{total - missing}/{total} expected entries exist in their collections (a missing one is a case to fix, not a retriever miss). Read only, no model.")
    return 1 if missing else 0


def _done_ids(path: Path) -> set[str]:
    return {json.loads(line)["id"] for line in path.open()} if path.exists() else set()


def cmd_run(args: argparse.Namespace) -> int:
    if not args.live:
        print("Refusing to run: this command calls OpenAI (parser, embedding, reorder). Pass --live and set "
              f"{AUTH_ENV}=yes. `plan` shows what it would do without calling anything.")
        return 2
    if os.environ.get(AUTH_ENV) != "yes":
        print(f"Refusing to run: {AUTH_ENV}=yes is not set (the owner authorises each live part separately).")
        return 2
    cases = load_cases(args.set, args.only)
    out_dir = OUT_ROOT / args.label
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "run.jsonl"
    if args.force and path.exists():
        path.unlink()
    done = _done_ids(path)
    recorder = Recorder(inner=real_openai())
    tools = {"film": build_film_tool(), "series": build_series_tool(recorder)}
    cinema = None
    if not args.no_handoff and CINEMA_DB.is_file():
        from tool.cinema_db.config import CinemaDbConfig
        from tool.cinema_db.tool import CinemaSqlTool
        cinema = CinemaSqlTool(config=CinemaDbConfig(enabled=True, db_path=str(CINEMA_DB), max_queries_per_turn=40, default_limit=10))
    from tool.rag.film.retrieval.adapter import index_for
    import app as app_module
    cast_lookup = full_cast_lookup(index_for(app_module.build_runtime_config({})["rag"]))
    failures = 0
    with path.open("a") as f:
        for c in cases:
            if c["id"] in done:
                print(f"  skip {c['id']} (already in {path.name}; --force to redo)")
                continue
            row = run_case(c, tools, recorder, cinema, cast_lookup)
            row["label"] = args.label
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            f.flush()
            g = row["grade"]
            print(f"  {c['id']:4} {'VALID' if g['valid'] else 'check'}  {row['total_ms']:6} ms  calls {row['calls']}  stage-error={row['failed_stage']}  top: "
                  + " | ".join((i['title'] or '?') + (f" ({i['year']})" if i.get('year') else '') for i in row['items'][:3]))
            failures = failures + 1 if row["failed_stage"] else 0
            if failures >= MAX_CONSECUTIVE_FAILURES:
                print(f"Stopping: {MAX_CONSECUTIVE_FAILURES} cases in a row failed in a model or retrieval stage; fix that first (rows so far are kept).")
                break
    return cmd_report(argparse.Namespace(label=args.label, price=args.price or []))


def parse_prices(specs: list[str]) -> dict[str, tuple[float, float]]:
    out: dict[str, tuple[float, float]] = {}
    for spec in specs:
        m = re.fullmatch(r"([^=]+)=([\d.]+):([\d.]+)", spec)
        if not m:
            raise SystemExit(f"--price expects MODEL=IN:OUT in USD per million tokens, got {spec!r}")
        out[m[1]] = (float(m[2]), float(m[3]))
    return out


def summarize(rows: list[dict[str, Any]], prices: dict[str, tuple[float, float]] | None = None) -> dict[str, Any]:
    """Pure: aggregates of a run. Cost only for models whose price was given (embedding uses the recorded 0.13 USD per million tokens)."""
    prices = prices or {}
    tokens: dict[str, dict[str, int]] = {}
    cost, unpriced = 0.0, set()
    for r in rows:
        for e in r["events"]:
            usage = e.get("usage") or {"input": 0, "output": 0, "total": 0}
            t = tokens.setdefault(e["stage"], {"calls": 0, "input": 0, "output": 0, "total": 0, "ms": 0, "errors": 0})
            t["calls"] += 1
            t["ms"] += e["ms"]
            t["errors"] += not e["ok"]
            for key in ("input", "output", "total"):
                t[key] += usage[key]
            if e["stage"] == "embedding":
                cost += usage["total"] * EMBEDDING_USD_PER_MILLION / 1e6
            elif e.get("model") in prices:
                pin, pout = prices[e["model"]]
                cost += (usage["input"] * pin + usage["output"] * pout) / 1e6
            else:
                unpriced.add(e.get("model"))
    by_kind: dict[str, Any] = {}
    for kind in ("film", "series"):
        sel = [r for r in rows if r["kind"] == kind]
        if not sel:
            continue
        ms = sorted(r["total_ms"] for r in sel)
        ranked = [r["grade"]["hit_rank"] for r in sel if r["grade"]["hit_rank"]]
        by_kind[kind] = {
            "cases": len(sel), "valid": sum(r["grade"]["valid"] for r in sel),
            "hit": sum(r["grade"]["hit_rank"] is not None for r in sel), "mrr_over_hits": round(statistics.mean(1 / x for x in ranked), 3) if ranked else None,
            "forbidden_hits": sum(len(r["grade"]["forbidden"]) for r in sel), "filter_violations": sum(len(r["grade"]["filter_violations"]) for r in sel),
            "stage_errors": {s: sum(r["failed_stage"] == s for r in sel) for s in STAGES if any(r["failed_stage"] == s for r in sel)},
            "degraded": {s: sum(s in r["degraded"] for r in sel) for s in ("parser", "reranking") if any(s in r["degraded"] for r in sel)},
            "latency_ms": {"median": ms[len(ms) // 2], "max": ms[-1]},
            "handoff": _sum_dicts([r["handoff"] for r in sel if r.get("handoff")]),
        }
    return {"cases": len(rows), "by_kind": by_kind, "tokens_by_stage": tokens, "cost_usd_priced_calls": round(cost, 4), "unpriced_models": sorted(m for m in unpriced if m),
            "model_calls": sum(t["calls"] for t in tokens.values())}


def _sum_dicts(dicts: list[dict[str, int]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0) + v
    return out


def cmd_report(args: argparse.Namespace) -> int:
    path = OUT_ROOT / args.label / "run.jsonl"
    if not path.exists():
        print(f"No results at {path}")
        return 1
    rows = [json.loads(line) for line in path.open()]
    summary = summarize(rows, parse_prices(args.price))
    (path.parent / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print("\n== per case")
    for r in rows:
        g = r["grade"]
        print(f"\n{r['id']} [{r['category']}] {'VALID' if g['valid'] else 'CHECK'}  checks={g.get('checks')}  hit_rank={g['hit_rank']}  stage_error={r['failed_stage']} degraded={r['degraded']}")
        print(f"   «{r['query']}»")
        for n, it in enumerate(r["items"][:5], start=1):
            print(f"   {n}. {it.get('series') + ' — ' if it.get('series') else ''}{it.get('title')} ({it.get('year')}) [{it.get('level')}] {it.get('imdb_id') or '-'}")
        for key in ("forbidden", "filter_violations"):
            if g[key]:
                print(f"   !! {key}: {g[key]}")
        if r["notes"]:
            print(f"   notes: {r['notes']}")
    _write_review_sheet(path.parent, rows)
    print("\n== summary")
    for kind, s in summary["by_kind"].items():
        need = THRESHOLDS[kind]
        full = s["cases"] >= 12
        print(f"  {kind}: valid {s['valid']}/{s['cases']}" + (f" (threshold {need}/12: {'OK' if s['valid'] >= need else 'NOT MET'})" if full else " (trial: no threshold applied)")
              + f", hits {s['hit']}, forbidden {s['forbidden_hits']}, filter violations {s['filter_violations']}, median {s['latency_ms']['median']} ms, errors {s['stage_errors']}, degraded {s['degraded']}")
        print(f"     hand-over to cinema_sql: {s['handoff']}")
    print(f"  model calls {summary['model_calls']}; tokens by stage {json.dumps(summary['tokens_by_stage'])}")
    print(f"  cost of the priced calls: {summary['cost_usd_priced_calls']} USD; unpriced models (pass --price MODEL=IN:OUT): {summary['unpriced_models']}")
    return 0


RUBRIC = ("Manual relevance grade of each of the top 5 (blind to the automatic verdict): 2 = clearly what was asked, 1 = partly (right area, wrong detail), "
          "0 = not what was asked or violates an exclusion/filter. A request is RELEVANT if its top 3 contain at least two 2s and no 0 caused by a stated exclusion. "
          "Thresholds of the plan: film >= 10/12 and series >= 9/12 relevant, 0 filter violations, the nonexistent title returns nothing.")


def _write_review_sheet(directory: Path, rows: list[dict[str, Any]]) -> None:
    """`review.md`: every request with what the parser understood, the engine, the top 5 and an empty grade column, for the human judgement the automatic check cannot make."""
    lines = ["# Manual review sheet", "", RUBRIC, ""]
    for r in rows:
        sig = r.get("signals") or {}
        lines += [f"## {r['id']} [{r['category']}] automatic: {'valid' if r['grade']['valid'] else 'CHECK'} (hit rank {r['grade']['hit_rank']})", f"> {r['query']}", "",
                  f"parser: wanted=`{sig.get('positive_it') or sig.get('semantic_query') or r.get('embedded_text') or '-'}` avoid={sig.get('avoid_descriptions_it') or sig.get('negative_signals') or sig.get('avoid_titles') or sig.get('hard_exclusions') or '-'} "
                  f"filters={ {k: v for k, v in {**sig, **(sig.get('filters') or {})}.items() if k in ('year_from', 'year_to', 'countries', 'directors', 'actors', 'rare_terms', 'level', 'series_title')  and v} } engine={r.get('engine')}", "",
                  "| # | result | year | level | imdb | grade 0/1/2 |", "|---|---|---|---|---|---|"]
        for n, it in enumerate(r["items"][:5], start=1):
            lines.append(f"| {n} | {it.get('series') + ' — ' if it.get('series') else ''}{it.get('title')} | {it.get('year')} | {it.get('level')} | {it.get('imdb_id') or '-'} |  |")
        lines.append("")
    (directory / "review.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "validate", "run"):
        p = sub.add_parser(name)
        p.add_argument("--set", choices=("smoke", "full"), default="smoke")
        p.add_argument("--only", nargs="*")
        if name == "run":
            p.add_argument("--live", action="store_true")
            p.add_argument("--label", required=True)
            p.add_argument("--force", action="store_true")
            p.add_argument("--no-handoff", action="store_true")
            p.add_argument("--price", action="append", help="MODEL=IN:OUT, USD per million tokens")
    p = sub.add_parser("report")
    p.add_argument("--label", required=True)
    p.add_argument("--price", action="append", default=[])
    args = ap.parse_args(argv)
    return {"plan": cmd_plan, "validate": cmd_validate, "run": cmd_run, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
