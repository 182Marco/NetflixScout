"""Phase S4b: evidence-based review of uncertain and class-conflicting records -> `review/overrides.json`.

Rules use only data already on disk (S1 evidence, S2 Wikidata classes P31, S3 relations). Each decision is
written with the ORIGINAL classification and the reasons; anything the evidence does not settle stays as it is.
Rerunnable: it replaces only the entries it owns (`rule` field U1/U2/U3/D1), never the manual ones.

  U1  uncertain TV movie -> tv_movie   Wikidata class is a film (television film / film) AND a narrative genre is declared;
                                       docudrama mixes need the class "television film" itself; sketch / special / short stay uncertain
  U2  uncertain programme -> excluded  the Wikidata class is exclusively a radio programme
  U3  uncertain programme -> series    the Wikidata class is explicitly an animated / drama series or a miniseries
  D1  miniseries: FLAG possible_tv_movie (not reclassified: two community sources disagree, so the evidence is insufficient)
                                       infobox says miniseries but Wikidata says (television) film AND no season / episode pages,
                                       no declared episode count > 1, no "N puntate / episodi / parti" (N >= 2) and no self-description as
                                       miniserie / serie / sceneggiato / puntata / serata / episodio / stagione / parte in its title or text

    python -m pipelines.wikipedia_series.review_rules [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter

from .build_clean import S5
from .build_relations import OVERRIDES, read
from .common import DATA_DIR

S1, S2, S3 = DATA_DIR / "s1", DATA_DIR / "s2", DATA_DIR / "s3"
OWNED = ("U1", "U2", "U3", "D1")
NARRATIVE = ("drammatico", "commedia", "thriller", "horror", "fantascienza", "poliziesco", "giallo", "azione", "avventura", "fantastico",
             "sentimentale", "romantic", "western", "drama", "natalizio", "fantasy")
FILM_CLASSES = ("television film", "film", "television film broadcast in two parts")
NOT_PLAIN_FILM = ("short film", "television special", "animated short film")
SERIAL_TEXT = re.compile(r"\b(?:(?:[2-9]|\d{2,})|due|tre|quattro|cinque|sei|otto|dieci)\s+(?:puntate|episodi|parti)\b", re.I)
# the page's own words: a text (or a title) that calls the work a series / miniseries / episodes outweighs the Wikidata class
SELF_DESCRIBED_SERIAL = re.compile(r"miniserie|serie televisiva|serie tv|sceneggiato|\bpuntat|\bserat|\bepisod|\bstagion|\bparte\b|\bparti\b", re.I)


def labels_of(entity: dict | None, labels: dict) -> list[str]:
    return sorted((labels.get(q) or {}).get("en") or q for q in (entity or {}).get("instance_of", []))


def declared(rec: dict) -> int | None:
    match = re.match(r"\s*(\d+)", str(rec.get("declared_episodes") or ""))
    return int(match.group(1)) if match else None


def decide() -> dict[str, dict]:
    labels = json.loads((S2 / "wikidata_classes.json").read_text())
    entities = {e["page_id"]: e for e in read(S2 / "wikidata_entities.jsonl")}
    s1_unc = {r["page_id"]: r for r in read(S1 / "uncertain.jsonl")}
    children = Counter(e["parent_page_id"] for e in read(S3 / "relations.jsonl") if e["parent_page_id"])
    s1_series = {r["page_id"]: r for r in read(S1 / "series.jsonl")}
    out: dict[str, dict] = {"reclassify": {}, "exclude": {}, "flag": {}}

    for rec in read(S5 / "uncertain.jsonl"):
        pid = rec["page_id"]
        cls = labels_of(entities.get(pid), labels)
        original = {"bucket": "uncertain", "subtype": rec["subtype"], "wikidata_classes": cls,
                    "classification": (s1_unc.get(pid) or {}).get("classification"), "programme_reason": (s1_unc.get(pid) or {}).get("programme_reason")}
        if rec["subtype"] == "tv_movie":
            genres = [g.lower() for g in rec.get("genres", [])]
            narrative = any(any(n in g for n in NARRATIVE) for g in genres)
            filmish = [c for c in cls if c in FILM_CLASSES]
            documentary = any("documentar" in g or "docufiction" in g for g in genres)
            plain = not any(c in NOT_PLAIN_FILM for c in cls) and "sketch" not in " ".join(genres)
            if filmish and narrative and plain and (not documentary or "television film" in cls):
                out["reclassify"][str(pid)] = {"to": "tv_movie", "rule": "U1", "original": original,
                                               "reason": f"Wikidata class {cls} is a film and the page declares narrative genre(s) {genres}; the infobox already says film TV"
                                                         + (" (docudrama mix accepted only because the class is 'television film')" if documentary else "")}
        else:
            if cls and all("radio" in c for c in cls):
                out["exclude"][str(pid)] = {"rule": "U2", "original": original, "reason": f"Wikidata class {cls} is exclusively a radio programme; the Programma infobox is also used for radio shows"}
            elif any(c in ("animated television series", "drama television series", "miniseries") for c in cls):
                out["reclassify"][str(pid)] = {"to": "series", "rule": "U3", "original": original,
                                               "reason": f"Wikidata class {cls} states a scripted / animated series, which settles the ambiguous genre {rec.get('genres')}"}

    for rec in read(S5 / "series.jsonl"):
        if rec["subtype"] != "miniseries" or not rec["class_check"].startswith("wikidata_film") or "mixed_media" in rec["flags"]:
            continue
        pid = rec["page_id"]
        cls = labels_of(entities.get(pid), labels)
        if not [c for c in cls if c in FILM_CLASSES] or any(c in NOT_PLAIN_FILM for c in cls):
            continue
        n = declared(rec)
        text = (rec["plot_text"] if rec["text_kind"] == "plot" else rec["lead_text"])[:2500]
        s1 = s1_series.get(pid, {})
        blockers = [name for name, hit in (("has_season_or_episode_pages", children[pid] > 0 or s1.get("has_episode_pages")),
                                           ("declared_episodes>1", bool(n and n > 1)), ("episode_rows_in_page", s1.get("inline_episode_row_count", 0) > 1),
                                           ("text_mentions_N_parts", bool(SERIAL_TEXT.search(text))),
                                           ("page_calls_itself_serial", bool(SELF_DESCRIBED_SERIAL.search(text) or SELF_DESCRIBED_SERIAL.search(rec["title"])))) if hit]
        if not blockers:
            out["flag"][str(pid)] = {"flag": "possible_tv_movie", "rule": "D1", "original": {"bucket": "series", "subtype": "miniseries", "wikidata_classes": cls, "class_check": rec["class_check"]},
                                     "reason": f"kept as miniseries (infobox) but flagged: Wikidata class {cls} is a film, and the page has no season/episode pages, no declared episode count > 1 and its own title and text never call it a series, miniseries, episode or part"}
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    new = decide()
    data = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    for section in ("reclassify", "exclude", "flag"):
        kept = {k: v for k, v in data.get(section, {}).items() if v.get("rule") not in OWNED}
        data[section] = {**kept, **new[section]}
    summary = {s: dict(Counter(v["rule"] for v in new[s].values())) for s in new}
    print(json.dumps(summary, indent=1))
    if not args.dry_run:
        OVERRIDES.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
