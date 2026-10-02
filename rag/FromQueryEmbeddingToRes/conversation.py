from __future__ import annotations

from openai import OpenAI


def _compact_history(history: list[dict], runtime_config: dict, openai_client: OpenAI) -> list[dict]:
    transcript_lines = []
    for msg in history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        transcript_lines.append(f"[{role}]\n{content}")
    transcript = "\n\n".join(transcript_lines)

    prompt = (
        "Compatta questa conversazione per uso operativo nei prossimi turni.\n"
        "Mantieni solo informazioni ancora valide o aperte.\n"
        "La risposta deve avere le sezioni richieste e niente altro.\n\n"
        f"{transcript}"
    )

    response = openai_client.responses.create(
        model=runtime_config["conversation"]["compact_model"],
        instructions=runtime_config["conversation"]["compact_instructions"],
        input=[{"role": "user", "content": prompt}],
    )

    compacted = response.output_text.strip()
    return [
        {
            "role": "system",
            "content": (
                "Memoria conversazione compatta. "
                "Usa questa memoria per mantenere continuita.\n\n"
                f"{compacted}"
            ),
        }
    ]


def _rewrite_query_with_history(
    query: str,
    history: list[dict],
    runtime_config: dict,
    openai_client: OpenAI,
) -> str:
    if not history:
        return query

    recent_history = history[-8:]
    transcript_lines = []
    for msg in recent_history:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        transcript_lines.append(f"[{role}] {content}")

    prompt = (
        "Riscrivi la nuova richiesta utente in una query autonoma per retrieval RAG.\n"
        "Usa la cronologia solo se serve a risolvere riferimenti impliciti.\n"
        "Non inventare fatti, non rispondere alla domanda.\n"
        "Output: solo la query riscritta, una riga.\n\n"
        "Cronologia recente:\n"
        + "\n".join(transcript_lines)
        + "\n\nNuova richiesta utente:\n"
        + query
    )

    response = openai_client.responses.create(
        model=runtime_config["generation"]["model"],
        input=[{"role": "user", "content": prompt}],
    )

    rewritten = response.output_text.strip()
    return rewritten or query
