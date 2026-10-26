from __future__ import annotations

import os
import re

from openai import OpenAI

from .hybrid import cerca_bm25, cerca_hybrid, costruisci_indice_bm25
from .models import QuerySignals, RerankBackend, SearchMode
from .rag import recupera
from .rerank import rerank_cohere, rerank_llm
from .vectorstore import apri_collection, has_excluded_genre


_signal_client = OpenAI()


def _extract_query_signals(query: str, llm_model: str, hint: str | None = None) -> QuerySignals:
    if not os.getenv("OPENAI_API_KEY"):
        return QuerySignals(positive_signals=[], negative_signals=[], hard_exclusions=[])

    prompt = (
        "You are a retrieval query parser for a movie recommendation engine.\n"
        "The movie corpus is in English: write every field in English, "
        "translating from the user's language.\n"
        "Extract from the user query:\n"
        "1) positive_signals: what the user wants (themes, genres, moods, plot elements, eras, style, actors/directors).\n"
        "2) negative_signals: what should be discouraged but NOT absolutely excluded.\n"
        "3) hard_exclusions: exact movies/people/franchises or explicit hard constraints to exclude.\n"
        "4) semantic_query: one English sentence describing the kind of movie or plot the user wants, "
        "used for semantic search over English plot summaries. Leave out counts and quality words "
        "(e.g. '3', 'best').\n"
        "5) genres: the requested genres using the corpus genre names (e.g. 'Science Fiction', "
        "'Horror', 'Comedy', 'Drama', 'Thriller', 'Romance Film', 'Animation', 'Documentary', "
        "'War film', 'Western', 'Crime Fiction', 'Fantasy').\n"
        "6) excluded_genres: genres the user explicitly rules out (e.g. 'without science fiction' "
        "-> 'Science Fiction'), with the same corpus genre names; never list them in genres or "
        "hard_exclusions.\n\n"
        "Rules:\n"
        "- Keep each item short (1-5 words), lowercase when natural.\n"
        "- Do not invent facts.\n"
        "- Expressions like 'that made history', 'classics' or 'cult' mean influential or iconic "
        "movies, not historical movies.\n"
        "- If a list is not present, return [] for that list.\n"
        "- Requests about the answer (ratings, reviews, number of results) are not signals.\n"
        "- semantic_query and positive_signals must keep every explicit attribute the user gives: "
        "country or nationality, decade or years, genres, setting or place.\n"
        "- When the user cites a movie only as a reference ('like X', 'the themes of X'), "
        "semantic_query describes the themes, situations and setting of X in plain words and "
        "never just says 'similar to X'; put X in hard_exclusions.\n"
        "- A 'Planner rewrite' may follow the user query: use it only to add context; the "
        "user's own words win and nothing they asked may be dropped.\n"
        "- Return JSON only matching the schema.\n"
    )
    text = query
    if hint and hint.strip() and hint.strip() != query.strip():
        text = f"{query}\n\nPlanner rewrite: {hint.strip()}"
    try:
        response = _signal_client.responses.parse(
            model=llm_model,
            instructions=prompt,
            input=text,
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


def _build_signal_aware_query(query: str, config: dict, hint: str | None = None) -> QuerySignals:
    model = config["generation"]["model"]
    extracted = _extract_query_signals(query, llm_model=model, hint=hint)
    return QuerySignals(
        positive_signals=_normalize_signal_list(extracted.positive_signals),
        negative_signals=_normalize_signal_list(extracted.negative_signals),
        hard_exclusions=_normalize_signal_list(extracted.hard_exclusions),
        semantic_query=extracted.semantic_query.strip(),
        genres=_normalize_signal_list(extracted.genres),
        excluded_genres=_normalize_signal_list(extracted.excluded_genres),
    )


def _signal_words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


# Requests about the answer ("indicami anche i voti"), not about the movie: never reranked on.
_ANSWER_REQUEST_WORDS = frozenset({"rating", "ratings", "review", "reviews", "vote", "votes", "score", "scores"})


def compose_rerank_query(signals: QuerySignals, query: str) -> str:
    """Semantic query plus the explicit requirements it left out, for the reranker.

    The semantic sentence states the intent in English, but the parser sometimes drops an
    explicit attribute (real case: "1950s" missing from "A Japanese science fiction comedy
    set on Mars…"). Every requested genre and positive signal whose key words do not all
    appear in the sentence is appended, so the reranker sees decade, country, genre and
    setting too. No extra call: the text is built from signals already extracted.
    """
    base = (signals.semantic_query or query).strip()
    present = set(_signal_words(base))
    missing = []
    for item in [*signals.positive_signals, *signals.genres]:
        words = [w for w in _signal_words(item) if len(w) >= 4 or any(ch.isdigit() for ch in w)]
        if set(words) & _ANSWER_REQUEST_WORDS:
            continue
        if words and not all(word in present for word in words) and item not in missing:
            missing.append(item)
    return f"{base} Must match: {'; '.join(missing)}." if missing else base


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


def _retrieve(query: str, config: dict, signals: QuerySignals | None = None) -> list[dict]:
    if signals is None:
        signals = _build_signal_aware_query(query, config)
    retrieval_config = config["retrieval"]
    fetch_k = max(
        retrieval_config.get("fetch_k") or retrieval_config["k_finale"] * 3,
        retrieval_config["k_largo"],
    )

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
            fetch_k=fetch_k,
            semantic_query=signals.semantic_query,
            genres=signals.genres,
            genre_boost=retrieval_config.get("genre_boost", 0.0),
            excluded_genres=signals.excluded_genres,
        )
        return _light_rerank(query, base_results, signals)

    indice_bm25 = costruisci_indice_bm25(collection)
    # The corpus is English: keyword matching needs the English semantic query, not the user's words.
    keyword_query = signals.semantic_query or query

    def _apply_hard_exclusions(chunks: list[dict]) -> list[dict]:
        if not signals.hard_exclusions and not signals.excluded_genres:
            return chunks
        exclusions = [s.lower() for s in signals.hard_exclusions]
        filtrati = []
        for chunk in chunks:
            title = str(chunk.get("title") or "").lower()
            movie_id = str(chunk.get("movie_id") or "").lower()
            source = str(chunk.get("source") or "").lower()
            if any(sig in title or sig in movie_id or sig in source for sig in exclusions):
                continue
            if has_excluded_genre(chunk, signals.excluded_genres):
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
            fetch_k=fetch_k,
            semantic_query=signals.semantic_query,
            genres=signals.genres,
            genre_boost=retrieval_config.get("genre_boost", 0.0),
            excluded_genres=signals.excluded_genres,
        )
        risultati_bm25 = cerca_bm25(keyword_query, indice_bm25, config["retrieval"]["k_largo"])
        risultati_bm25 = _apply_hard_exclusions(risultati_bm25)
        risultati = cerca_hybrid(
            risultati_semantici,
            risultati_bm25,
            config["retrieval"]["k_largo"],
            rrf_costante=config["retrieval"]["rrf_costante"],
        )
        return _light_rerank(query, risultati, signals)

    risultati_bm25 = cerca_bm25(keyword_query, indice_bm25, config["retrieval"]["k_largo"])
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
