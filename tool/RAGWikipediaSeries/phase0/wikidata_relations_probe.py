"""Phase 0 Wikidata probe 2: reliability of season -> series relations (aggregate queries only)."""
from __future__ import annotations

import json
import logging

from ..common import DATA_DIR
from .wikidata_probe import load_client

SITE = "?{v} schema:about ?{x} ; schema:isPartOf <https://it.wikipedia.org/> ."
QUERIES = {
    "seasons_itwiki": "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s wdt:P31 wd:Q3464665 . " + SITE.format(v="a", x="s") + " }",
    "seasons_itwiki_with_parent": "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s wdt:P31 wd:Q3464665 . " + SITE.format(v="a", x="s") + " ?s wdt:P179 ?p . }",
    "seasons_itwiki_parent_itwiki": "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s wdt:P31 wd:Q3464665 . " + SITE.format(v="a", x="s") + " ?s wdt:P179 ?p . " + SITE.format(v="b", x="p") + " }",
    "seasons_itwiki_with_ordinal": "SELECT (COUNT(DISTINCT ?s) AS ?n) WHERE { ?s wdt:P31 wd:Q3464665 . " + SITE.format(v="a", x="s") + " ?s p:P179 ?st . ?st pq:P1545 ?o . }",
    "seasons_itwiki_with_several_parents": "SELECT (COUNT(*) AS ?n) WHERE { SELECT ?s (COUNT(DISTINCT ?p) AS ?k) WHERE { ?s wdt:P31 wd:Q3464665 . " + SITE.format(v="a", x="s") + " ?s wdt:P179 ?p . } GROUP BY ?s HAVING (?k > 1) }",
    "series_itwiki_with_itwiki_season": "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { ?p wdt:P31 wd:Q5398426 . " + SITE.format(v="b", x="p") + " ?s wdt:P179 ?p . ?s wdt:P31 wd:Q3464665 . " + SITE.format(v="a", x="s") + " }",
    "series_itwiki_total": "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { ?p wdt:P31 wd:Q5398426 . " + SITE.format(v="b", x="p") + " }",
    "episodes_itwiki_parent_itwiki": "SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE { ?e wdt:P31 wd:Q21191270 . " + SITE.format(v="a", x="e") + " ?e wdt:P179 ?p . " + SITE.format(v="b", x="p") + " }",
    "episodes_itwiki_with_season_prop": "SELECT (COUNT(DISTINCT ?e) AS ?n) WHERE { ?e wdt:P31 wd:Q21191270 . " + SITE.format(v="a", x="e") + " ?e wdt:P4908 ?x . }",
    "series_all_with_number_of_episodes_known_itwiki": "SELECT (COUNT(DISTINCT ?p) AS ?n) WHERE { ?p wdt:P31 wd:Q5398426 . " + SITE.format(v="b", x="p") + " ?p wdt:P2437 ?x . }",
}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    client = load_client()
    out = {}
    for name, query in QUERIES.items():
        try:
            rows = client.sparql_json(query)["results"]["bindings"]
            out[name] = int(rows[0]["n"]["value"]) if rows else 0
        except Exception as error:
            out[name] = f"error: {str(error)[:120]}"
        logging.info("%s = %s", name, out[name])
    out["_requests"] = {"network": client.network_requests, "snapshot_hits": client.snapshot_hits}
    (DATA_DIR / "phase0" / "wikidata_relations_probe.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
