"""A/B of the RAG retrieval parameters: configured defaults vs the planner's choice (costs credits).

History: run with search_mode, k_largo, fetch_k and genre_boost in the planner schema (2026-10-24,
2 runs); they showed no gain beyond k_finale and were removed. Kept to re-test new parameters.

Per question: one planner call, then `run_rag` twice (defaults, planner parameters), each with
one signal-parser call and one Cohere rerank. Objective measures only: films returned vs
asked, constraint statuses of the final films (`constraints.constraint_report`) and, when the
question names a film, its presence in the result. A planner choice counts as better only
when it wins on those measures, not merely when it differs.

    python -m movie_db.harness.evaluation.run_rag_params_eval --live
"""
from __future__ import annotations

import argparse
import time
from dataclasses import dataclass

# Cohere trial keys allow 10 calls/min: one pause per rerank.
PAUSE_SECONDS = 7


@dataclass(frozen=True)
class AbCase:
    question: str
    count: int | None = None  # films asked for
    title: str | None = None  # lowercase fragment of the film the question describes


AB_CASES = (
    AbCase("Dammi 5 film sul rapporto tra un padre e un figlio, malinconici e lenti", count=5),
    AbCase("Consigliami un film sulla solitudine nello spazio", count=1),
    AbCase("Qual è quel film in cui il protagonista si chiama Truman Burbank e vive in uno show televisivo?",
           count=1, title="truman"),
    AbCase("Il film in cui Tom Hanks naufraga su un'isola deserta e parla con un pallone", count=1, title="cast away"),
    AbCase("Consigliami 4 commedie giapponesi di fantascienza degli anni 50", count=4),
    AbCase("Dammi 3 film horror ambientati in un ospedale psichiatrico", count=3),
    AbCase("Un western con un cacciatore di taglie e un vecchio sceriffo"),
    AbCase("Film di guerra sulla prima guerra mondiale visti dalla parte dei soldati tedeschi"),
    AbCase("Cerco 2 film sul tema della memoria che si perde", count=2),
    AbCase("Quel film dove Hannibal Lecter è un cannibale psichiatra", count=1, title="silence of the lambs"),
)


def summarize(result, case: AbCase) -> dict:
    statuses: dict[str, int] = {}
    for check in (result.constraints or {}).get("checks", []):
        for item in check["results"].values():
            statuses[item["status"]] = statuses.get(item["status"], 0) + 1
    titles = [str(c.title or "").lower() for c in result.chunks]
    rank = next((i + 1 for i, t in enumerate(titles) if case.title and case.title in t), None)
    return {
        "returned": len(result.chunks),
        "verified": statuses.get("verified", 0),
        "contradicted": statuses.get("contradicted", 0),
        "title_rank": rank,
        "titles": [c.title for c in result.chunks],
    }


def verdict(default: dict, planned: dict, case: AbCase) -> str:
    """'better', 'worse' or 'same' for the planner arm, on objective measures only."""
    def score(arm: dict) -> tuple:
        count_ok = case.count is None or arm["returned"] == case.count
        found = case.title is None or arm["title_rank"] is not None
        rank = -(arm["title_rank"] or 99) if case.title else 0
        # Rates, not totals: arms with different k_finale are compared on the same footing.
        n = max(arm["returned"], 1)
        if case.title:  # identifying one film: constraint rates say nothing about it
            return (count_ok, found, rank)
        return (count_ok, found, -round(arm["contradicted"] / n, 2), round(arm["verified"] / n, 2), rank)

    a, b = score(planned), score(default)
    return "better" if a > b else "worse" if a < b else "same"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="A/B of RAG retrieval parameters (costs API credits).")
    parser.add_argument("--live", action="store_true", required=True, help="Required: this run costs API credits.")
    args = parser.parse_args(argv)
    del args

    from dotenv import load_dotenv
    from openai import OpenAI

    load_dotenv()
    import app as app_module
    from tool.rag.FromQueryEmbeddingToRes.pipeline import run_rag
    from tool.rag.FromQueryEmbeddingToRes.retrieval_params import resolve_retrieval

    application = app_module.build_app()
    orchestrator = application["orchestrator"]
    orchestrator.client = OpenAI(max_retries=0)
    rag_config = application["config"]["rag"]

    tally = {"better": 0, "worse": 0, "same": 0}
    for case in AB_CASES:
        tool, arguments, standalone = orchestrator._plan_turn(query=case.question, conversation_history=[])
        print(f"\n{case.question}\n   planner: tool={tool} arguments={arguments}")
        if tool != "rag_search":
            print("   skipped: not routed to rag_search")
            continue
        effective, overridden = resolve_retrieval(rag_config["retrieval"], arguments)
        arms = {}
        for name, retrieval in (("default", rag_config["retrieval"]), ("planner", effective)):
            result = run_rag(config={**rag_config, "retrieval": retrieval}, query=standalone)
            arms[name] = summarize(result, case)
            print(f"   {name:8} {arms[name]}")
            time.sleep(PAUSE_SECONDS)
        outcome = "same" if not overridden else verdict(arms["default"], arms["planner"], case)
        tally[outcome] += 1
        print(f"   overridden={sorted(overridden)} -> {outcome}")
    print(f"\nplanner vs defaults: {tally}")


if __name__ == "__main__":
    main()
