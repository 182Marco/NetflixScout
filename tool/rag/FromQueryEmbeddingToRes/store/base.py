"""Provider-neutral contract of the vector store."""
from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class StorePoint:
    """One indexed chunk: `id` is the stable string id, metadata values are strings."""

    id: str
    vector: Sequence[float]
    document: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class IndexMeta:
    """What an index was built with; a store refuses to open if the config disagrees."""

    model: str
    dimension: int
    distance: str = "cosine"


class VectorStore(Protocol):
    """Results are dicts `{id, testo, score, **metadata}`, the shape `vectorstore.search` returns.

    `score` is the cosine similarity (higher is better).
    """

    def count(self) -> int: ...

    def upsert(self, points: Sequence[StorePoint]) -> None: ...

    def query(
        self, vector: Sequence[float], limit: int, *, exclude_movie_ids: Sequence[str] = (),
        exact: bool = False, ef: int | None = None,
    ) -> list[dict]: ...

    def recommend(
        self,
        positive: Sequence[Sequence[float]],
        negative: Sequence[Sequence[float]],
        limit: int,
        *,
        strategy: str = "average_vector",
        exclude_movie_ids: Sequence[str] = (),
        exact: bool = False,
        ef: int | None = None,
    ) -> list[dict]: ...

    def find_by_title(self, title: str, year: int | None = None, window: int = 1) -> list[dict]: ...

    def vector_of(self, legacy_id: str) -> list[float] | None: ...

    def page(self, limit: int, cursor: object = None) -> tuple[list[dict], object]: ...

    def scroll(self, batch_size: int = 5000) -> Iterator[dict]: ...

    def close(self) -> None: ...
