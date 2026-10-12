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


def _fake_openai(monkeypatch, captured: dict[str, object]) -> None:
    class FakeCompletions:
        @staticmethod
        def create(**kwargs):
            captured["messages"] = kwargs["messages"]
            message = type("Message", (), {"content": '{"is_cinema": true, "is_italian": true}'})()
            return type("Response", (), {"choices": [type("Choice", (), {"message": message})()]})()

    monkeypatch.setattr(
        "rag.FromQueryEmbeddingToRes.query_classifier.query_classifier.OpenAI",
        lambda: type("Client", (), {"chat": type("Chat", (), {"completions": FakeCompletions})()})(),
    )


def test_classifier_without_history_sends_only_the_query(monkeypatch) -> None:
    captured: dict[str, object] = {}
    _fake_openai(monkeypatch, captured)

    classify_query_domain("Consigliami un film di fantascienza")

    messages = captured["messages"]
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[-1]["content"] == "Consigliami un film di fantascienza"


def test_classifier_with_history_sends_context_before_the_query(monkeypatch) -> None:
    captured: dict[str, object] = {}
    _fake_openai(monkeypatch, captured)
    history = [
        {"role": "user", "content": "Consigliami 3 dei migliori film di fantascienza"},
        {"role": "assistant", "content": "Alien (1979), Blade Runner (1982), Stargate (1994)"},
    ]

    classify_query_domain("Ne puoi trovare 3 più recenti rispetto al 94?", history)

    messages = captured["messages"]
    assert [m["role"] for m in messages] == ["system", "user", "user"]
    assert "Consigliami 3 dei migliori film di fantascienza" in messages[1]["content"]
    assert "Stargate (1994)" in messages[1]["content"]
    assert messages[-1]["content"] == "Ne puoi trovare 3 più recenti rispetto al 94?"
