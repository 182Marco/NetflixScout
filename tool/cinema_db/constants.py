"""Constants of the `cinema_sql` tool (not of the SQL guard, which lives in `settings.py`). Pure data."""
from __future__ import annotations

# Works a title or a person's work list is about, by default: the screen works. Episodes, seasons and "other" works (novels, comics,
# games that are only the target of a relation) are reached on purpose (`series`, `relations`), never by a title search.
FILM_KINDS = ("film", "short", "tv_film")
SERIES_KINDS = ("series", "miniseries")
SCREEN_KINDS = FILM_KINDS + SERIES_KINDS
ROLES = ("director", "writer", "cast", "composer", "cinematographer", "editor", "producer", "production_designer", "costume_designer", "creator")

MAX_CANDIDATES = 5        # alternatives listed when a name is ambiguous or only similar
CANDIDATE_FETCH = 12      # rows read to find them (names repeat: the same entity has several names)
DEFAULT_LIMIT = 25
MAX_LIMIT = 50            # the SQL guard never returns more
TURNS_REMEMBERED = 16     # turn budgets kept in memory
MAX_TEXT_CHARS = 200

LICENSE_TEXT = "Contains data from Wikipedia (CC BY-SA 4.0) and Wikidata (CC0 1.0)."

# The one place that says what the local data cannot prove. Codes are stable; the text reaches the model.
NOTES = {
    "coverage": "The local catalogue holds films and series that have a Wikipedia page; recent works (after 2019) are incomplete. A missing item or credit does not prove it does not exist.",
    "cast_order": "The cast is listed without billing order (the order of the credits is not recorded) and may be partial.",
    "filmography": "Only works of the local catalogue are listed, with credits taken from Wikidata statements: the list may be incomplete, especially for recent years.",
    "awards": "Awards come from Wikidata statements, recorded only for some works; names are as recorded (often in Italian) and a category may appear as its own award. No award found does not prove none was given.",
    "relations": "'is based on' covers remakes, adaptations and works that only inspired another, without telling them apart; 'follows' is the order in a series and does not say sequel, prequel or reboot.",
    "series": "Seasons and episodes exist only where the catalogue has them: counts can be lower than the real ones; episode titles are in the language of the source page.",
    "episode_duplicates": "Episode counts are not reliable: `episodes` counts every row of the catalogue and `numbered_episodes` only those with a number. An episode known both from its own page and from a table row can appear twice (once without a number), while other episodes legitimately have no number. Do not state a season's episode count as certain; give the figures as recorded.",
    "companies": "Companies are those recorded as production, distribution or network; the list may be partial.",
    "franchise": "Franchise membership is what Wikidata records: a film of a saga may be missing from it.",
    "person": "Birth and death years exist only where Wikidata has an unambiguous date; a missing year is not imported, not unknown to the world.",
    "money": "Budget and box office are in the currency recorded, never converted.",
    "limit": "The list was cut at the limit shown; ask for a narrower year range or role to see the rest.",
    "unverified": "Only similar names were found, not an exact one: they are alternatives, not the requested entity.",
    "no_ids": "This work has no external identifier in the catalogue.",
}
