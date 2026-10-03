from __future__ import annotations

import os

from openai import OpenAI

from .hybrid import cerca_bm25, cerca_hybrid, costruisci_indice_bm25
from .models import QuerySignals, RerankBackend, SearchMode
from .rag import recupera
from .rerank import rerank_cohere, rerank_llm
from .vectorstore import apri_collection


_signal_client = OpenAI()


def _extract_query_signals(query: str, llm_model: str) -> QuerySignals:
    if not os.getenv("OPENAI_API_KEY"):
        return QuerySignals(positive_signals=[], negative_signals=[], hard_exclusions=[])

    prompt = (
        "You are a retrieval query parser for a movie recommendation engine.\n"
        "Extract three lists from the user query:\n"
        "1) positive_signals: what the user wants (themes, genres, moods, plot elements, eras, style, actors/directors).\n"
        "2) negative_signals: what should be discouraged but NOT absolutely excluded.\n"
        "3) hard_exclusions: exact movies/people/franchises or explicit hard constraints to exclude.\n\n"
        "Rules:\n"
        "- Keep each item short (1-5 words), lowercase when natural.\n"
        "- Do not invent facts.\n"
        "- If a list is not present, return [] for that list.\n"
        "- Return JSON only matching the schema.\n"
    )
    try:
        response = _signal_client.responses.parse(
            model=llm_model,
            instructions=prompt,
            input=query,
            text_format=QuerySignals,
        )
        parsed = response.output_parsed
        if isinstance(parsed, QuerySignals):
            return parsed
    except Exception:
        pass

    # Safe fallback keeps full backward compatibility.
    return QuerySignals(positive_signals=[], negative_signals=[], hard_exclusions=[])


def _normalize_signal_list(values: list[str]) -> list[str]:
    seen = set()
    normalized = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return normalized


def _build_signal_aware_query(query: str, config: dict) -> QuerySignals:
    model = config["generation"]["model"]
    extracted = _extract_query_signals(query, llm_model=model)
    return QuerySignals(
        positive_signals=_normalize_signal_list(extracted.positive_signals),
        negative_signals=_normalize_signal_list(extracted.negative_signals),
        hard_exclusions=_normalize_signal_list(extracted.hard_exclusions),
    )


def _light_rerank(query: str, chunks: list[dict], signals: QuerySignals) -> list[dict]:
    query_words = {w for w in query.lower().split() if len(w) > 2}
    positive = [s.lower() for s in signals.positive_signals]
    negative = [s.lower() for s in signals.negative_signals]

    rescored = []
    for chunk in chunks:
        text = " ".join(
            [
                str(chunk.get("title") or ""),
                str(chunk.get("genres") or ""),
                str(chunk.get("cast") or ""),
                str(chunk.get("testo") or ""),
            ]
        ).lower()

        bonus = 0.0
        for signal in positive:
            if signal and signal in text:
                bonus += 0.03

        negative_penalty = 0.0
        for signal in negative:
            if signal and signal in text:
                negative_penalty += 0.08

        lexical_overlap = sum(1 for w in query_words if w in text)
        bonus += min(0.06, lexical_overlap * 0.005)

        rescored.append({
            **chunk,
            "score": float(chunk.get("score", 0.0)) + bonus - negative_penalty,
        })

    rescored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    return rescored


def _retrieve(query: str, config: dict) -> list[dict]:
    signals = _build_signal_aware_query(query, config)

    collection = apri_collection(
        config["vectorstore"]["collection"],
        db_dir=config["vectorstore"]["db_dir"],
    )

    if config["retrieval"]["search_mode"] == SearchMode.semantic:
        base_results = recupera(
            query,
            collection_name=config["vectorstore"]["collection"],
            k=config["retrieval"]["k_largo"],
            embedding_backend=config["embedding"]["backend"],
            embedding_model=config["embedding"]["model"],
            db_dir=config["vectorstore"]["db_dir"],
            positive_signals=signals.positive_signals,
            negative_signals=signals.negative_signals,
            hard_exclusions=signals.hard_exclusions,
            fetch_k=max(config["retrieval"]["k_largo"], config["retrieval"]["k_finale"] * 3),
        )
        return _light_rerank(query, base_results, signals)

    indice_bm25 = costruisci_indice_bm25(collection)

    def _apply_hard_exclusions(chunks: list[dict]) -> list[dict]:
        if not signals.hard_exclusions:
            return chunks
        exclusions = [s.lower() for s in signals.hard_exclusions]
        filtrati = []
        for chunk in chunks:
            title = str(chunk.get("title") or "").lower()
            movie_id = str(chunk.get("movie_id") or "").lower()
            source = str(chunk.get("source") or "").lower()
            if any(sig in title or sig in movie_id or sig in source for sig in exclusions):
                continue
            filtrati.append(chunk)
        return filtrati

    if config["retrieval"]["search_mode"] == SearchMode.hybrid:
        risultati_semantici = recupera(
            query,
            collection_name=config["vectorstore"]["collection"],
            k=config["retrieval"]["k_largo"],
            embedding_backend=config["embedding"]["backend"],
            embedding_model=config["embedding"]["model"],
            db_dir=config["vectorstore"]["db_dir"],
            positive_signals=signals.positive_signals,
            negative_signals=signals.negative_signals,
            hard_exclusions=signals.hard_exclusions,
            fetch_k=max(config["retrieval"]["k_largo"], config["retrieval"]["k_finale"] * 3),
        )
        risultati_bm25 = cerca_bm25(query, indice_bm25, config["retrieval"]["k_largo"])
        risultati_bm25 = _apply_hard_exclusions(risultati_bm25)
        risultati = cerca_hybrid(
            risultati_semantici,
            risultati_bm25,
            config["retrieval"]["k_largo"],
            rrf_costante=config["retrieval"]["rrf_costante"],
        )
        return _light_rerank(query, risultati, signals)

    risultati_bm25 = cerca_bm25(query, indice_bm25, config["retrieval"]["k_largo"])
    risultati_bm25 = _apply_hard_exclusions(risultati_bm25)
    return _light_rerank(query, risultati_bm25, signals)


def _rerank(query: str, chunks: list[dict], config: dict) -> list[dict]:
    if config["rerank"]["backend"] == RerankBackend.cohere:
        ranked = rerank_cohere(
            query,
            chunks,
            model=config["rerank"]["cohere_model"],
        )
    else:
        ranked = rerank_llm(
            query,
            chunks,
            model=config["rerank"]["llm_model"],
        )

    return ranked[: config["retrieval"]["k_finale"]]
