from __future__ import annotations

import os
import re
from functools import lru_cache

from openai import OpenAI

from .constraints import demote_contradicted
from .hybrid import cerca_bm25, cerca_hybrid, costruisci_indice_bm25
from .models import QuerySignals, ReferenceTitle, RerankBackend, SearchMode
from .rag import recupera
from .rerank import rerank_cohere, rerank_llm, rerank_llm_request
from .vectorstore import apri_collection, has_excluded_genre


@lru_cache(maxsize=1)
def _signal_client() -> OpenAI:
    return OpenAI()


# Replaces item 4 and adds item 7 of the parser prompt when `rag.signals.avoid_query` is on: the sentence that is
# embedded and reranked must contain only what the user wants (an embedding of "without X" is close to X), and
# what to avoid travels in its own field.
_AVOID_ITEM_4 = (
    "4) semantic_query: one English sentence describing ONLY the kind of movie or plot the user wants, "
    "used for semantic search over English plot summaries. It must never contain negations or what to avoid "
    "('without', 'not', 'avoiding', 'rather than'). Leave out counts and quality words (e.g. '3', 'best').\n"
)
_AVOID_ITEM_7 = (
    "7) avoid_query: one English sentence describing the themes, tone and style of what the user wants to "
    "avoid or be different from; when they cite a movie Y to be different from, describe Y's themes, tone and "
    "style in plain words (never just 'like Y') and put Y in hard_exclusions. Empty string when there is nothing to avoid.\n"
)


_REFERENCE_ITEMS = (
    "like_titles: the movies the user cites as a model to be SIMILAR to, as objects {title, year}: the title "
    "exactly as the movie is commonly known (original title for non-English films) and the release year ONLY "
    "if you are sure of it, otherwise null (never guess a year). Empty list when the user cites none.\n",
    "avoid_titles: the movies the user cites to be DIFFERENT from or to avoid, in the same {title, year} form. "
    "Every movie listed here or in like_titles must also be in hard_exclusions.\n",
)


