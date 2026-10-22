"""Terminal blocks of the turn flow shared by every tool: classifier, query used,
tool choice, unknown steps and the final answer."""
from __future__ import annotations

from .box import print_box


def print_query_used(original: str, used: str, rewritten: bool) -> None:
    if rewritten:
        print(f"\n🔁 Query riscritta con il contesto: {used}")
        print(f"   (domanda originale: {original})")
    else:
        print(f"\n🔁 Query usata: {used}")


def print_classification(is_cinema: bool | None, is_italian: bool | None) -> None:
    def _yes_no(value: bool | None) -> str:
        return "?" if value is None else ("sì" if value else "no")

    print(f"\n🧭 Classificatore: cinema={_yes_no(is_cinema)}, italiano={_yes_no(is_italian)}")


def print_tool_selection(tool_name: str) -> None:
    print(f"\n🛠️  Tool scelto dall'orchestratore: {tool_name}")


def print_generic_step(title: str, data: dict) -> None:
    print_box("⚙️", title)
    for key, value in data.items():
        print(f"  {key}: {value}")


def print_final_answer(answer: str) -> None:
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print("║  🤖  RISPOSTA FINALE DELL'LLM" + " " * 38 + "║")
    print("╚" + "═" * 68 + "╝")
    print()
    print(answer)
    print()
    print("═" * 70)
    print("✅ RAG PIPELINE COMPLETATA")
    print("═" * 70)


def print_compact_notice() -> None:
    print("🧠 Soglia raggiunta: history compattata. 💬 Continuiamo!")
