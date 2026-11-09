"""Decision-list classifier of the catalogue records (explainable, deterministic, local data only).

Verdicts:  film | series | topic | other_work | doubtful.   Every record gets the reasons that decided it.
The P31 ('instance of') values were interpreted from the titles they group in the data (see AUDIT_REPORT.md), not guessed.
Nothing is deleted: the output is a classification, the decision to exclude is separate (exclusions.json)."""
from __future__ import annotations

import re

# --- P31 classes, interpreted from the clusters of titles they contain
FILM = {  # cinematic works of any form
    "Q11424": "feature", "Q24862": "short", "Q17517379": "short", "Q506240": "tv_film", "Q202866": "animated",
    "Q20650540": "animated", "Q226730": "silent", "Q20667187": "short", "Q117209498": "animated", "Q14946528": "feature",
    "Q31235": "feature", "Q18011171": "unreleased", "Q18011172": "unreleased", "Q7751682": "serial", "Q104840802": "feature",
    "Q61283808": "feature", "Q10590726": "music_film", "Q110879246": "short", "Q678345": "feature", "Q93204": "documentary",
    "Q112158242": "video_film", "Q98807719": "video_film", "Q1261214": "tv_special", "Q104775758": "tv_special",
    "Q21191270": "tv_film", "Q123126551": "tv_special", "Q717040": "short", "Q47461344": "feature", "Q842256": "video_film",
    "Q67655225": "animated", "Q29168811": "animated", "Q1030329": "short", "Q2301591": "short", "Q1186399": "tv_special",
    "Q25110269": "feature", "Q1144661": "short", "Q4350349": "feature", "Q3331189": "feature", "Q2484376": "feature",
    "Q3334776": "feature", "Q1060398": "short", "Q515": "feature", "Q169930": "music_film", "Q113671041": "animated",
    "Q917641": "short", "Q45107780": "serial", "Q115768274": "feature", "Q17123180": "feature", "Q482994": "music_film",
    "Q29982285": "animated", "Q4167410": "feature", "Q3585697": "documentary", "Q1535153": "feature", "Q118189123": "animated",
    "Q1869909": "short", "Q106046707": "short", "Q653916": "animated", "Q2927074": "feature", "Q240862": "feature",
    "Q18340514": "feature", "Q517386": "feature", "Q127402430": "feature", "Q193977": "music_film", "Q18020205": "short",
    "Q920285": "short", "Q20742776": "feature", "Q11425": "feature", "Q790192": "feature", "Q50914552": "video_film",
    "Q526877": "feature", "Q1635956": "tv_film", "Q43099500": "feature", "Q2620972": "animated", "Q1001378": None,
}
FILM.pop("Q1001378")
SERIES = {"Q5398426": "tv_series", "Q1259759": "miniseries", "Q98701476": "miniseries", "Q21198342": "manga",
          "Q63952888": "anime_series", "Q8274": "manga", "Q15416": "tv_programme", "Q1667921": "novel_series"}
OTHER_WORK = {"Q7889": "video_game", "Q7725634": "literary_work", "Q1004": "comic"}
TOPIC = {"Q201658": "film_genre", "Q110900120": "film_technique", "Q124026596": "film_technique", "Q13406463": "list_article",
         "Q53710030": "fictional_object", "Q989888": "fictional_object", "Q14637321": "fictional_object",
         "Q196600": "media_franchise", "Q2617970": "media_franchise", "Q1001378": "film_genre", "Q108329096": "film_genre",
         "Q59825918": "film_genre", "Q112193867": "medical_condition", "Q7777573": "film_genre", "Q15961987": "film_genre",
         "Q116374620": "film_genre", "Q28640": "profession", "Q12737077": "occupation", "Q3464665": "list_article",
         "Q117467246": "list_article", "Q43229": "organisation"}
AMBIGUOUS_ANIME = {"Q113687694": "ova", "Q220898": "anime", "Q104213567": "anime_film_series", "Q1047299": "anime",
                   "Q56884562": "anthology", "Q58483088": "stage_work", "Q58483083": "stage_work", "Q50062923": "tv_special",
                   "Q79769107": None, "Q21664088": None, "Q3252662": None, "Q21202185": None, "Q3951815": None, "Q170584": None,
                   "Q2416723": None, "Q1415274": None, "Q140723394": None, "Q838795": None, "Q120243801": None}
AMBIGUOUS_ANIME = {k: v for k, v in AMBIGUOUS_ANIME.items() if v}

