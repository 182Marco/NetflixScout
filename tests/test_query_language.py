from rag.FromQueryEmbeddingToRes.chat import _choose_block_language
from rag.FromQueryEmbeddingToRes.query_classifier.query_classifier import classify_query_domain


def test_block_language_uses_classification_flag() -> None:
    assert _choose_block_language("query", {"is_cinema": False, "is_italian": True}) == "it"
    assert _choose_block_language("query", {"is_cinema": False, "is_italian": False}) == "en"


def test_cinema_question_uses_openai_classifier(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            captured["model"] = kwargs["model"]
            captured["messages"] = kwargs["messages"]
            return type(
                "Response",
                (),
                {
                    "choices": [
                        type(
                            "Choice",
                            (),
                            {"message": type("Message", (), {"content": '{"is_cinema": true, "is_italian": true}'})()},
                        )()
                    ]
                },
            )()

    monkeypatch.setattr(
        "rag.FromQueryEmbeddingToRes.query_classifier.query_classifier.OpenAI",
        lambda: type("Client", (), {"chat": type("Chat", (), {"completions": FakeCompletions})()})(),
    )

    result = classify_query_domain(
        "Dimmi il più bel film di sport che hai tra i documenti e poi dimmi quando uscirà il prossimo film di sport su un grande personaggio con budget relativamente alto"
    )

    assert result == {"is_cinema": True, "is_italian": True}
    assert captured["model"] == "gpt-4o-mini"
