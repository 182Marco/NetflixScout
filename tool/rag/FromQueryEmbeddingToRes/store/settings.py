"""Pinned Qdrant versions: the client and the server are fixed and checked together."""
from __future__ import annotations

QDRANT_CLIENT_VERSION = "1.20.0"  # must equal the pin in requirements.txt
QDRANT_SERVER_VERSION = "1.20.0"  # tag of the server image/binary the project is tested against


def _minor(version: str) -> tuple[int, int]:
    major, minor, *_ = (int(part) for part in version.split("."))
    return major, minor


def versions_compatible(client: str, server: str) -> bool:
    """Same major.minor, the matrix the project declares (qdrant-client warns beyond it)."""
    return _minor(client) == _minor(server)

DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_DIMENSION = 1536
