"""The legacy conversation loop opens the same vector engine as the app (it used to open Chroma only)."""
from __future__ import annotations

import pytest

import app as app_module
from tool.rag.FromQueryEmbeddingToRes import chat


def test_legacy_loop_passes_the_engine_configuration(monkeypatch):
    seen = {}

    class Empty:
        def count(self):
            return 0

    monkeypatch.setattr(chat, "apri_collection", lambda name, **kw: seen.update(kw) or Empty())
    config = app_module.build_runtime_config({"rag": {"vectorstore": {"engine": "qdrant"}}})["rag"]
    with pytest.raises(RuntimeError, match="empty"):
        chat.run_conversation_loop(config=config, exit_commands={"exit"}, compact_notice="")
    assert seen["store_config"]["engine"] == "qdrant"
