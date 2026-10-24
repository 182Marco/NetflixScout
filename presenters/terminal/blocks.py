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


def print_tool_selection(tool_name: str) -> None:
    print(f"\n🛠️  Tool scelto dall'orchestratore: {tool_name}")


def print_planning(parts: list[dict], tools: list[str], pending: list[dict], stop_reason: str) -> None:
    print("\n🧩 Pianificazione del turno")
    for part in parts:
        print(f"  parte: {part.get('part')} → {part.get('tool')}")
    print(f"  tool eseguiti: {', '.join(tools) or 'nessuno'}")
    if pending:
        print("  non eseguite: " + "; ".join(f"{p.get('part')} ({p.get('tool')})" for p in pending))
    print(f"  stop: {stop_reason}")


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


def print_compact_notice() -> None:
    print("🧠 Soglia raggiunta: history compattata. 💬 Continuiamo!")
