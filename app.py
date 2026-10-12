from __future__ import annotations

import copy
from typing import Any

from openai import OpenAI

from orchestrator import LLMOrchestrator
from presenters import OutputChannel, present, terminal
from rag.FromQueryEmbeddingToRes.chat import _choose_block_language
from rag.FromQueryEmbeddingToRes.conversation import _compact_history
from rag.FromQueryEmbeddingToRes.query_classifier.query_classifier import classify_query_domain
from rag.FromQueryEmbeddingToRes.runtime import _resolve_runtime_config
from rag.FromQueryEmbeddingToRes.models import RerankBackend, SearchMode
from rag.FromQueryEmbeddingToRes.tool_interface import RagTool
from rag.FromQueryEmbeddingToRes.vectorstore import apri_collection
from turn import STEP_CLASSIFICATION, STEP_QUERY_REWRITE, STEP_TOOL_SELECTION, TraceStep, TurnResult

NON_CINEMA_BLOCK_MESSAGES = {
    "it": "Non rispondo a domande non cinematografiche",
    "en": "I do not answer non-film questions",
}

EXIT_COMMANDS = {"exit", "quit"}

CONFIG = {
    "orchestrator": {
        "llm_model": "gpt-5.6-luna",
        "temperature": 0.2,
        "instructions": (
            "Sei l'orchestratore di un sistema multi-tool. "
            "Scegli il tool più adatto alla query e alle informazioni disponibili. "
            "Ritorna solo JSON con chiavi: standalone_query, tool_name, arguments, confidence. "
            "standalone_query è l'ultima richiesta dell'utente riscritta in modo autonomo, "
            "risolvendo con la conversazione precedente i riferimenti impliciti "
            "(es. 'e uno più recente?', 'qualcosa di simile'); non inventare fatti e non rispondere "
            "alla domanda. Se la richiesta è già autonoma, ripetila uguale. "
            "Usa il tool RAG per domande su film, trama, generi, cast e recommendation."
        ),
        "max_iterations": 3,
        "max_execution_time": 30,
        "token_budget": 60000,
        "memory_window_size": 12,
        # Last history messages shown to the domain classifier, so follow-ups are not blocked.
        "classifier_context_messages": 2,
        "allowed_tools": ["rag_search"],
        "required_tools": [],
        "tool_confidence_threshold": 0.6,
        "fallback_tool": "rag_search",
        "verbose": False,
        "conversation": {
            "token_threshold": 40000,
            "compact_model": "gpt-5.6-luna",
            "compact_instructions": (
                "Compatta la conversazione mantenendo continuita operativa. "
                "Produci solo markdown con sezioni: FATTO, DECISIONE, APERTO, IPOTESI. "
                "Includi esclusivamente elementi ancora utili per i prossimi turni. "
                "Rimuovi output rumoroso, duplicazioni, tentativi superati e dettagli obsoleti."
            ),
        },
    },
    "rag": {
        "retrieval": {
            "search_mode": SearchMode.semantic,
            "k_largo": 10,
            "k_finale": 3,
            "fetch_k": 50,
            "genre_boost": 0.15,
            "rrf_costante": 60,
        },
        "rerank": {
            "backend": RerankBackend.cohere,
            "cohere_model": "rerank-v3.5",
            "llm_model": "gpt-5.6-luna",
        },
        "generation": {
            "model": "gpt-5.6-luna",
            "instructions": (
                "Rispondi alla domanda usando solo le informazioni nei documenti del messaggio. "
                "Non cercare su internet. "
                "Non usare id film o markup nella risposta. "
                "Prima del consiglio riporta titolo, anno e genere tra parentesi. "
                "Poi spiega le motivazioni del consiglio con tono informale, caldo e amabile, "
                "citando i passaggi specifici che motivano la scelta. "
                'Se la risposta non e presente nei documenti, rispondi esattamente: "Non lo trovo nei documenti."'
            ),
        },
        "embedding": {
            "backend": "openai",
            "model": "text-embedding-3-small",
        },
        "vectorstore": {
            "collection": "netflix_scout",
            "db_dir": None,
        },
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    result = copy.deepcopy(base)
    if not override:
        return result

    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def build_runtime_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Merge default config with request-specific overrides.

    This keeps default app config in one place while allowing future SSE/web overrides
    to be applied at runtime without changing tool or orchestrator code.
    """
    return _deep_merge(CONFIG, overrides)


def build_app(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    runtime_config = build_runtime_config(overrides)
    orchestrator = LLMOrchestrator(
        config=runtime_config,
        tools=[RagTool(config=runtime_config["rag"])],
    )
    return {
        "config": runtime_config,
        "orchestrator": orchestrator,
    }


def ensure_collection_ready(runtime_rag: dict[str, Any]) -> None:
    collection = apri_collection(
        runtime_rag["vectorstore"]["collection"],
        db_dir=runtime_rag["vectorstore"]["db_dir"],
    )
    if collection.count() == 0:
        raise RuntimeError(
            "Collection is empty. Run `python buildSemanticDb.py --embedding-backend <backend>` before querying."
        )


def handle_query(
    app: dict[str, Any],
    query: str,
    history: list[dict[str, str]] | None = None,
    openai_client: OpenAI | None = None,
) -> TurnResult:
    """Answer one query and record every step. Never prints: output is up to presenters/."""
    runtime_config = app["config"]
    history = list(history or [])

    context_size = runtime_config["orchestrator"].get("classifier_context_messages", 0)
    classification = classify_query_domain(query, history[-context_size:] if context_size else [])
    language = _choose_block_language(query, classification)
    steps = [TraceStep(kind=STEP_CLASSIFICATION, title="Classificazione", data=dict(classification))]

    if not classification["is_cinema"]:
        return TurnResult(
            query=query,
            language=language,
            blocked=True,
            answer=NON_CINEMA_BLOCK_MESSAGES[language],
            steps=steps,
            history=history,
        )

    decision = app["orchestrator"].run(query=query, conversation_history=history)
    answer = decision["final_answer"]
    standalone_query = decision.get("standalone_query") or query
    steps.append(
        TraceStep(
            kind=STEP_QUERY_REWRITE,
            title="Query usata dai tool",
            data={"original": query, "used": standalone_query, "rewritten": standalone_query != query},
        )
    )
    steps.append(TraceStep(kind=STEP_TOOL_SELECTION, title="Tool scelto", data={"tool": decision["tool"]}))
    steps.extend(TraceStep(**step) for step in decision["result"].get("trace", []))

    history.extend(
        [
            {"role": "user", "content": query},
            {"role": "assistant", "content": answer},
        ]
    )

    compacted = False
    if len(history) >= runtime_config["orchestrator"]["memory_window_size"]:
        compact_runtime = {
            "generation": runtime_config["rag"]["generation"],
            "conversation": runtime_config["orchestrator"]["conversation"],
        }
        history = _compact_history(history, compact_runtime, openai_client or OpenAI())
        compacted = True

    return TurnResult(
        query=query,
        language=language,
        blocked=False,
        answer=answer,
        tool=decision["tool"],
        steps=steps,
        history=history,
        history_compacted=compacted,
    )


def run_terminal_chat() -> None:
    app = build_app()
    runtime_rag = _resolve_runtime_config(app["config"]["rag"])
    ensure_collection_ready(runtime_rag)

    history: list[dict[str, str]] = []
    openai_client = OpenAI()
    terminal.print_header()
    terminal.print_mode(runtime_rag)

    while True:
        query = terminal.read_query()
        if not query:
            continue
        if query.lower() in EXIT_COMMANDS:
            terminal.print_goodbye()
            break

        turn = handle_query(app, query, history, openai_client)
        present(turn, OutputChannel.terminal)
        history = turn.history


def main() -> None:
    # Input read with input() from the terminal: this entry point declares the terminal channel.
    run_terminal_chat()


if __name__ == "__main__":
    main()
