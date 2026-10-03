from rag.FromQueryEmbeddingToRes.chat import _choose_block_language
from rag.FromQueryEmbeddingToRes.local_query_classifier.local_query_classifier import (
    _validate_classification,
)


def test_block_language_uses_italian_markers_for_mixed_language_queries() -> None:
    query = "Mi spieghi per favore the relativity theory from albery Einstein?"

    assert _choose_block_language(query, {"is_cinema": False, "is_italian": False}) == "it"


def test_cinema_queries_skip_italian_marker_detection(monkeypatch) -> None:
    called = {"value": False}

    def fake_looks_italian(query: str) -> bool:
        called["value"] = True
        return True

    monkeypatch.setattr(
        "rag.FromQueryEmbeddingToRes.local_query_classifier.local_query_classifier._looks_italian",
        fake_looks_italian,
    )

    result = _validate_classification({"is_cinema": True, "is_italian": False}, "Mi spieghi per favore?")

    assert result == {"is_cinema": True, "is_italian": False}
    assert called["value"] is False
