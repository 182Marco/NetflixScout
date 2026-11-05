"""Phase 3 pre-build survey: what the LOCAL sources can give, and what a targeted Wikidata pass (phase 4) would still need.

    python -m cinema_db.harness.build.survey      # reads only local files; writes docs/cinema_db/SURVEY.json and SURVEY.md

No network, no writes outside docs/cinema_db/. The numbers come from the same extraction code the build uses.
"""
from __future__ import annotations

import collections
import json
import math
from pathlib import Path
from typing import Any

from cinema_db.harness.build.extract import ROLE_PROPS, summarize
from cinema_db.harness.build.snapshot import Snapshot

ROOT = Path(__file__).resolve().parents[3]
FILM_SNAP = ROOT / "tool/RAGWikipediaFilm/data/cache/wikidata/itwiki-20261101-a"
SERIES_SNAP = ROOT / "tool/RAGWikipediaSeries/data/cache/wikidata/itwiki-20261101-series-a"
FILMS = ROOT / "tool/RAGWikipediaFilm/data/clean_v3/films.v3.jsonl"
S5 = ROOT / "tool/RAGWikipediaSeries/data/s5"
OUT_JSON = ROOT / "docs/cinema_db/SURVEY.json"
OUT_MD = ROOT / "docs/cinema_db/SURVEY.md"
BATCH = 50  # wbgetentities accepts up to 50 ids per request


def jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def requests_for(n: int) -> int:
    return math.ceil(n / BATCH)


