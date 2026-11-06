"""A miniature of the local sources (Wikidata snapshots, film catalogue, series catalogue) written to a temp folder, with INVENTED
data in the real formats, so the offline build can be tested end to end without the real files."""
from __future__ import annotations

import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

from cinema_db.harness.build.build import Inputs


def item(prop: str, qid: str, qualifiers: dict | None = None, rank: str = "normal") -> dict:
    c = {"mainsnak": {"snaktype": "value", "property": prop, "datavalue": {"value": {"entity-type": "item", "id": qid}, "type": "wikibase-entityid"}}, "rank": rank, "type": "statement"}
    if qualifiers:
        c["qualifiers"] = qualifiers
    return c


def q_item(prop: str, qid: str) -> dict:
    return {"snaktype": "value", "property": prop, "datavalue": {"value": {"entity-type": "item", "id": qid}, "type": "wikibase-entityid"}}


def q_text(prop: str, text: str) -> dict:
    return {"snaktype": "value", "property": prop, "datavalue": {"value": text, "type": "string"}}


def string(prop: str, value: str) -> dict:
    return {"mainsnak": {"snaktype": "value", "property": prop, "datavalue": {"value": value, "type": "string"}}, "rank": "normal", "type": "statement"}


def time(prop: str, when: str, precision: int = 11, qualifiers: dict | None = None) -> dict:
    c = {"mainsnak": {"snaktype": "value", "property": prop, "datavalue": {"value": {"time": when, "precision": precision}, "type": "time"}}, "rank": "normal", "type": "statement"}
    if qualifiers:
        c["qualifiers"] = qualifiers
    return c


def quantity(prop: str, amount: str, unit: str, qualifiers: dict | None = None) -> dict:
    c = {"mainsnak": {"snaktype": "value", "property": prop, "datavalue": {"value": {"amount": amount, "unit": "http://www.wikidata.org/entity/" + unit}, "type": "quantity"}}, "rank": "normal", "type": "statement"}
    if qualifiers:
        c["qualifiers"] = qualifiers
    return c


def entity(qid: str, it: str | None, en: str | None, claims: dict[str, list], itwiki: str | None = None) -> dict:
    labels = {}
    if it:
        labels["it"] = {"language": "it", "value": it}
    if en:
        labels["en"] = {"language": "en", "value": en}
    e: dict[str, Any] = {"type": "item", "id": qid, "labels": labels, "claims": claims}
    if itwiki:
        e["sitelinks"] = {"itwiki": {"site": "itwiki", "title": itwiki}}
    return e