def _extract_query_signals(
    query: str,
    llm_model: str,
    hint: str | None = None,
    *,
    avoid_query: bool = False,
    reference_titles: bool = False,
) -> QuerySignals:
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
    if avoid_query:
        start = prompt.index("4) semantic_query")
        end = prompt.index("5) genres")
        prompt = prompt[:start] + _AVOID_ITEM_4 + prompt[end:]
        prompt = prompt.replace("\nRules:\n", _AVOID_ITEM_7 + "\nRules:\n", 1)
    if reference_titles:
        first = 8 if avoid_query else 7
        items = "".join(f"{first + n}) {item}" for n, item in enumerate(_REFERENCE_ITEMS))
        prompt = prompt.replace("\nRules:\n", items + "\nRules:\n", 1)
    text = query
    if hint and hint.strip() and hint.strip() != query.strip():
        text = f"{query}\n\nPlanner rewrite: {hint.strip()}"
    try:
        response = _signal_client().responses.parse(
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


def _clean_reference_titles(values: list) -> list[ReferenceTitle]:
    """Titles trimmed and deduplicated; a year outside a plausible range is dropped (the title is kept)."""
    seen: set[tuple] = set()
    cleaned: list[ReferenceTitle] = []
    for value in values:
        title = str(getattr(value, "title", "") or "").strip()
        year = getattr(value, "year", None)
        year = year if isinstance(year, int) and 1880 <= year <= 2100 else None
        key = (title.casefold(), year)
        if not title or key in seen:
            continue
        seen.add(key)
        cleaned.append(ReferenceTitle(title=title, year=year))
    return cleaned


def _build_signal_aware_query(query: str, config: dict, hint: str | None = None) -> QuerySignals:
    model = config["generation"]["model"]
    use_avoid = bool((config.get("signals") or {}).get("avoid_query"))
    use_refs = bool((config.get("signals") or {}).get("reference_titles"))
    extracted = _extract_query_signals(query, llm_model=model, hint=hint, avoid_query=use_avoid, reference_titles=use_refs)
    return QuerySignals(
        positive_signals=_normalize_signal_list(extracted.positive_signals),
        negative_signals=_normalize_signal_list(extracted.negative_signals),
        hard_exclusions=_normalize_signal_list(extracted.hard_exclusions),
        semantic_query=extracted.semantic_query.strip(),
        avoid_query=extracted.avoid_query.strip() if use_avoid else "",
        like_titles=_clean_reference_titles(extracted.like_titles) if use_refs else [],
        avoid_titles=_clean_reference_titles(extracted.avoid_titles) if use_refs else [],
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


def candidate_pool_size(config: dict, signals: QuerySignals) -> int:
    """Candidates handed to the reranker: `retrieval.k_largo`, or the wider `rerank.avoid_pool` when the request says what to
    avoid and an LLM ranks it (it can read the whole fetch pool; a cross-encoder given a description cannot use the contrast)."""
    k_pool = int(config["retrieval"]["k_largo"])
    rerank = config.get("rerank") or {}
    if rerank.get("avoid_llm") and signals.avoid_query:
        k_pool = max(k_pool, int(rerank.get("avoid_pool") or 0))
    return k_pool


def _retrieve(query: str, config: dict, signals: QuerySignals | None = None, references=None) -> list[dict]:
    if signals is None:
        signals = _build_signal_aware_query(query, config)
    retrieval_config = config["retrieval"]
    k_pool = candidate_pool_size(config, signals)
    fetch_k = max(
        retrieval_config.get("fetch_k") or retrieval_config["k_finale"] * 3,
        k_pool,
    )

    collection = apri_collection(
        config["vectorstore"]["collection"],
        store_config=config["vectorstore"],
    )

    if config["retrieval"]["search_mode"] == SearchMode.semantic:
        base_results = recupera(
            query,
            collection_name=config["vectorstore"]["collection"],
            k=k_pool,
            embedding_backend=config["embedding"]["backend"],
            embedding_model=config["embedding"]["model"],
                positive_signals=signals.positive_signals,
            negative_signals=signals.negative_signals,
            hard_exclusions=signals.hard_exclusions,
            fetch_k=fetch_k,
            semantic_query=signals.semantic_query,
            genres=signals.genres,
            genre_boost=retrieval_config.get("genre_boost", 0.0),
            excluded_genres=signals.excluded_genres,
            store_config=config["vectorstore"],
            references=references,
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
            k=k_pool,
            embedding_backend=config["embedding"]["backend"],
            embedding_model=config["embedding"]["model"],
                positive_signals=signals.positive_signals,
            negative_signals=signals.negative_signals,
            hard_exclusions=signals.hard_exclusions,
            fetch_k=fetch_k,
            semantic_query=signals.semantic_query,
            genres=signals.genres,
            genre_boost=retrieval_config.get("genre_boost", 0.0),
            excluded_genres=signals.excluded_genres,
            store_config=config["vectorstore"],
        )
        risultati_bm25 = cerca_bm25(keyword_query, indice_bm25, k_pool)
        risultati_bm25 = _apply_hard_exclusions(risultati_bm25)
        risultati = cerca_hybrid(
            risultati_semantici,
            risultati_bm25,
            k_pool,
            rrf_costante=config["retrieval"]["rrf_costante"],
        )
        return _light_rerank(query, risultati, signals)

    risultati_bm25 = cerca_bm25(keyword_query, indice_bm25, k_pool)
    risultati_bm25 = _apply_hard_exclusions(risultati_bm25)
    return _light_rerank(query, risultati_bm25, signals)


def _rerank(
    query: str, chunks: list[dict], config: dict, signals: QuerySignals | None = None, request: str | None = None
) -> list[dict]:
    ranked = None
    if config["rerank"].get("avoid_llm") and signals is not None and signals.avoid_query and request:
        try:  # "like X, not like Y": an LLM that knows the films; any failure falls back to the cross-encoder
            # A plot whose film has no title in the metadata cannot be named, recommended or judged by the model.
            titled = [c for c in chunks if str(c.get("title") or "").strip()]
            ranked = rerank_llm_request(
                request, query, signals.avoid_query,
                titled if len(titled) >= config["retrieval"]["k_finale"] else chunks,
                model=config["rerank"].get("llm_model"))
        except Exception:
            ranked = None
    if ranked is not None:
        pass
    elif config["rerank"]["backend"] == RerankBackend.cohere:
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

    if signals is not None:
        ranked = demote_contradicted(signals, ranked)
    return ranked[: config["retrieval"]["k_finale"]]
