"""Offline tests of the YouTube part of the final-answer prompt (`final_instructions`) and of
what the final answer receives. No LLM call: the answer itself is checked live only."""
from __future__ import annotations

import json

from youtube_support import make_tool, run_tool, search_item, video_item

import app as app_module
from orchestrator import LLMOrchestrator


def _youtube_paragraph() -> str:
    final = app_module.CONFIG["orchestrator"]["final_instructions"]
    start = final.index("Se il tool usato è youtube_search")
    return final[start:]


def test_the_youtube_rules_apply_only_to_youtube_turns() -> None:
    assert _youtube_paragraph().startswith("Se il tool usato è youtube_search, ")


def test_categories_are_named_director_and_cast_interviews() -> None:
    text = _youtube_paragraph()

    assert "interviste al regista (director_interview)" in text
    assert "interviste al cast (cast_interview)" in text
    assert "making-of, dietro le quinte, commenti degli autori" in text


def test_confirmed_before_to_verify_in_the_order_received_never_mixed() -> None:
    text = _youtube_paragraph()

    assert "prima i video con verification 'confirmed' e poi, sotto 'Da verificare'" in text
    assert "ciascun gruppo nello stesso ordine ricevuto" in text
    assert "non presentare mai un video da verificare come confermato" in text
    assert "cosa non è confermato (la categoria o il film)" in text


def test_titles_and_channels_verbatim_no_official_claim_no_invented_content() -> None:
    text = _youtube_paragraph()

    assert "titolo e canale esattamente come ricevuti" in text
    assert "Non affermare che un video è ufficiale" in text
    assert "non compaiono nel titolo o nell'estratto della descrizione" in text


def test_turn_limit_wording_hints_and_conciseness() -> None:
    text = _youtube_paragraph()

    assert "per il limite di ricerche per turno" in text and "limite di turni" not in text
    assert "'specify_year', suggerisci di indicare l'anno del film" in text
    assert "'original_title'" in text and "senza proporne uno" in text
    assert "Non mescolare link TMDb e YouTube" in text and "Rispondi in modo conciso" in text


def test_the_previous_final_rules_are_unchanged() -> None:
    final = app_module.CONFIG["orchestrator"]["final_instructions"]

    assert final.index("Se il tool usato è youtube_search") > final.index("inventare grafie.")
    assert "tmdb_enrichment" in final and "Non mostrare all'utente nomi tecnici di campi" in final


def test_youtube_is_still_not_registered() -> None:
    """Step 9 (registration and routing) is not part of this fix."""
    assert "youtube_search" not in app_module.CONFIG["orchestrator"]["allowed_tools"]
    assert "youtube_search" not in app_module.CONFIG["orchestrator"]["instructions"]


class _NoClient:
    responses = None


def test_the_final_answer_receives_labels_and_hints_in_metadata() -> None:
    routes = {
        "/search": {"items": [search_item("vid00000001", "Arrival - Behind the scenes"), search_item("vid00000002", "Arrival - Featurette")]},
        "/videos": {"items": [video_item("vid00000001", "Arrival - Behind the scenes"), video_item("vid00000002", "Arrival - Featurette")]},
    }
    tool, _ = make_tool(routes)
    result = run_tool(tool, title="Arrival", kinds=["behind_the_scenes"])
    orchestrator = LLMOrchestrator(config=app_module.build_runtime_config(), tools=[tool], client=_NoClient())

    messages = orchestrator._build_final_context(query="q", tool_result={"tool_name": "youtube_search", **result})

    payload = messages[-1]["content"]
    assert "Tool usato: youtube_search" in payload
    metadata = json.loads(payload.split("Metadata: ", 1)[1].split("\n", 1)[0])
    hits = metadata["youtube"]["kinds"][0]["hits"]
    assert [hit["verification"] for hit in hits] == ["to_verify", "to_verify"]
    assert metadata["youtube"]["hints"] == ["specify_year", "original_title"]
