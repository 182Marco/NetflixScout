"""Compaction of the conversation history (used by `app.handle_query` once the history grows past `memory_window_size`)."""
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
