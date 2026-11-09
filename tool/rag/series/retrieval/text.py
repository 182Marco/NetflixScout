"""Title helpers of the series retriever; `norm` and `unit` are shared with the film retriever."""
from __future__ import annotations

import re

from ...shared.text import norm, unit  # noqa: F401  (re-exported: the series modules import them from here)


def base_title_norm(title) -> str:
    """The title without the trailing disambiguation of Wikipedia: "Lost (serie televisiva)" -> "lost"."""
    return norm(re.sub(r"\s*\([^)]*\)\s*$", "", str(title or "")))


def _same_word(term_word: str, request_word: str) -> bool:
    """Equal, or the same word in another inflection: lengths differ by at most one letter and the shared beginning covers all but one letter of the
    shorter word (sopravvissuto/sopravvissuti, botola/botole). Words under four letters must be equal. A mismatch only WIDENS the search (see `verified_rare_terms`)."""
    if term_word == request_word:
        return True
    short = min(len(term_word), len(request_word))
    if short < 4 or abs(len(term_word) - len(request_word)) > 1:
        return False
    common = 0
    for a, b in zip(term_word, request_word):
        if a != b:
            break
        common += 1
    return common >= short - 1


def verified_rare_terms(terms: list[str], request: str) -> tuple[list[str], list[str]]:
    """Split the parser's `rare_terms` into (kept, dropped). A rare term becomes a HARD full-text filter on the plots, and its contract is "words the user states
    verbatim": a term whose words are not, in order and next to each other, words of the user's request (any case or accent, plural or other inflection of the
    same word) is not the user's and is dropped, so a translation or an invention can never narrow the catalogue (FASE 19H: "iron" -> "ferro" left 62 of 11.478
    series). Without a request text nothing can be checked and every term is kept. Dropping can only make the pool larger; the dense ranking is untouched."""
    if not (request or "").strip():
        return list(terms), []
    words = norm(request).split()
    kept: list[str] = []
    dropped: list[str] = []
    for term in terms:
        tw = norm(term).split()
        found = bool(tw) and any(all(_same_word(t, w) for t, w in zip(tw, words[i:i + len(tw)])) for i in range(len(words) - len(tw) + 1))
        (kept if found else dropped).append(term)
    return kept, dropped