def survey() -> dict[str, Any]:
    out: dict[str, Any] = {}
    catalog = {r["film_id"]: r for r in jsonl(FILMS)}
    fs = Snapshot(FILM_SNAP)
    labels = fs.labels()
    ents = {q: summarize(q, e) for q, e in fs.entities()}
    ss = Snapshot(SERIES_SNAP)
    labels_s = ss.labels()
    sents = {q: summarize(q, e) for q, e in ss.entities()}
    all_labels = {**labels_s, **labels}

    named_by_catalog: dict[str, str] = {}
    for r in catalog.values():
        for p in (r.get("director") or []) + (r.get("actors") or []):
            if p.get("wikidata_id") and p.get("name"):
                named_by_catalog[p["wikidata_id"]] = p["name"]

    def has_label(q: str) -> bool:
        return bool(all_labels.get(q, {}).get("it") or all_labels.get(q, {}).get("en") or q in named_by_catalog)

    # ---- films: snapshot vs catalog
    in_cat = [q for q in ents if q in catalog]
    out["films"] = {
        "catalog_records": len(catalog), "snapshot_entities": len(ents), "snapshot_in_catalog": len(in_cat),
        "snapshot_not_in_catalog": len(ents) - len(in_cat), "catalog_with_qid": sum(1 for r in catalog.values() if r.get("wikidata_id")),
        "catalog_in_snapshot": sum(1 for r in catalog.values() if r.get("wikidata_id") in ents),
        "snapshot_labels": len(labels), "snapshot_acquired": fs.acquired_range, "snapshot_requests": len(fs.requests),
    }
    cat_in = [ents[q] for q in in_cat]

    def count(pred) -> int:
        return sum(1 for x in cat_in if pred(x))

    out["field_coverage"] = {
        "works_with_title_it": count(lambda x: x["labels"].get("it")), "works_with_original_title": sum(1 for r in catalog.values() if r.get("original_title")),
        "with_publication_date": count(lambda x: x["dates"]), "with_release_place_qualifier": count(lambda x: any(d["places"] for d in x["dates"])),
        "with_runtime_snapshot": count(lambda x: x["runtime_min"]), "with_runtime_catalog": sum(1 for r in catalog.values() if r.get("duration_minutes")),
        "with_year_catalog": sum(1 for r in catalog.values() if r.get("year")),
        "ids": {k: count(lambda x, k=k: x["ids"].get(k)) for k in ("imdb_title", "tmdb_movie", "tmdb_tv", "tvdb_series", "eidr")},
        "with_genres": count(lambda x: x["genres"]), "with_countries": count(lambda x: x["countries"]), "with_languages": count(lambda x: x["languages"]),
        "with_companies": count(lambda x: x["companies"]), "with_itwiki_sitelink": count(lambda x: x["itwiki"]),
        "with_relations": count(lambda x: x["relations"]), "with_franchise": count(lambda x: x["franchises"]),
        "with_financial": count(lambda x: x["financial"]), "with_awards": count(lambda x: x["awards"]),
        "with_any_role": count(lambda x: x["roles"]),
        "roles": {r: count(lambda x, r=r: x["roles"].get(r)) for r in ROLE_PROPS},
    }

    # ---- people by role
    persons: dict[str, collections.Counter] = {r: collections.Counter() for r in ROLE_PROPS}
    credits_total = collections.Counter(); credits_named = collections.Counter()
    for x in cat_in:
        for role, rows in x["roles"].items():
            for row in rows:
                persons[role][row["person"]] += 1
                credits_total[role] += 1
                credits_named[role] += has_label(row["person"])
    all_persons = set().union(*[set(c) for c in persons.values()])
    out["people"] = {
        "distinct_persons": len(all_persons), "named": sum(has_label(q) for q in all_persons),
        "named_by_catalog_only": sum(1 for q in all_persons if q in named_by_catalog and not all_labels.get(q)),
        "by_role": {r: {"credits": credits_total[r], "credits_with_named_person": credits_named[r], "distinct_persons": len(persons[r]),
                        "distinct_named": sum(has_label(q) for q in persons[r])} for r in ROLE_PROPS},
    }

    # ---- vocabularies
    def vocab(field: str) -> dict[str, int]:
        qs = {q for x in cat_in for q in x[field]}
        return {"distinct": len(qs), "labeled": sum(has_label(q) for q in qs), "assertions": sum(len(x[field]) for x in cat_in),
                "assertions_with_label": sum(has_label(q) for x in cat_in for q in x[field])}

    out["vocabularies"] = {"genres": vocab("genres"), "countries": vocab("countries"), "languages": vocab("languages")}
    out["vocabularies"]["catalog_genre_texts_distinct"] = len({g for r in catalog.values() for g in (r.get("genres") or [])})
    comp = collections.Counter(q for x in cat_in for v in x["companies"].values() for q in v)
    out["companies"] = {"distinct": len(comp), "labeled": sum(has_label(q) for q in comp), "assertions": sum(comp.values())}

    # ---- relations and franchises
    rel_total = collections.Counter(); rel_known = collections.Counter(); targets = set(); known_targets = set()
    for x in cat_in:
        for rel, qs in x["relations"].items():
            for q in qs:
                rel_total[rel] += 1
                targets.add(q)
                if q in ents or has_label(q):
                    rel_known[rel] += 1; known_targets.add(q)
    out["relations"] = {"by_type": {k: {"statements": rel_total[k], "target_known": rel_known[k]} for k in rel_total},
                        "distinct_targets": len(targets), "targets_known": len(known_targets), "targets_unlabeled": len(targets - known_targets)}
    fr = collections.Counter(q for x in cat_in for v in x["franchises"].values() for q in v)
    out["franchises"] = {"distinct": len(fr), "labeled": sum(has_label(q) for q in fr), "assertions": sum(fr.values()),
                         "catalog_works_with_franchise_id": sum(1 for r in catalog.values() if r.get("franchise_id"))}

    # ---- awards, money, release dates
    aw = [a for x in cat_in for a in x["awards"]]
    award_items = {a["award"] for a in aw}; ceremonies = {c for a in aw for c in a["ceremony"]}; nominees = {p for a in aw for p in a["nominee"]}
    out["awards"] = {"statements": len(aw), "won": sum(a["outcome"] == "won" for a in aw), "nominated": sum(a["outcome"] == "nominated" for a in aw),
                     "works": count(lambda x: x["awards"]), "distinct_award_items": len(award_items), "award_items_labeled": sum(has_label(q) for q in award_items),
                     "with_year": sum(1 for a in aw if a["times"]), "with_ceremony_item": sum(1 for a in aw if a["ceremony"]),
                     "distinct_ceremony_items": len(ceremonies), "ceremony_items_labeled": sum(has_label(q) for q in ceremonies),
                     "nominee_statements": sum(1 for a in aw if a["nominee"]), "distinct_nominee_persons": len(nominees)}
    fin = [f for x in cat_in for f in x["financial"]]
    units = collections.Counter(f["unit"] for f in fin)
    out["financial"] = {"statements": len(fin), "box_office": sum(f["kind"] == "box_office" for f in fin), "budget": sum(f["kind"] == "budget" for f in fin),
                        "units_top": units.most_common(8), "usd_statements": units.get("Q4917", 0), "with_place": sum(1 for f in fin if f["places"]),
                        "with_time": sum(1 for f in fin if f["times"]), "works": count(lambda x: x["financial"]), "distinct_units": len(units)}
    places = {p for x in cat_in for d in x["dates"] for p in d["places"]}
    out["release_dates"] = {"statements": sum(len(x["dates"]) for x in cat_in), "with_place": sum(1 for x in cat_in for d in x["dates"] if d["places"]),
                            "distinct_places": len(places), "places_labeled": sum(has_label(q) for q in places)}

    # ---- series project
    series = list(jsonl(S5 / "series.jsonl")); seasons = list(jsonl(S5 / "seasons.jsonl")); episodes = list(jsonl(S5 / "episodes.jsonl"))
    meta_rows = sum(1 for _ in jsonl(S5 / "episodes_meta.jsonl")); tvm = list(jsonl(S5 / "tv_movies.jsonl"))
    s_qids = [r["ids"].get("qid") for r in series if (r.get("ids") or {}).get("qid")]
    reliable = [r for r in series if (r.get("ids") or {}).get("qid") and r.get("ids_reliable")]
    out["series"] = {
        "series": len(series), "series_with_qid": len(s_qids), "series_with_reliable_qid": len(reliable), "series_eligible_default": sum(1 for r in series if r.get("default_search_eligible")),
        "series_in_snapshot": sum(1 for q in s_qids if q in sents), "reliable_in_snapshot": sum(1 for r in reliable if r["ids"]["qid"] in sents),
        "seasons": len(seasons), "seasons_logical": sum(1 for r in seasons if r.get("logical")), "seasons_with_number": sum(1 for r in seasons if r.get("season_number") is not None),
        "episodes_with_text": len(episodes), "episodes_numbered": sum(1 for r in episodes if r.get("episode_number") is not None), "episode_meta_rows": meta_rows,
        "tv_movies": len(tvm), "tv_movies_with_qid": sum(1 for r in tvm if (r.get("ids") or {}).get("qid")),
        "snapshot_entities": len(sents), "snapshot_labels": len(labels_s), "snapshot_acquired": ss.acquired_range,
        "series_with_genres_catalog": sum(1 for r in series if r.get("genres")), "series_with_cast_text": sum(1 for r in series if r.get("cast")),
    }
    s_cast = {row["person"] for q, x in sents.items() for rows in x["roles"].values() for row in rows}
    out["series"]["snapshot_persons"] = len(s_cast); out["series"]["snapshot_persons_labeled"] = sum(has_label(q) for q in s_cast)

    # ---- the phase-4 request estimate (wbgetentities, 50 ids per request; nothing is requested now)
    unnamed_persons = {q for q in all_persons | s_cast if not has_label(q)}
    unlabeled_rel = targets - known_targets
    unlabeled_fr = {q for q in fr if not has_label(q)}
    unlabeled_comp = {q for q in comp if not has_label(q)}
    unlabeled_award = {q for q in award_items | ceremonies if not has_label(q)}
    unlabeled_vocab = {q for f in ("genres", "countries", "languages") for x in cat_in for q in x[f] if not has_label(q)}
    unlabeled_places = places - {q for q in places if has_label(q)}
    est = {
        "persons_without_name": (len(unnamed_persons), requests_for(len(unnamed_persons))),
        "persons_all_for_life_dates_and_ids": (len(all_persons | s_cast), requests_for(len(all_persons | s_cast))),
        "relation_targets_without_label": (len(unlabeled_rel), requests_for(len(unlabeled_rel))),
        "franchises_without_name": (len(unlabeled_fr), requests_for(len(unlabeled_fr))),
        "companies_without_name": (len(unlabeled_comp), requests_for(len(unlabeled_comp))),
        "award_and_ceremony_items": (len(unlabeled_award), requests_for(len(unlabeled_award))),
        "currency_units": (out["financial"]["distinct_units"], requests_for(out["financial"]["distinct_units"])),
        "genre_country_language_without_label": (len(unlabeled_vocab), requests_for(len(unlabeled_vocab))),
        "release_places_without_label": (len(unlabeled_places), requests_for(len(unlabeled_places))),
    }
    out["phase4_estimate"] = {k: {"entities": a, "requests": b} for k, (a, b) in est.items()}
    full = sum(b for k, (a, b) in est.items() if k != "persons_without_name")  # persons_all already includes the unnamed ones
    out["phase4_estimate"]["_total_requests_if_everything"] = full
    out["phase4_estimate"]["_total_requests_minimum"] = sum(est[k][1] for k in ("persons_without_name", "award_and_ceremony_items", "currency_units"))

    # ---- IMDb: the most it could add, only where a field is missing AND the work has an IMDb id to join on
    def imdb_gap(field_has) -> dict[str, int]:
        missing = [r for r in catalog.values() if not field_has(r)]
        joinable = [r for r in missing if r.get("imdb_id")]
        return {"missing": len(missing), "missing_and_joinable_by_imdb_id": len(joinable), "missing_without_imdb_id": len(missing) - len(joinable)}

    out["imdb_upper_bound"] = {
        "works_without_imdb_id": sum(1 for r in catalog.values() if not r.get("imdb_id")),
        "year": imdb_gap(lambda r: r.get("year")), "runtime": imdb_gap(lambda r: r.get("duration_minutes")),
        "director": imdb_gap(lambda r: r.get("director")), "cast": imdb_gap(lambda r: r.get("actors")),
        "genres": imdb_gap(lambda r: r.get("genres")), "original_title": imdb_gap(lambda r: r.get("original_title")),
        "writers_in_wikidata": {"works_without_writer": sum(1 for x in cat_in if not x["roles"].get("writer")), "works_without_composer": sum(1 for x in cat_in if not x["roles"].get("composer"))},
    }
    return out


