"""Access to the vector index (Qdrant) and the filters, penalties and boosts applied to its results."""
import re

from .embeddings import embed


def apri_collection(nome, *, store_config):
    """Open the Qdrant collection described by `CONFIG["rag"]["vectorstore"]`.

    The collection is never created here: it is built by `buildSemanticDb.py`.
    """
    from .store.collection import open_collection

    return open_collection(nome, store_config)


def _normalize_signals(signals):
    normalized = []
    for signal in signals or []:
        text = str(signal).strip()
        if text:
            normalized.append(text)
    return normalized


def _contains_signal(text, signal):
    if not text or not signal:
        return False
    return signal.lower() in text.lower()


def _is_hard_excluded(result, hard_exclusions):
    if not hard_exclusions:
        return False

    title = str(result.get("title") or "")
    movie_id = str(result.get("movie_id") or "")
    source = str(result.get("source") or "")

    for signal in hard_exclusions:
        if (
            _contains_signal(title, signal)
            or _contains_signal(movie_id, signal)
            or _contains_signal(source, signal)
        ):
            return True
    return False


def _count_negative_matches(result, negative_signals):
    if not negative_signals:
        return 0

    fields = [
        str(result.get("title") or ""),
        str(result.get("genres") or ""),
        str(result.get("cast") or ""),
        str(result.get("testo") or ""),
    ]
    haystack = "\n".join(fields)

    matches = 0
    for signal in negative_signals:
        if not signal:
            continue
        # Whole-word-ish match when possible, fallback to substring for multiword phrases.
        if " " in signal:
            if _contains_signal(haystack, signal):
                matches += 1
            continue
        pattern = rf"\b{re.escape(signal.lower())}\b"
        if re.search(pattern, haystack.lower()):
            matches += 1
    return matches


def has_excluded_genre(result, excluded_genres):
    """True if a `;`-separated chunk genre contains an excluded genre as whole words."""
    chunk_genres = [g.strip().lower() for g in str(result.get("genres") or "").split(";") if g.strip()]
    return any(
        re.search(rf"\b{re.escape(genre.lower())}\b", chunk_genre)
        for genre in excluded_genres or []
        for chunk_genre in chunk_genres
    )


def _matches_genres(result, genres):
    """True if any requested genre appears in the chunk's `;`-separated genres metadata."""
    if not genres:
        return False
    chunk_genres = [g.strip().lower() for g in str(result.get("genres") or "").split(";")]
    return any(
        genre.lower() in chunk_genre
        for genre in genres
        for chunk_genre in chunk_genres
        if chunk_genre
    )


def search(
    collection,
    query,
    k,
    backend,
    model,
    *,
    positive_signals=None,
    negative_signals=None,
    hard_exclusions=None,
    fetch_k=None,
    semantic_query=None,
    genres=None,
    genre_boost=0.0,
    excluded_genres=None,
    references=None,
):
    """Return the top-k most similar documents for a query.

    The embedded text is `semantic_query` when given, otherwise `query`. Keyword signals
    are never embedded: a bag of keywords (often not in the corpus language) drifts away
    from the user's intent. Chunks matching `genres` get `genre_boost` added to their score
    before the fetch_k pool is cut to k. Chunks with an `excluded_genres` genre are dropped.

    With `references` (a `references.ReferenceSet`) that has at least one usable vector, the pool
    comes from a steered search (text vector + positive examples, minus negative examples) instead
    of the plain one, and no reference film can be returned. Without usable references nothing
    changes: the call below is exactly the plain query.
    """
    negative_signals = _normalize_signals(negative_signals)
    hard_exclusions = _normalize_signals(hard_exclusions)
    genres = _normalize_signals(genres)

    embedded_text = str(semantic_query or "").strip() or query
    q = embed([embedded_text], backend=backend, model=model)[0]

    requested_k = int(fetch_k or k)
    requested_k = max(requested_k, int(k))
    steered = references is not None and references.active
    if steered:
        if not hasattr(collection, "recommend"):
            raise RuntimeError("Reference search needs a collection that can `recommend` (the Qdrant adapter).")
        ris = collection.recommend(
            positive=[q] * references.text_repeat + references.positives(),
            negative=references.negatives(), n_results=requested_k, strategy=references.strategy,
            exclude_movie_ids=references.excluded_movie_ids())
    else:
        ris = collection.query(query_embeddings=[q], n_results=requested_k)

    # Soft penalty for negative signals: subtract from semantic score, never hard-filter.
    soft_penalty_per_match = 0.08

    risultati = []
    for i in range(len(ris["ids"][0])):
        risultato = {
            "id": ris["ids"][0][i],
            "testo": ris["documents"][0][i],
            "score": 1 - ris["distances"][0][i],
        }
        if ris["metadatas"][0][i]:
            risultato.update(ris["metadatas"][0][i])

        if _is_hard_excluded(risultato, hard_exclusions):
            continue
        if has_excluded_genre(risultato, excluded_genres):
            continue

        negative_matches = _count_negative_matches(risultato, negative_signals)
        if negative_matches > 0:
            risultato["score"] = risultato["score"] - (soft_penalty_per_match * negative_matches)

        if _matches_genres(risultato, genres):
            risultato["score"] = risultato["score"] + genre_boost

        risultati.append(risultato)

    risultati.sort(key=lambda item: item.get("score", 0.0), reverse=True)
    if references is not None:
        from .references import drop_references

        risultati = drop_references(risultati, references)
    return risultati[:k]
