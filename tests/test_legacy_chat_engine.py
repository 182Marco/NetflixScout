"""The legacy conversation loop opens the same Qdrant collection as the app, from the same configuration."""
from __future__ import annotations

import pytest

import app as app_module
from tool.rag.FromQueryEmbeddingToRes import chat


def test_legacy_loop_passes_the_qdrant_configuration(monkeypatch):
    seen = {}

    class Empty:
        def count(self):
            return 0

    monkeypatch.setattr(chat, "apri_collection", lambda name, **kw: seen.update(kw) or Empty())
    config = app_module.build_runtime_config({"rag": {"vectorstore": {"qdrant": {"url": "http://h:6333"}}}})["rag"]
    with pytest.raises(RuntimeError, match="empty"):
        chat.run_conversation_loop(config=config, exit_commands={"exit"}, compact_notice="")
    assert seen["store_config"]["qdrant"]["url"] == "http://h:6333"
