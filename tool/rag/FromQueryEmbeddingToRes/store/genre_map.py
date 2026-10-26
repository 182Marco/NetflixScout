"""TMDb genre names mapped onto the vocabulary of the corpus (CMU), where they differ.

Genre filters match by substring (`_matches_genres`) and exclusions by whole word, so a TMDb "Crime"
must be stored as the corpus' "Crime Fiction" to be found next to the 4,277 films that use it. The
13 genres that already coincide are not listed.
"""
from __future__ import annotations

TMDB_TO_CORPUS = {
    "Crime": "Crime Fiction",
    "Romance": "Romance Film",
    "War": "War film",
    "Family": "Family Film",
    "Music": "Musical",
    "TV Movie": "Television movie",
}


def corpus_genres(names: list[str] | tuple[str, ...]) -> list[str]:
    """Genres in the corpus vocabulary, order kept, duplicates removed."""
    mapped = (TMDB_TO_CORPUS.get(name.strip(), name.strip()) for name in names if str(name).strip())
    return list(dict.fromkeys(mapped))
