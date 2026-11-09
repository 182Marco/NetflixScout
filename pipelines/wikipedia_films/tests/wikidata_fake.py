"""Fake Wikidata transport with invented, realistically shaped wbgetentities responses."""
from __future__ import annotations

import json
import urllib.parse


def _item(qid, **labels):
    return {"id": qid, "labels": {lang: {"language": lang, "value": v} for lang, v in labels.items()}}


def _snak(prop, qid):
    return {"snaktype": "value", "property": prop,
            "datavalue": {"type": "wikibase-entityid", "value": {"entity-type": "item", "id": qid}}}


def _stmt(prop, qid, rank="normal", qualifiers=None):
    out = {"mainsnak": _snak(prop, qid), "rank": rank, "type": "statement"}
    if qualifiers:
        out["qualifiers"] = qualifiers
    return out


def _string(prop, value):
    return {"mainsnak": {"snaktype": "value", "property": prop, "datavalue": {"type": "string", "value": value}},
            "rank": "normal"}


FILM_UNO = {
    "id": "Q1001",
    "labels": {"it": {"language": "it", "value": "Film Uno"}},
    "sitelinks": {"itwiki": {"site": "itwiki", "title": "Film Uno"}},
    "claims": {
        "P57": [_stmt("P57", "Q2001")],
        "P161": [_stmt("P161", "Q2002", qualifiers={"P453": [_snak("P453", "Q3001")]}), _stmt("P161", "Q2003")],
        "P136": [_stmt("P136", "Q4001"), _stmt("P136", "Q4002", rank="deprecated")],
        "P495": [_stmt("P495", "Q5001")],
        "P364": [_stmt("P364", "Q6001")],
        "P577": [{"mainsnak": {"snaktype": "value", "property": "P577", "datavalue": {
            "type": "time", "value": {"time": "+1999-05-12T00:00:00Z", "precision": 11}}}, "rank": "normal"},
                 {"mainsnak": {"snaktype": "value", "property": "P577", "datavalue": {
                     "type": "time", "value": {"time": "+1998-09-01T00:00:00Z", "precision": 11}}}, "rank": "normal"}],
        "P2047": [{"mainsnak": {"snaktype": "value", "property": "P2047", "datavalue": {
            "type": "quantity", "value": {"amount": "+6600", "unit": "http://www.wikidata.org/entity/Q11574"}}},
                   "rank": "normal"}],
        "P345": [_string("P345", "tt0123456")],
        "P1476": [{"mainsnak": {"snaktype": "value", "property": "P1476", "datavalue": {
            "type": "monolingualtext", "value": {"text": "The First Film", "language": "en"}}}, "rank": "normal"}],
    },
}
LABELS = {
    "Q2001": _item("Q2001", it="Anna Bianchi"),
    "Q2002": _item("Q2002", it="Luca Verdi"),
    "Q2003": _item("Q2003", en="Maria Neri"),
    "Q3001": _item("Q3001", it="Il Professore"),
    "Q4001": _item("Q4001", it="drammatico"),
    "Q5001": _item("Q5001", it="Italia"),
    "Q6001": _item("Q6001", it="lingua italiana"),
}


class FakeWikidata:
    def __init__(self, fail_first: int = 0, status: int = 503):
        self.calls: list[dict] = []
        self.sparql_batches: list[int] = []
        self.fail_first, self.status = fail_first, status

    def __call__(self, url, headers, timeout, data=None):
        if data is not None:
            return self._sparql(url, headers, data)
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        self.calls.append({"params": params, "headers": headers})
        if self.fail_first:
            self.fail_first -= 1
            return self.status, {"retry-after": "2"} if self.status == 429 else {}, b"{}"
        if "titles" in params:
            entities = {}
            for index, title in enumerate(params["titles"].split("|"), start=1):
                if title == "Film Uno":
                    entities["Q1001"] = FILM_UNO
                else:
                    entities[f"-{index}"] = {"site": "itwiki", "title": title, "missing": ""}
            return 200, {}, json.dumps({"entities": entities}).encode()
        ids = params["ids"].split("|")
        return 200, {}, json.dumps({"entities": {i: LABELS[i] for i in ids if i in LABELS}}).encode()

    def _sparql(self, url, headers, data):
        import re

        query = urllib.parse.parse_qs(data.decode())["query"][0]
        self.calls.append({"params": {"sparql": query}, "headers": headers, "url": url})
        if self.fail_first:
            self.fail_first -= 1
            return self.status, {}, b"{}"
        ids = re.findall(r"wd:(Q\d+)", query)
        self.sparql_batches.append(len(ids))
        rows = []
        for qid in ids:
            for lang, label in LABELS.get(qid, {}).get("labels", {}).items():
                rows.append({"item": {"value": f"http://www.wikidata.org/entity/{qid}"},
                             "lang": {"value": lang}, "label": {"value": label["value"]}})
        return 200, {}, json.dumps({"results": {"bindings": rows}}).encode()
