"""Manual decisions taken after READING the title, genres, metadata and the start of the synopsis of the records the
rules left wrong or unclear (Phase 4). They override the automatic verdict; each carries the reason. Matching is by title
among the records with no year, and must be unique (checked when the file is built).

This is a reading of the local text, not an external verification: confidence is 'manual' and the doubtful ones stay doubtful."""
from __future__ import annotations

# (title or title prefix, verdict, subtype, note)
REVIEW: list[tuple[str, str, str, str]] = [
    # --- topic articles that the automatic rules left as 'doubtful'
    ("Rappresentazione dell'HIV/AIDS nel cinema", "topic", "film_topic", "article on how a subject is represented in cinema"),
    ("Decamerotico", "topic", "film_genre", "article on a film genre ('le origini del genere cinematografico')"),
    ("Cinema di propaganda fascista", "topic", "film_topic", "article on a period/trend of cinema"),
    ("Uomo lupo nella cinematografia", "topic", "film_topic", "article on a character type across films"),
    ("Cinema in Abruzzo", "topic", "film_topic", "article on the cinema of a region"),
    ("Cinema protogiallo", "topic", "film_genre", "article on the origins of a genre"),
    ("Krimi (cinema)", "topic", "film_genre", "article on a genre term"),
    ("Fort Bravo - Texas Hollywood", "topic", "film_location", "describes a film set/location"),
    ("Shin Japan Heroes Universe", "topic", "media_franchise", "announced collaboration project / franchise"),
    ("Happy Hooligan", "topic", "comic_character", "page about a comic-strip character"),
    # --- series, newsreels, manga/anime/games that are not films
    ("Cine-settimana", "series", "newsreel_series", "Soviet newsreel series"),
    ("Kinopravda", "series", "newsreel_series", "Vertov's newsreel series and the concept behind it"),
    ("Rokudenashi Blues", "series", "manga", "synopsis presents the premise of the manga/anime series"),
    ("Higurashi no naku koro ni", "series", "visual_novel_anime", "visual novel / anime series"),
    ("Video Girl Ai", "series", "manga", "manga/anime franchise page"),
    ("Wild 7", "series", "manga", "manga/anime franchise page"),
    ("Aikatsu!", "series", "anime_series", "anime franchise page"),
    ("Aikatsu Stars!", "series", "anime_series", "anime series (Wikidata labels it a video game)"),
    ("Siamo in 11!", "series", "manga", "manga/anime franchise page"),
    ("Annika: Crime Reporter", "series", "tv_series", "describes the investigations of a TV series' protagonist"),
    ("Lo schiaccianoci", "other_work", "stage_work", "ballet: the synopsis is the libretto"),
    # --- real films the rules could not trust (little metadata, or a wrong Wikidata class)
    ("Il Generale e i Fratellini d'Italia", "film", "animated", "narrative synopsis of an animated work; metadata incomplete"),
    ("Mel Gibson's Video Diary 2", "film", "short", "narrative synopsis; metadata incomplete"),
    ("I veleni dei Gonzaga", "film", "tv_film", "narrative synopsis (historical fiction); metadata incomplete"),
    ("Una vita sottile", "film", "feature", "narrative synopsis; metadata incomplete"),
    ("Crazy for Football - Matti per il calcio", "film", "documentary", "narrates the story of a real group (documentary-style)"),
    ("Natale a Roma", "film", "feature", "narrative synopsis; metadata incomplete"),
    ("Inverno di malato", "film", "tv_film", "narrative synopsis; metadata incomplete"),
    ("La tela del ragno (film 1980)", "film", "tv_film", "title says film; narrative synopsis"),
    ("Dalla Terra alla Luna (film 1979)", "film", "tv_film", "title says film; narrative synopsis"),
    ("Superman-Batman - Nemici pubblici", "film", "animated", "animated feature adapted from a comic; no Wikidata item"),
    ("Grachi: Sweet 16 Matilda", "film", "tv_special", "TV special of a series; borderline"),
    ("Un mare di guai (film 1995)", "film", "tv_film", "title says film; Wikidata class is a series (mismatch)"),
    ("Errore fatale (film 1992)", "film", "tv_film", "title says film; Wikidata class is a miniseries (mismatch)"),
    ("102 Boulevard Haussmann", "film", "tv_film", "single narrative work; Wikidata class is a TV programme"),
    ("È solo acqua e vento", "film", "documentary", "the synopsis says 'Il documentario racconta'"),
    # --- projects never released: not recommendable
    ("Ronnie Rocket", "doubtful", "unreleased", "never-produced film project"),
    ("Night Skies", "doubtful", "unreleased", "unmade sequel project"),
    ("The Works (film)", "doubtful", "unreleased", "unfinished/unreleased film"),
]


def apply(rows_without_year: list[dict]) -> dict[str, dict]:
    """film_id -> {verdict, subtype, note}. Raises if a title matches zero or several records."""
    out: dict[str, dict] = {}
    for key, verdict, subtype, note in REVIEW:
        hits = [r for r in rows_without_year if r["film"]["title"] == key or r["film"]["title"].startswith(key)]
        exact = [r for r in hits if r["film"]["title"] == key]
        hits = exact or hits
        if len(hits) != 1:
            raise ValueError(f"manual review entry {key!r} matches {len(hits)} records")
        out[hits[0]["film"]["film_id"]] = {"verdict": verdict, "subtype": subtype, "note": note, "title": hits[0]["film"]["title"]}
    return out
