from __future__ import annotations

from openai import OpenAI

from aikit import apri_collection, genera
from rag_support.cli import (
    _print_chunks,
    _print_retrieval_compact,
    print_final_answer,
    print_header,
    print_mode,
)
from rag_support.conversation import _compact_history, _rewrite_query_with_history
from rag_support.local_query_classifier import classify_query_domain
from rag_support.retrieval import _rerank, _retrieve
from rag_support.runtime import _resolve_runtime_config


def run_conversation_loop(
    *,
    config: dict,
    exit_commands: set[str],
    compact_notice: str,
) -> None:
    def _precheck_query(query: str) -> str | None:
        classification = classify_query_domain(query)
        if classification["is_cinema"]:
            return None

        # Lazy import avoids circular imports while keeping the shared message source in app.py.
        from app import NON_CINEMA_BLOCK_MESSAGES

        language = "it" if classification["is_italian"] else "en"
        return NON_CINEMA_BLOCK_MESSAGES[language]

    runtime_config = _resolve_runtime_config(config)

    collection = apri_collection(
        runtime_config["vectorstore"]["collection"],
        db_dir=runtime_config["vectorstore"]["db_dir"],
    )

    if collection.count() == 0:
        raise RuntimeError(
            "Collection is empty. Run `python buildSemanticDb.py "
            "--embedding-backend <backend>` before querying."
        )

    print_header()
    print_mode(runtime_config)

    history: list[dict] = []
    openai_client = OpenAI()
    threshold = runtime_config["conversation"]["token_threshold"]

    while True:
        query = input("\n" * 2 + "Tu > ").strip()
        print( "\n" * 2)
        if not query:
            continue
        if query.lower() in exit_commands:
            print("\nChiusura chat. A presto!")
            break

        block_message = _precheck_query(query)
        if block_message:
            print_final_answer(block_message)
            continue

        effective_query = _rewrite_query_with_history(query, history, runtime_config, openai_client)

        retrieved = _retrieve(effective_query, runtime_config)
        _print_retrieval_compact(
            f"K LARGO — {len(retrieved)} CHUNK RECUPERATI",
            retrieved,
            "📚",
        )

        final_chunks = _rerank(effective_query, retrieved, runtime_config)
        _print_chunks(
            f"RERANKING — {len(final_chunks)} CHUNK SELEZIONATI",
            final_chunks,
            "🏆",
        )

        generation_result = genera(
            final_chunks,
            effective_query,
            model=runtime_config["generation"]["model"],
            instructions=runtime_config["generation"]["instructions"],
            storia=history,
            return_usage=True,
            openai_client=openai_client,
        )
        answer = generation_result["text"]

        print_final_answer(answer)

        history.extend(
            [
                {"role": "user", "content": query},
                {"role": "assistant", "content": answer},
            ]
        )

        if (generation_result.get("input_tokens") or 0) >= threshold:
            history = _compact_history(history, runtime_config, openai_client)
            print(compact_notice)
