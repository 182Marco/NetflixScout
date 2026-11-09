"""Errors shared by the RAG tools."""


class QdrantUnavailable(RuntimeError):
    """The Qdrant server cannot be reached (down, wrong URL) or the collection is missing. The message tells what to do."""
