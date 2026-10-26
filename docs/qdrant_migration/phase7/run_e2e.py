"""Phase 7 runner: real LLM, embedding, rerank and TMDb calls (PAID). Refuses to start without authorization.

    PHASE7_AUTHORIZED=yes VECTORSTORE_ENGINE=qdrant python docs/qdrant_migration/phase7/run_e2e.py --out DIR
Writes one JSON per question (answer, tools, steps, seconds); judging against criteria.md is done afterwards.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
PAUSE_SECONDS = 30


def classify(record: dict, question: dict) -> tuple[str, list[str]]:
    """Mechanical pre-classification (never a verdict: the judging in criteria.md is done by a person).

    error = the turn raised; missed = no answer or no tool where one was expected; partial = a tool error/empty
    outcome or a silent fallback happened; completed = nothing mechanical went wrong. Errors are never successes.
    """
    if "error" in record:
        return "error", [record["error"]]
    reasons: list[str] = []
    steps = record.get("steps") or []
    if not str(record.get("answer") or "").strip():
        return "missed", ["empty_answer"]
    if question.get("kind") == "off_topic":
        return ("completed", []) if not record.get("tools") else ("partial", ["tool_used_on_off_topic"])
    if not record.get("tools"):
        return "missed", ["no_tool_used"]
    for step in steps:
        data = step.get("data") or {}
        if step.get("kind") == "planning" and data.get("fallbacks"):
            reasons += [f"fallback:{f}" for f in data["fallbacks"]]
        if step.get("kind") == "tool_outcome" and data.get("status") in ("error", "empty"):
            reasons.append(f"tool_{data['status']}:{data.get('tool')}:{data.get('reason')}")
    return ("partial", reasons) if reasons else ("completed", [])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--questions", default=str(Path(__file__).with_name("questions.json")))
    args = ap.parse_args(argv)
    if os.environ.get("PHASE7_AUTHORIZED") != "yes":
        sys.stderr.write("Refused: this run calls OpenAI, Cohere and TMDb (paid). Set PHASE7_AUTHORIZED=yes only with the owner's authorization.\n")
        return 2
    from openai import OpenAI

    import app as app_module

    application = app_module.build_ready_app()
    if application["config"]["rag"]["vectorstore"].get("engine") != "qdrant":
        sys.stderr.write("Refused: phase 7 tests the Qdrant engine; set VECTORSTORE_ENGINE=qdrant.\n")
        return 2
    if application["config"]["catalog"]["enabled"]:
        sys.stderr.write("Refused: the catalog must be off for the main phase 7 questions.\n")
        return 2
    client = OpenAI()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    histories: dict[str, list] = {}
    results: list[dict] = []
    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    for position, question in enumerate(questions):
        history = histories.get(question.get("after", ""), [])
        started = time.time()
        try:
            turn = app_module.handle_query(application, question["text"], list(history), client)
            record = {"answer": turn.answer, "tools": turn.tools, "steps": [{"kind": s.kind, "data": s.data} for s in turn.steps]}
            histories[question["id"]] = turn.history
        except Exception as exc:  # noqa: BLE001
            record = {"error": f"{type(exc).__name__}: {exc}"[:300]}
        record["auto_class"], record["auto_reasons"] = classify(record, question)
        results.append({"id": question["id"], "auto_class": record["auto_class"], "reasons": record["auto_reasons"]})
        record |= {"engine": "qdrant", "question": question, "seconds": round(time.time() - started, 1)}
        (out / f"{question['id']}.json").write_text(json.dumps(record, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        if position < len(questions) - 1:
            time.sleep(PAUSE_SECONDS)
    counts = {c: sum(1 for r in results if r["auto_class"] == c) for c in ("completed", "partial", "missed", "error")}
    (out / "summary.json").write_text(json.dumps({"counts": counts, "results": results,
                                                  "note": "mechanical pre-classification, not a verdict"}, indent=1), encoding="utf-8")
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