TITLE_SERIES = re.compile(r"\((miniserie televisiva|serie televisiva|serie animata|anime|manga|serie TV|telefilm)\b", re.I)
TITLE_FILM_SERIES = re.compile(r"\((serie di film|franchise|saga|tetralogia|trilogia)\b", re.I)
TITLE_TOPIC = re.compile(r"^(Film|Cinema|Cortometraggi|Episodi di|Filmografia|Lista|Elenco)\b", re.I)
GENRE_SERIES = re.compile(r"\b(anime|manga|miniserie|serie televisiva|fiction televisiva|sound novel)\b", re.I)
TITLE_FILM = re.compile(r"\((film|cortometraggio|film d'animazione|film incompiuto|serial cinematografico)\b", re.I)


def classify(rec: dict) -> dict:
    """rec: {"film", "flags", "p31", "has_wd"} (see features.load). Returns verdict, subtype, confidence, reasons."""
    f, flags, p31 = rec["film"], rec["flags"], set(rec["p31"])
    title = f["title"]
    infobox = "no_infobox" not in flags
    reasons: list[str] = []
    film_c = sorted(p31 & FILM.keys()); series_c = sorted(p31 & SERIES.keys()); topic_c = sorted(p31 & TOPIC.keys())
    other_c = sorted(p31 & OTHER_WORK.keys()); amb_c = sorted(p31 & AMBIGUOUS_ANIME.keys())
    has_meta = bool(f["imdb_id"] or f["director"])

    def out(verdict, subtype, conf, *why):
        return {"verdict": verdict, "subtype": subtype, "confidence": conf,
                "reasons": reasons + list(why), "infobox_film": infobox, "p31": sorted(p31)}

    if infobox:
        reasons.append("infobox {{Film}} present")
    else:
        reasons.append("included only for a 'Film ...' category (no {{Film}} infobox)")
    # 1) topic pages
    if topic_c:
        return out("topic", TOPIC[topic_c[0]], "high", f"P31={topic_c[0]} ({TOPIC[topic_c[0]]})")
    if TITLE_FILM_SERIES.search(title) or (("Q24856" in p31) and not film_c and not infobox):
        return out("topic", "film_series_page", "high" if TITLE_FILM_SERIES.search(title) else "medium",
                   "page about a series of films, not one film", *(["P31=Q24856 (film series)"] if "Q24856" in p31 else []))
    # 2) other kinds of work
    if other_c and not film_c:
        return out("other_work", OTHER_WORK[other_c[0]], "high" if not infobox else "medium", f"P31={other_c[0]} ({OTHER_WORK[other_c[0]]})")
    # 3) series
    if series_c and not film_c:
        conf = "high" if not infobox else "low"
        v = "series" if not infobox else "doubtful"
        return out(v, SERIES[series_c[0]], conf, f"P31={series_c[0]} ({SERIES[series_c[0]]}), no film class",
                   *( ["has a {{Film}} infobox but Wikidata describes a series: item/page mismatch"] if infobox else []))
    if TITLE_SERIES.search(title) and not (film_c and infobox):
        return out("series", "title_marks_series", "high" if not film_c else "medium", f"title suffix marks a series: {TITLE_SERIES.search(title).group(0)})")
    if amb_c and not film_c:
        return out("doubtful", AMBIGUOUS_ANIME[amb_c[0]], "low", f"P31={amb_c[0]} ({AMBIGUOUS_ANIME[amb_c[0]]}): animation/stage work, film status unclear")
    # 4) films
    if film_c:
        sub = FILM[film_c[0]]
        if infobox:
            return out("film", sub, "high", f"P31={film_c[0]} ({sub})")
        if has_meta or TITLE_FILM.search(title):
            return out("film", sub, "medium", f"P31={film_c[0]} ({sub})", "category-only page with " + ("imdb/director" if has_meta else "film title suffix"))
        return out("doubtful", sub, "low", f"P31={film_c[0]} ({sub}) but category-only page with no director, no IMDb and no film suffix")
    # 5) no usable P31
    if infobox:
        return out("film", "unknown", "medium", "no film-class P31 (" + ("no Wikidata item" if not rec["has_wd"] else "P31=" + ",".join(sorted(p31))) + ") but {{Film}} infobox")
    if TITLE_TOPIC.search(title) or GENRE_SERIES.search(" ".join(f["genres"])) and not f["imdb_id"]:
        return out("doubtful", "unknown", "low", "category-only page, no usable P31, title/genre look like a topic or an animation")
    return out("doubtful", "unknown", "low", "category-only page with no film-class P31" + ("" if f["imdb_id"] else ", no IMDb"))
