"""Constants of the `cinema_sql` tool (not of the SQL guard, which lives in `settings.py`). Pure data."""
from __future__ import annotations

# Works a title or a person's work list is about, by default: the screen works. Episodes, seasons and "other" works (novels, comics,
# games that are only the target of a relation) are reached on purpose (`series`, `relations`), never by a title search.
FILM_KINDS = ("film", "short", "tv_film")
SERIES_KINDS = ("series", "miniseries")
SCREEN_KINDS = FILM_KINDS + SERIES_KINDS
ROLES = ("director", "writer", "cast", "composer", "cinematographer", "editor", "producer", "production_designer", "costume_designer", "creator")

# MovieLens (schema 4): its own 19 genres (not the IMDb/Wikidata genres) and the minimum ratings of its rankings, as in the old `movie_db_search` (a test keeps the list equal to it).
ML_GENRES = ("Action", "Adventure", "Animation", "Children", "Comedy", "Crime", "Documentary", "Drama", "Fantasy", "Film-Noir", "Horror", "IMAX",
             "Musical", "Mystery", "Romance", "Sci-Fi", "Thriller", "War", "Western")
ML_MODES = ("top_rated", "most_rated", "by_title", "by_tag", "genre_stats")
ML_MIN_RATINGS = 50

MAX_CANDIDATES = 5        # alternatives listed when a name is ambiguous or only similar
CANDIDATE_FETCH = 12      # rows read to find them (names repeat: the same entity has several names)
DEFAULT_LIMIT = 25
MAX_LIMIT = 50            # the SQL guard never returns more
TURNS_REMEMBERED = 16     # turn budgets kept in memory
MAX_TEXT_CHARS = 200
IDS_FOR_FIRST = 15        # works of a list that get their external ids (one query; the SQL guard allows 16 parameters)

LICENSE_TEXT = "Contains data from Wikipedia (CC BY-SA 4.0) and Wikidata (CC0 1.0)."

# The one place that says what the local data cannot prove. Codes are stable; the text reaches the model.
NOTES = {
    "cast_order_partial": "The first credited people carry the billing order of IMDb (billing_order, 1 = top billed); the credits without it come from other sources, unordered, and the cast may be partial. Present the ordered ones as the lead cast (in billing order); do not rank the others.",
    "coverage": "The local catalogue holds films and series that have a Wikipedia page; recent works (after 2019) are incomplete. A missing item or credit does not prove it does not exist.",
    "cast_order": "The cast is listed without billing order (the order of the credits is not recorded) and may be partial.",
    "filmography": "Only works of the local catalogue are listed, with credits taken from Wikidata statements: the list may be incomplete, especially for recent years.",
    "awards": "Awards come from Wikidata statements, recorded only for some works; names are as recorded (often in Italian) and a category may appear as its own award. No award found does not prove none was given.",
    "awards_person_scope": "A result is attached to a person only when the source names the nominee: a prize recorded only on the work (for example Best Picture) does not appear among a person's awards, so a person can have won more than listed. Check the awards of their works too.",
    "relations": "'is based on' covers remakes, adaptations and works that only inspired another, without telling them apart; 'follows' is the order in a series and does not say sequel, prequel or reboot.",
    "series": "Seasons and episodes exist only where the catalogue has them: counts can be lower than the real ones; episode titles are in the language of the source page.",
    "crew": "Credits are Wikidata statements: the 'writer' role can also list the authors of the source material or the creators of a character, not only the screenwriters of the film. Present them as recorded writers and say so when the names look like source authors.",
    "episode_duplicates": "Episode counts are not reliable: `episodes` counts every row of the catalogue and `numbered_episodes` only those with a number. An episode known both from its own page and from a table row can appear twice (once without a number), while other episodes legitimately have no number. Do not state a season's episode count as certain; give the figures as recorded.",
    "companies": "Companies are those recorded as production, distribution or network; the list may be partial.",
    "franchise": "'Part of the series' is what Wikidata records: besides sagas it can be a list, a ranking or a collection (for example a 'best films' list), and a film of a saga may be missing from it. Say 'recorded as part of', and do not call a list a saga.",
    "person": "Birth and death years exist only where Wikidata has an unambiguous date; a missing year is not imported, not unknown to the world.",
    "ids_partial": "Only the first works of the list carry their external ids; ask for a single work (work_id) to get the others.",
    "money": "Budget and box office are in the currency recorded, never converted.",
    "limit": "The list was cut at the limit shown; ask for a narrower year range or role to see the rest.",
    "unverified": "Only similar names were found, not an exact one: they are alternatives, not the requested entity.",
    "no_ids": "This work has no external identifier in the catalogue.",
    "identity_rule_based": "This work was identified by a rule (a single IMDb title of that name within a year), not by a director or an identifier given by a second source: say it is 'identified with good probability', not that it is certain.",
    "identity_uncertain": "The identification of this work is UNCERTAIN: the Italian page names a director that IMDb does not list for the matching title. Do not present it as verified; say that the match is uncertain and, if the user needs certainty, ask or check one external source.",
    "ratings": "Ratings are audience ratings (IMDb viewers, MovieLens users) on their own scales (10 and 5), with the number of votes and the date of the data; they are not critics' scores and are never averaged or converted. Give each with its scale and votes.",
    "ratings_mixed_types": "No type was asked: this ranking mixes films and series (see each kind). Say so; for the best FILMS ask again with type film.",
    "ratings_ranking": "The ranking uses IMDb viewer ratings and only titles with at least the minimum number of votes shown; it covers the titles of this catalogue.",
    "movielens": "These are MovieLens users' ratings on a 1-5 scale with the number of ratings, not critics' scores and not IMDb votes; never average them with another source or convert the scale. Rankings list only films, shorts and TV films of the catalogue with at least the minimum number of ratings shown, so they can differ from other lists; a MovieLens film that is not in the catalogue appears only in a title search, with status excluded and its reason.",
    "movielens_films_only": "The genre statistics count only films, shorts and TV films of the catalogue (never series or episodes) with at least the minimum number of ratings shown.",
    "movielens_any_kind": "The tag search covers every linked work, not only films: each item has a kind (film, series, miniseries, episode...). Name the kind whenever it is not a film; `type` restricts the search to films or series.",
    "movielens_genres": "The genres here are MovieLens' own list (Action, Sci-Fi, Film-Noir...), not the genres shown by other operations: a film can have several or none.",
    "provenance": "Provenance lists what the database knows about WHERE a fact comes from: identifiers (primary and alternative), the identification level, values that lost a priority decision, and candidates NOT attached. Candidates are suspicions, never facts.",
}
