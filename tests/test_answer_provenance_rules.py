"""The text written for the user never names a source or provider (TMDb, OMDb, IMDb as a source, MovieLens,
Wikipedia, YouTube, the RAG...): the interface shows where the data comes from (presenters). Regression of the
live check of 2026-10-28 (docs/omdb_routing_live_report.md, case 8: «ordered by TMDb audience rating»).

These tests read the prompts: they show the instructions no longer ask for, or model, a provider name; what the
model really writes is only observed live."""
from __future__ import annotations

import json
import re

import app as app_module
from omdb_support import by_endpoint, make_tool, record
from preferences import behavior

ORCH = app_module.CONFIG["orchestrator"]
FINAL = ORCH["final_instructions"]
TOOL_RULES = ORCH["tool_final_instructions"]
ANSWER_TEXTS = [FINAL, *TOOL_RULES.values()]

# Instructions that would make the model write a provider as the origin or as an adjective of a data point.
PROVIDER_AS_ORIGIN = (
    "voti TMDb", "pubblico TMDb", "titolo TMDb", "registrate da TMDb", "MovieLens non distingue",
    "su YouTube", "risultati di ricerca YouTube", "(TMDb, IMDb)",
)


def test_no_answer_instruction_asks_to_write_a_provider_as_the_origin_of_a_datum() -> None:
    for text in ANSWER_TEXTS:
        for phrase in PROVIDER_AS_ORIGIN:
            assert phrase not in text, phrase


def test_the_general_rule_bans_provider_names_even_as_adjectives_and_allows_score_names_only_as_names() -> None:
    assert "Non nominare mai TMDb, OMDb, MovieLens, Wikipedia, YouTube, il RAG o altri servizi" in FINAL
    assert "nemmeno come aggettivo o complemento" in FINAL and "«voto TMDb»" in FINAL
    assert "Il nome di un punteggio (Metascore, Rotten Tomatoes, voto IMDb) si può usare solo come nome di quel punteggio" in FINAL
    assert "mai come provenienza" in FINAL


def test_the_offers_and_the_notes_name_no_platform() -> None:
    assert "proponi di cercarli come video online, senza nominare la piattaforma" in FINAL
    assert "questi dati non distinguono film e serie TV" in FINAL
    assert "indica il titolo con cui il film risulta registrato" in FINAL and "i voti sono del pubblico, mai della critica" in FINAL


def test_the_omdb_rule_keeps_audience_and_critics_distinct_the_display_format_and_no_winner_between_scales() -> None:
    text = TOOL_RULES["omdb_search"]

    assert "senza nominare mai la provenienza dei dati" in text
    assert "voto del pubblico o punteggio della critica" in text
    assert "campo display" in text and "9.3/10, 82/100, 93%" in text
    assert "non va mai scritto «93/100»" in text
    assert "elenca separatamente per ogni fonte il nome, il punteggio e la scala" in text
    assert "non dichiarare quale sia più alto, migliore, favorito o vincente" in text
    assert "non presentare mai i voti del pubblico come giudizio della critica" in text


def test_the_user_settings_fragments_name_no_provider_either() -> None:
    texts = [behavior.ANSWER_INTRO, *behavior.SOURCES_ANSWER.values(), behavior.SOURCES_COMMON, *behavior.APPROACH.values()]

    for text in texts:
        assert not re.search(r"TMDb|OMDb|MovieLens|Wikipedia|YouTube|\bRAG\b", text), text


def test_the_omdb_result_that_reaches_the_prompt_does_not_carry_the_provider_name() -> None:
    tool, _ = make_tool(by_endpoint(by_id={"tt1000001": record()}))
    ok = tool.run(query="q", params={"imdb_id": "tt1000001"})
    failed = tool.run(query="q", params={"imdb_id": "not-an-id"})
    sent_to_the_model = json.dumps([ok["metadata"], failed["metadata"]])

    assert "OMDb" not in sent_to_the_model and "omdbapi" not in sent_to_the_model
    rows = {row["source"]: row for row in ok["metadata"]["omdb"]["ratings"]}
    # Audience and critics stay distinct, each with its own scale and written form.
    assert [(rows[s]["kind"], rows[s]["display"]) for s in ("imdb", "metascore", "rotten_tomatoes")] == [
        ("audience", "7.9/10"), ("critics", "81/100"), ("critics", "94%"),
    ]