def write_snapshot(root: Path, entities: list[dict], labels: dict[str, dict[str, str]]) -> Path:
    (root / "bodies").mkdir(parents=True, exist_ok=True)
    lines = []

    def put(endpoint: str, params: dict, body: dict) -> None:
        raw = json.dumps(body).encode()
        sha = hashlib.sha256(raw).hexdigest()
        (root / "bodies" / f"{sha}.json.gz").write_bytes(gzip.compress(raw))
        lines.append(json.dumps({"acquired_at": "2026-01-01T00:00:00Z", "bytes": len(raw), "endpoint": endpoint, "key": sha[:16], "params": params, "sha256": sha, "status": 200}))

    put("https://www.wikidata.org/w/api.php", {"action": "wbgetentities", "props": "claims|labels|sitelinks", "titles": "x"}, {"entities": {e["id"]: e for e in entities}, "success": 1})
    bindings = [{"item": {"type": "uri", "value": "http://www.wikidata.org/entity/" + q}, "label": {"xml:lang": lang, "type": "literal", "value": v}, "lang": {"type": "literal", "value": lang}}
                for q, ls in labels.items() for lang, v in ls.items()]
    put("https://query.wikidata.org/sparql", {"query": "SELECT ?item ?lang ?label WHERE { VALUES ?item { wd:Q1 } }"}, {"head": {"vars": ["item", "lang", "label"]}, "results": {"bindings": bindings}})
    (root / "requests.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def film(film_id: str, qid: str | None, title: str, year: int | None, **extra) -> dict:
    base = {"film_id": film_id, "wikidata_id": qid, "title": title, "original_title": None, "year": year, "work_format": "feature", "duration_minutes": None, "imdb_id": None,
            "director": [], "actors": [], "genres": [], "country": [], "wikipedia_url": f"https://it.wikipedia.org/wiki/{title.replace(' ', '_')}", "wikipedia_page_id": 1, "source_revision_id": "9"}
    base.update(extra)
    return base


def make_inputs(tmp: Path, *, awards_demo: bool = False) -> Inputs:
    unit_usd, unit_other = "Q4917", "Q9999"
    entities = [
        entity("Q9001", "Film di prova", "Sample Film", {
            "P57": [item("P57", "Q9101")],
            "P161": [item("P161", "Q9102", {"P4633": [q_text("P4633", "Eroe")]}), item("P161", "Q9103")],
            "P58": [item("P58", "Q9104")],  # a writer nobody named offline: the credit must NOT be imported
            "P136": [item("P136", "Q9201"), item("P136", "Q9202"), item("P136", "Q9203")],
            "P495": [item("P495", "Q9301")], "P364": [item("P364", "Q9401")],
            "P577": [time("P577", "+1982-06-25T00:00:00Z", 11, {"P291": [q_item("P291", "Q9301")]}), time("P577", "+1983-01-01T00:00:00Z", 9)],
            "P2047": [{"mainsnak": {"snaktype": "value", "property": "P2047", "datavalue": {"value": {"amount": "+109", "unit": "http://www.wikidata.org/entity/Q7727"}, "type": "quantity"}}, "rank": "normal"}],
            "P2142": [quantity("P2142", "+20000000", unit_usd, {"P3005": [q_item("P3005", "Q13780930")]})],
            "P2130": [quantity("P2130", "+1500000", unit_usd), quantity("P2130", "+900000", unit_other)],
            "P345": [string("P345", "tt9000002")], "P4947": [string("P4947", "9001")], "P2704": [string("P2704", "10.5240/AAAA")],
            "P144": [item("P144", "Q9002"), item("P144", "Q9998")],  # a labelled source work and one nobody named
            "P155": [item("P155", "Q9003")], "P8345": [item("P8345", "Q9601")], "P272": [item("P272", "Q9501"), item("P272", "Q9502")],
            "P166": [item("P166", "Q9701")],
        }, itwiki="Film di prova"),
        entity("Q9003", "Prequel di prova", None, {"P57": [item("P57", "Q9101")], "P345": [string("P345", "tt9000003")], "P156": [item("P156", "Q9001")]}, itwiki="Prequel di prova"),
        entity("Q9004", "Film gemello", None, {"P345": [string("P345", "tt9000002")]}, itwiki="Film gemello"),  # same IMDb id as Q9001: a conflict
        entity("Q9005", None, "Only English", {"P136": [item("P136", "Q9204")]}, itwiki="Only English"),
    ]
    if awards_demo:
        entities[0]["claims"]["P162"] = [item("P162", "Q9502"), item("P162", "Q9503")]  # Q9502: an organisation that is also a production company; Q9503: a HUMAN entered as one
        entities[0]["claims"]["P272"] = entities[0]["claims"]["P272"] + [item("P272", "Q9503")]
        entities[0]["claims"]["P577"] = entities[0]["claims"]["P577"] + [time("P577", "+1982-09-01T00:00:00Z", 11, {"P291": [q_item("P291", "Q9310")]}),
                                                                         time("P577", "+1982-09-02T00:00:00Z", 11, {"P291": [q_item("P291", "Q9311")]})]
        when = {"snaktype": "value", "property": "P585", "datavalue": {"value": {"time": "+1983-01-01T00:00:00Z", "precision": 9}, "type": "time"}}
        entities[0]["claims"]["P1411"] = [item("P1411", "Q9702", {"P805": [q_item("P805", "Q9710")], "P2453": [q_item("P2453", "Q9102"), q_item("P2453", "Q9104")]}),
                                          item("P1411", "Q9704"), item("P1411", "Q9703", {"P805": [q_item("P805", "Q9711")]})]
        entities[0]["claims"]["P166"] += [item("P166", "Q9703", {"P585": [when]}), item("P166", "Q9702", {"P805": [q_item("P805", "Q9710")], "P2453": [q_item("P2453", "Q9102")]}),
                                              # Wikidata names the WINNER of a P166 statement with P1346: a known person (Q9101) becomes a result, a company (Q9502) never a person
                                              item("P166", "Q9702", {"P805": [q_item("P805", "Q9710")], "P1346": [q_item("P1346", "Q9101"), q_item("P1346", "Q9502")]})]
    labels = {
        "Q9101": {"it": "Ann Regista", "en": "Ann Director"}, "Q9102": {"it": "Bob Attore"}, "Q9201": {"it": "film drammatico", "en": "drama film"},
        "Q9202": {"it": "film strano"}, "Q9203": {"en": "psychological thriller"}, "Q9204": {"en": "romantic comedy film"},
        "Q9301": {"it": "Italia", "en": "Italy"}, "Q9401": {"it": "italiano", "en": "Italian"}, "Q9002": {"it": "Romanzo di prova", "en": "Sample Novel"},
        "Q9501": {}, "Q9502": {"it": "Casa di Prova"}, "Q9601": {"it": "Saga di prova"},
    }
    film_snap = write_snapshot(tmp / "film_snap", entities, labels)
    catalog = write_jsonl(tmp / "films.v3.jsonl", [
        film("Q9001", "Q9001", "Film di prova", 1982, original_title="Test Film", duration_minutes=None, imdb_id="tt9000001",
             director=[{"name": "Ann Regista", "wikidata_id": "Q9101"}], actors=[{"name": "Bob Attore", "wikidata_id": "Q9102", "character": "Eroe catalogo"}, {"name": "Cara Attrice", "wikidata_id": "Q9103", "character": None}]),
        film("Q9003", "Q9003", "Prequel di prova", 1980, work_format="short", duration_minutes=20),
        film("Q9004", "Q9004", "Film gemello", 1990, imdb_id="tt9000002"),
        film("Q9005", "Q9005", "Only English", 2001, work_format="tv_special"),
        film("wp-77", None, "Senza Wikidata", 1950, work_format="silent"),
    ])
    series_entities = [
        entity("Q9801", "Serie di prova", "Sample Show", {"P495": [item("P495", "Q9301")], "P136": [item("P136", "Q9201")], "P161": [item("P161", "Q9102")], "P4983": [string("P4983", "5555")]}, itwiki="Serie di prova"),
        entity("Q9802", "Serie sbagliata", None, {"P161": [item("P161", "Q9101")]}),  # unreliable: must not be used
        entity("Q9005", "Solo inglese", "Only English", {"P136": [item("P136", "Q9204")]}, itwiki="Only English"),  # same item as in the film snapshot: the genre arrives twice
        entity("Q9803", "Film TV di prova", "Sample TV Film", {"P136": [item("P136", "Q9201")]}, itwiki="Film TV di prova"),
    ]
    series_snap = write_snapshot(tmp / "series_snap", series_entities, {})
    s5 = tmp / "s5"
    s5.mkdir()
    (s5 / "manifest.json").write_text('{"x": 1}', encoding="utf-8")
    write_jsonl(s5 / "series.jsonl", [
        {"record_id": "wp-100", "title": "Serie di prova (serie televisiva)", "subtype": "tv_series", "default_search_eligible": True, "ids": {"qid": "Q9801", "imdb_id": "tt9100001"}, "ids_reliable": True,
         "year": 2016, "year_end": 2018, "genres": ["azione", "genere ignoto", "—"], "country": ["Italia", "Atlantide"], "network": "Rai Uno", "original_title": "Sample Show", "wikipedia_url": "https://it.wikipedia.org/wiki/Serie_di_prova_(serie_televisiva)", "revision_id": "5", "catalog_class": "series"},
        {"record_id": "wp-101", "title": "Serie dubbia", "subtype": "tv_series", "default_search_eligible": True, "ids": {"qid": "Q9802", "imdb_id": "tt9100002"}, "ids_reliable": False, "year": 2010, "genres": [], "country": [], "catalog_class": "series"},
        {"record_id": "wp-102", "title": "Pagina mista", "subtype": "anime", "default_search_eligible": False, "ids": {}, "catalog_class": "franchise_page_mixed_media"},
        {"record_id": "wp-103", "title": "Miniserie di prova", "subtype": "miniseries", "default_search_eligible": True, "ids": {}, "ids_reliable": False, "year": 2020, "genres": [], "country": [], "catalog_class": "series"},
    ])
    write_jsonl(s5 / "seasons.jsonl", [
        {"record_id": "wp-100#season1", "series_id": "wp-100", "season_number": 1, "title": "Serie di prova – stagione 1", "wikipedia_url": None, "logical": True},
        {"record_id": "wp-100#season2", "series_id": "wp-100", "season_number": 2, "title": "Serie di prova – stagione 2", "wikipedia_url": "https://it.wikipedia.org/wiki/Serie_di_prova_(seconda_stagione)", "logical": False},
        {"record_id": "wp-102#season1", "series_id": "wp-102", "season_number": 1, "title": "Pagina mista – stagione 1", "wikipedia_url": None, "logical": True},
    ])
    write_jsonl(s5 / "episodes.jsonl", [
        {"record_id": "wp-300", "series_id": "wp-100", "season_id": "wp-100#season1", "season_number": 1, "episode_number": 1, "title": "Pilota", "title_it": None, "title_original": "Pilot",
         "air_dates": ["15 luglio 2016"], "source": "episode_page", "ids": {"imdb_id": "tt9200001", "qid": None}, "wikipedia_url": "https://it.wikipedia.org/wiki/Pilota_(Serie_di_prova)"},
        {"record_id": "wp-301", "series_id": "wp-999", "season_id": None, "season_number": 1, "episode_number": 1, "title": "Orfano", "air_dates": []},
    ])
    write_jsonl(s5 / "episodes_meta.jsonl", [
        {"record_id": "wp-100#r0", "series_id": "wp-100", "season_id": None, "season_number": 1, "episode_number": 1, "title": "Pilota (riga)", "air_dates": ["15 luglio 2016"], "source": "table_row", "wikipedia_url": "https://it.wikipedia.org/wiki/Episodi_di_Serie_di_prova"},
        {"record_id": "wp-100#r1", "series_id": "wp-100", "season_id": None, "season_number": 2, "episode_number": 1, "title": "Ritorno", "air_dates": ["data sconosciuta"], "source": "table_row", "wikipedia_url": "https://it.wikipedia.org/wiki/Episodi_di_Serie_di_prova"},
        {"record_id": "wp-100#r2", "series_id": "wp-100", "season_id": None, "season_number": None, "episode_number": None, "title": "Speciale", "air_dates": ["dicembre 2017"]},
    ])
    write_jsonl(s5 / "tv_movies.jsonl", [
        # the same work as the film catalogue's Q9005 / page "Only_English": ONE work must result, decided by this catalogue
        {"record_id": "wp-501", "title": "Solo inglese", "ids": {"qid": "Q9005", "imdb_id": "tt9300002"}, "ids_reliable": True, "year": 2001, "genres": ["drammatico"],
         "wikipedia_url": "https://it.wikipedia.org/wiki/Only_English", "revision_id": "4"},
        {"record_id": "wp-500", "title": "Film TV di prova", "ids": {"qid": "Q9803", "imdb_id": "tt9300001", "tmdb_id": 777}, "ids_reliable": True, "year": 2003, "genres": ["commedia"], "wikipedia_url": "https://it.wikipedia.org/wiki/Film_TV_di_prova", "revision_id": "3"},
    ])
    return Inputs(film_snap, series_snap, catalog, s5)


def input_files(inputs: Inputs) -> list[Path]:
    return sorted(p for root in (inputs.film_snapshot, inputs.series_snapshot, inputs.film_catalog, inputs.series_dir) for p in ([root] if root.is_file() else root.rglob("*")) if p.is_file())


def sparql_row(qid: str, kind: str, value: str, aux: str, rank: str = "NormalRank") -> dict:
    return {"p": {"type": "uri", "value": "http://www.wikidata.org/entity/" + qid}, "kind": {"type": "literal", "value": kind}, "value": {"type": "literal", "value": value},
            "aux": {"type": "literal", "value": aux}, "rank": {"type": "uri", "value": "http://wikiba.se/ontology#" + rank}}


def make_phase4(root: Path) -> Path:
    """An INVENTED phase-4 snapshot in the real format (SPARQL person rows + wbgetentities items) that completes the miniature."""
    (root / "bodies").mkdir(parents=True, exist_ok=True)
    lines = []

    def put(endpoint: str, params: dict, body: dict) -> None:
        raw = json.dumps(body).encode()
        sha = hashlib.sha256(raw).hexdigest()
        (root / "bodies" / f"{sha}.json.gz").write_bytes(gzip.compress(raw))
        lines.append(json.dumps({"acquired_at": "2026-02-02T00:00:00Z", "bytes": len(raw), "endpoint": endpoint, "key": sha[:16], "params": params, "sha256": sha, "status": 200}))

    rows = [
        sparql_row("Q9104", "label", "Dora Sceneggiatrice", "it"), sparql_row("Q9104", "label", "Dora Writer", "en"),
        sparql_row("Q9104", "birth", "1950-03-04T00:00:00Z", "11"), sparql_row("Q9104", "death", "1999-01-01T00:00:00Z", "9"), sparql_row("Q9104", "death", "2001-05-05T00:00:00Z", "11"),
        sparql_row("Q9105", "label", "Solo Multilingua", "mul"), sparql_row("Q9105", "birth", "1960-01-01T00:00:00Z", "9"), sparql_row("Q9105", "birth", "1900-01-01T00:00:00Z", "11", "DeprecatedRank"),
        sparql_row("Q9106", "label", "Nata Dopo Morta", "en"), sparql_row("Q9106", "birth", "1990-01-01T00:00:00Z", "9"), sparql_row("Q9106", "death", "1980-01-01T00:00:00Z", "9"),
        sparql_row("Q9102", "label", "Bob Altro Nome", "it"), sparql_row("Q9102", "birth", "1941-02-03T00:00:00Z", "11"),
    ]
    put("https://query.wikidata.org/sparql", {"endpoint": "sparql", "query": "x"}, {"results": {"bindings": rows}})
    ents = {
        "Q9503": entity("Q9503", "Vecchio Produttore", None, {"P31": [item("P31", "Q5")]}),
        "Q9310": entity("Q9310", "Atlantide Libera", "Free Atlantis", {"P31": [item("P31", "Q3624078")], "P297": [string("P297", "AL")]}),  # a sovereign state
        "Q9311": entity("Q9311", "Festival di Prova 1982", None, {"P31": [item("P31", "Q27787439")]}),  # a festival edition: not a country
        "Q9998": entity("Q9998", "Romanzo senza nome offline", "Nameless Novel", {}),
        "Q9501": entity("Q9501", "Casa Senza Nome", None, {"P17": [item("P17", "Q9301")]}),
        "Q9999": entity("Q9999", None, "euro", {"P498": [string("P498", "EUR")]}),
        "Q9301": entity("Q9301", "Italia", "Italy", {"P297": [string("P297", "IT")]}),
        "Q9401": entity("Q9401", "italiano", "Italian", {"P218": [string("P218", "it")], "P220": [string("P220", "ita")]}),
        "Q9700": entity("Q9700", "Premio di Prova", "Test Prize", {"P17": [item("P17", "Q9301")]}),
        "Q9702": entity("Q9702", "Miglior regia", "Best Direction", {"P361": [item("P361", "Q9700")]}),
        "Q9703": entity("Q9703", "Miglior film", "Best Picture", {"P361": [item("P361", "Q9700")]}),
        "Q9704": entity("Q9704", "Premio orfano", None, {}),
        "Q9711": entity("Q9711", "5ª cerimonia del Premio di Prova", None, {"P179": [item("P179", "Q9700")], "P585": [time("P585", "+1983-04-01T00:00:00Z", 11)]}),  # same award, year and label
        "Q9710": entity("Q9710", "5ª cerimonia del Premio di Prova", None, {"P179": [item("P179", "Q9700")], "P585": [time("P585", "+1983-04-01T00:00:00Z", 11)]}),
    }
    put("https://www.wikidata.org/w/api.php", {"action": "wbgetentities", "props": "labels|claims"}, {"entities": ents})
    (root / "requests.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root
