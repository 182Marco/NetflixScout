"""Public API for the internal AIKit library."""

from aikit.chunk import chunk_fixed, chunk_recursive, chunk_semantic
from aikit.clean import clean, pipeline_for
from aikit.embeddings import cosine_similarity, embed
from aikit.hybrid import cerca_bm25, cerca_hybrid, costruisci_indice_bm25, rrf
from aikit.loaders import Document, load
from aikit.rag import genera, recupera, rispondi
from aikit.rerank import cerca_due_stadi, rerank_cohere, rerank_llm
from aikit.tools import definisci_tool
from aikit.vectorstore import apri_collection, crea_collection, db_dir_for_backend, indicizza, search

__all__ = [
    "Document",
    "apri_collection",
    "cerca_bm25",
    "cerca_due_stadi",
    "cerca_hybrid",
    "chunk_fixed",
    "chunk_recursive",
    "chunk_semantic",
    "clean",
    "cosine_similarity",
    "costruisci_indice_bm25",
    "crea_collection",
    "db_dir_for_backend",
    "definisci_tool",
    "embed",
    "genera",
    "indicizza",
    "load",
    "pipeline_for",
    "recupera",
    "rerank_cohere",
    "rerank_llm",
    "rispondi",
    "rrf",
    "search",
]
