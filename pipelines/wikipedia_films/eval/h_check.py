"""Category H (contradictory requests): does the answer declare the contradiction and avoid inventing a solution?

    AB_SET=main python -m pipelines.wikipedia_films.eval.h_check"""
from __future__ import annotations

from pydantic import BaseModel

from ..retrieval import llm
from .ab import CASES, jl_read, jl_write, pmap


class H(BaseModel):
    declares_contradiction: bool
    serves_only_coherent_part: bool
    invents_a_solution: bool
    asks_clarification: bool
    reason: str


INSTR = ("A user sent a request that contains a contradiction. Read the answer given. Decide: does it say the request is contradictory/impossible as asked "
         "(declares_contradiction); does it serve only a coherent reading and say which (serves_only_coherent_part); does it pretend the contradiction does not "
         "exist or present films as satisfying both contradictory parts (invents_a_solution); does it ask the user to clarify (asks_clarification).")


def main():
    answers = [a for a in jl_read("answers.jsonl") if CASES[a["id"]]["category"] == "H"]

    def work(a):
        v = llm.structured(H, INSTR, f"Request: {CASES[a['id']]['question']}\n\nAnswer:\n{a['answer']}")
        return {"id": a["id"], "corpus": a["corpus"], "strategy": a["strategy"], **v.model_dump()}
    out = pmap(work, answers)
    jl_write("h_check.jsonl", out)
    by = {}
    for r in out:
        by.setdefault(f"{r['corpus']}-{r['strategy']}", []).append(r)
    lines = ["# Categoria H: richieste contraddittorie", "", "| Configurazione | Dichiara la contraddizione | Serve solo la parte coerente | Inventa una soluzione | Chiede chiarimento |", "|---|---|---|---|---|"]
    for k, v in sorted(by.items()):
        n = len(v)
        lines.append(f"| {k} | {sum(x['declares_contradiction'] for x in v)}/{n} | {sum(x['serves_only_coherent_part'] for x in v)}/{n} | "
                     f"{sum(x['invents_a_solution'] for x in v)}/{n} | {sum(x['asks_clarification'] for x in v)}/{n} |")
    from .ab import RES
    (RES / "H_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