def markdown(d: dict[str, Any]) -> str:
    f, c, p, v = d["films"], d["field_coverage"], d["people"], d["vocabularies"]
    est = d["phase4_estimate"]
    L = ["# Indagine prima della build offline (fase 3)", "",
         "Generata da `python -m cinema_db.harness.build.survey` leggendo **solo file locali** (nessuna rete, nessun credito). Tutti i numeri sono conteggi sui dati reali, tranne le righe indicate come stima.", "",
         "## 1. Fonti locali", "",
         f"- Catalogo film v3: **{f['catalog_records']:,}** film; snapshot Wikidata film: **{f['snapshot_entities']:,}** entità ({f['snapshot_in_catalog']:,} nel catalogo, {f['snapshot_not_in_catalog']:,} no), {f['snapshot_labels']:,} etichette, {f['snapshot_requests']:,} richieste originali (acquisite {f['snapshot_acquired'][0][:10]} – {f['snapshot_acquired'][1][:10]}).",
         f"- Catalogo serie s5: {d['series']['series']:,} serie, {d['series']['seasons']:,} stagioni ({d['series']['seasons_logical']:,} logiche), {d['series']['episodes_with_text']:,} episodi con trama + {d['series']['episode_meta_rows']:,} righe-episodio solo metadati, {d['series']['tv_movies']:,} film TV; snapshot Wikidata serie: {d['series']['snapshot_entities']:,} entità.", "",
         "## 2. Copertura dei campi nei film (su opere del catalogo presenti nello snapshot)", ""]
    n = f["snapshot_in_catalog"]
    pct = lambda x: f"{x:,} ({100 * x / n:.1f}%)"  # noqa: E731
    for label, key in [("Titolo italiano (etichetta)", "works_with_title_it"), ("Data di pubblicazione", "with_publication_date"), ("… con il luogo della pubblicazione (uscita per paese)", "with_release_place_qualifier"),
                       ("Durata (snapshot)", "with_runtime_snapshot"), ("Generi", "with_genres"), ("Paesi", "with_countries"), ("Lingue", "with_languages"), ("Società di produzione/distribuzione", "with_companies"),
                       ("Pagina Wikipedia it", "with_itwiki_sitelink"), ("Relazioni con altre opere", "with_relations"), ("Franchise/serie", "with_franchise"),
                       ("Incassi o budget", "with_financial"), ("Premi o candidature", "with_awards"), ("Almeno un ruolo professionale", "with_any_role")]:
        L.append(f"- {label}: {pct(c[key])}")
    L.append(f"- Identificativi: " + ", ".join(f"{k} {pct(v_)}" for k, v_ in c["ids"].items()))
    L += ["", "## 3. Persone e crediti", "",
          f"- Persone distinte nei ruoli dei film e delle serie: **{p['distinct_persons']:,}** (film); con un nome già disponibile offline: **{p['named']:,}**.", "",
          "| Ruolo | Crediti | Con persona già nominata | Persone distinte | Nominate |", "|---|---|---|---|---|"]
    for r, x in p["by_role"].items():
        L.append(f"| {r} | {x['credits']:,} | {x['credits_with_named_person']:,} | {x['distinct_persons']:,} | {x['distinct_named']:,} |")
    L += ["", "I nomi offline vengono dalle etichette dello snapshot e dal catalogo (registi e attori): gli altri ruoli (sceneggiatori, compositori, fotografi, montatori, produttori) hanno solo il QID e **non si importano** finché la fase 4 non ne legge il nome (un credito senza nome non è utile e non si inventa).", "",
          "## 4. Vocabolari, società, relazioni, franchise", "",
          f"- Generi: {v['genres']['distinct']:,} voci distinte, {v['genres']['labeled']:,} con etichetta; {v['genres']['assertions_with_label']:,} di {v['genres']['assertions']:,} asserzioni etichettate; testi distinti nel catalogo: {v['catalog_genre_texts_distinct']:,}.",
          f"- Paesi: {v['countries']['distinct']:,} voci ({v['countries']['labeled']:,} etichettate); lingue: {v['languages']['distinct']:,} ({v['languages']['labeled']:,} etichettate).",
          f"- Società: {d['companies']['distinct']:,} distinte, {d['companies']['labeled']:,} con nome ({d['companies']['assertions']:,} asserzioni).",
          f"- Relazioni: " + ", ".join(f"{k} {x['statements']:,} (bersaglio noto {x['target_known']:,})" for k, x in d["relations"]["by_type"].items()) + f"; bersagli distinti {d['relations']['distinct_targets']:,}, senza etichetta {d['relations']['targets_unlabeled']:,}.",
          f"- Franchise: {d['franchises']['distinct']:,} distinti, {d['franchises']['labeled']:,} con nome; film con `franchise_id` nel catalogo: {d['franchises']['catalog_works_with_franchise_id']:,}.", "",
          "## 5. Premi, incassi, uscite per paese", "",
          f"- Premi: {d['awards']['statements']:,} asserzioni ({d['awards']['won']:,} vinti, {d['awards']['nominated']:,} candidature) su {d['awards']['works']:,} film; {d['awards']['distinct_award_items']:,} premi/categorie distinti (**{d['awards']['award_items_labeled']:,} con nome**); {d['awards']['with_year']:,} con anno; {d['awards']['with_ceremony_item']:,} con cerimonia ({d['awards']['distinct_ceremony_items']:,} distinte, {d['awards']['ceremony_items_labeled']:,} nominate); {d['awards']['nominee_statements']:,} con la persona candidata ({d['awards']['distinct_nominee_persons']:,} persone).",
          f"- Incassi e budget: {d['financial']['statements']:,} asserzioni su {d['financial']['works']:,} film ({d['financial']['box_office']:,} incassi, {d['financial']['budget']:,} budget); USD (Q4917): {d['financial']['usd_statements']:,}; unità distinte {d['financial']['distinct_units']:,}; con luogo {d['financial']['with_place']:,}, con data {d['financial']['with_time']:,}.",
          f"- Date di pubblicazione: {d['release_dates']['statements']:,}, di cui {d['release_dates']['with_place']:,} con il luogo ({d['release_dates']['distinct_places']:,} luoghi distinti, {d['release_dates']['places_labeled']:,} nominati).", "",
          "## 6. Serie", ""]
    s = d["series"]
    L += [f"- Serie con QID {s['series_with_qid']:,}, con QID **affidabile** {s['series_with_reliable_qid']:,}; presenti nello snapshot: {s['series_in_snapshot']:,} ({s['reliable_in_snapshot']:,} affidabili). Il QID non affidabile non si usa per importare fatti da Wikidata.",
          f"- Stagioni con numero {s['seasons_with_number']:,}; episodi numerati {s['episodes_numbered']:,} su {s['episodes_with_text']:,}; persone nelle serie dello snapshot: {s['snapshot_persons']:,} ({s['snapshot_persons_labeled']:,} nominate).", "",
          "## 7. Fabbisogno stimato per la fase 4 (richieste Wikidata mirate, 50 id per richiesta; STIMA, nulla è stato richiesto)", "",
          "| Tipo | Entità | Richieste |", "|---|---|---|"]
    names = {"persons_without_name": "Persone senza nome (sceneggiatori, compositori, ...)", "persons_all_for_life_dates_and_ids": "Tutte le persone: date di vita, paese, ID IMDb/TMDb",
             "relation_targets_without_label": "Bersagli delle relazioni senza etichetta", "franchises_without_name": "Franchise senza nome", "companies_without_name": "Società senza nome",
             "award_and_ceremony_items": "Premi, categorie e cerimonie", "currency_units": "Unità monetarie (codice ISO 4217)", "genre_country_language_without_label": "Generi/paesi/lingue senza etichetta",
             "release_places_without_label": "Luoghi di uscita senza nome"}
    for k, x in est.items():
        if not k.startswith("_"):
            L.append(f"| {names[k]} | {x['entities']:,} | {x['requests']:,} |")
    L += ["", f"Minimo (nomi delle persone mancanti + premi + valute): **{est['_total_requests_minimum']:,}** richieste. Completo (tutto ciò che sopra): **{est['_total_requests_if_everything']:,}** richieste. A 1 richiesta al secondo sono circa {est['_total_requests_if_everything'] / 3600:.1f} ore; le risposte pesano 0,3–4 MB ciascuna (snapshot film: 344 MB per 829 richieste di entità).", "",
          "## 8. IMDb: il massimo che potrebbe aggiungere (limite superiore, nulla è stato importato)", ""]
    ib = d["imdb_upper_bound"]
    L += [f"- Film del catalogo senza ID IMDb (non agganciabili senza corrispondenza per titolo): {ib['works_without_imdb_id']:,}.", "", "| Campo mancante | Film senza il dato | … con ID IMDb (agganciabili) | … senza ID IMDb |", "|---|---|---|---|"]
    for k in ("year", "runtime", "director", "cast", "genres", "original_title"):
        L.append(f"| {k} | {ib[k]['missing']:,} | {ib[k]['missing_and_joinable_by_imdb_id']:,} | {ib[k]['missing_without_imdb_id']:,} |")
    L += ["", f"Sceneggiatori e compositori mancano in Wikidata per {ib['writers_in_wikidata']['works_without_writer']:,} e {ib['writers_in_wikidata']['works_without_composer']:,} film, ma i dataset IMDb non sono stati letti: **la copertura reale che IMDb aggiungerebbe non è misurabile senza scaricarli** (vietato in questa fase) e va subordinata alle condizioni d'uso.", ""]
    return "\n".join(L)


def main() -> int:
    data = survey()
    OUT_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    OUT_MD.write_text(markdown(data), encoding="utf-8")
    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
