from __future__ import annotations

import argparse
import hashlib
import math
import os
from pathlib import Path

from dotenv import load_dotenv

from tool.rag.EmbeddingProcess.clean import clean, pipeline_for
from tool.rag.EmbeddingProcess.loaders import load
from tool.rag.EmbeddingProcess.movie_metadata import iter_plot_rows
from tool.rag.EmbeddingProcess.chunk import chunk_semantic
from tool.rag.FromQueryEmbeddingToRes.embeddings import embed


SUPPORTED_LOADER_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".md", ".markdown", ".txt"}


def _stable_id(relative_path: str, doc_index: int, chunk_index: int) -> str:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:12]
    return f"{digest}-{doc_index:06d}-{chunk_index:06d}"


def _read_text_fallback(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _stringify_metadata(metadata: dict) -> dict:
    flattened: dict[str, str] = {}
    for key, value in metadata.items():
        if value is None:
            flattened[key] = ""
        elif isinstance(value, str):
            flattened[key] = value.strip()
        elif isinstance(value, (int, float, bool)):
            flattened[key] = str(value)
        elif isinstance(value, (list, tuple, set)):
            flattened[key] = "; ".join(str(item).strip() for item in value if str(item).strip())
        elif isinstance(value, dict):
            flattened[key] = "; ".join(f"{k}: {v}" for k, v in value.items() if str(v).strip())
        else:
            flattened[key] = str(value).strip()
    return {key: value for key, value in flattened.items() if value is not None and value != ""}


def _iter_texts(dataset_dir: Path):
    for path in sorted(p for p in dataset_dir.rglob("*") if p.is_file()):
        if path.name == ".DS_Store":
            continue

        if path.suffix.lower() == ".tsv":
            continue

        rel = path.relative_to(dataset_dir).as_posix()
        if rel == "MovieSummaries/plot_summaries.txt":
            for row in iter_plot_rows(dataset_dir):
                yield (
                    row["rel"],
                    row["doc_index"],
                    row["movie_id"],
                    row["text"],
                    row["movie_info"],
                    row["cast_names"],
                )
            continue
        if path.suffix.lower() in SUPPORTED_LOADER_EXTENSIONS:
            docs = load(str(path))
            for i, doc in enumerate(docs):
                yield rel, i, None, doc.text, {}, []
        else:
            yield rel, 0, None, _read_text_fallback(path), {}, []


def collect_chunks(
    dataset_dir: Path, semantic_threshold: float, embedding_backend: str, embedding_model: str
) -> tuple[list[str], list[str], list[dict]]:
    """Ids, texts and string metadata of every chunk of the dataset (independent of where they are stored)."""
    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict] = []

    print(f"Scanning documents under: {dataset_dir}")
    for rel, doc_index, movie_id, raw_text, movie_info, cast_names in _iter_texts(dataset_dir):
        if rel == "MovieSummaries/plot_summaries.txt":
            cleaned = raw_text.strip()
            movie_info = movie_info or {}
        else:
            cleaned = clean(raw_text, pipeline_for(rel))
        if not cleaned.strip():
            continue

        if rel == "MovieSummaries/plot_summaries.txt":
            chunks = [cleaned]
        else:
            chunks = chunk_semantic(
                cleaned,
                semantic_threshold,
                backend=embedding_backend,
                model=embedding_model,
            )
        chunks = [c.strip() for c in chunks if c and c.strip()]
        if not chunks:
            continue

        if rel == "MovieSummaries/plot_summaries.txt":
            if doc_index % 1000 == 0:
                print(f"  {rel}: processed row {doc_index}")
        else:
            print(f"  {rel}: {len(chunks)} chunk")
        for i, chunk_text in enumerate(chunks):
            ids.append(_stable_id(rel, doc_index, i))
            texts.append(chunk_text)
            metadata = {
                "source": rel,
                "doc_index": str(doc_index),
                "chunk_index": str(i),
            }
            if movie_id:
                metadata["movie_id"] = movie_id
            if movie_info:
                metadata["title"] = movie_info.get("title", "")
                metadata["release_date"] = movie_info.get("release_date", "")
                metadata["release_year"] = movie_info.get("release_year", "")
                metadata["genres"] = movie_info.get("genres", "")
                metadata["languages"] = movie_info.get("languages", "")
                metadata["countries"] = movie_info.get("countries", "")
            if cast_names:
                metadata["cast"] = "; ".join(cast_names)
            metadatas.append(_stringify_metadata(metadata))
    return ids, texts, metadatas


class QdrantTarget:
    """Builds a NEW Qdrant collection and never replaces or deletes anything.

    The point ids are the same `uuid5` of the stable chunk id as in the migrated index, so a rebuilt
    index and a migrated one are comparable point by point. The vector dimension is taken from the
    first batch and every later batch must match it.
    """

    def __init__(self, collection_name: str, qdrant: dict, embedding_model: str) -> None:
        self.collection_name, self.qdrant, self.model = collection_name, dict(qdrant), embedding_model
        self.store = None

    def prepare(self) -> None:
        mode, path = self.qdrant.get("mode", "server"), self.qdrant.get("path")
        if mode == "memory":
            raise ValueError("an in-memory Qdrant is lost at exit: use mode 'embedded' or 'server'")
        if mode == "embedded":
            if not path:
                raise ValueError("mode 'embedded' needs a storage path (--qdrant-path)")
            if Path(path).exists() and any(Path(path).iterdir()):
                raise FileExistsError(f"{path} is not empty: Qdrant builds never overwrite a storage; use a new folder")
        elif mode == "server" and not self.qdrant.get("url"):
            raise ValueError("mode 'server' needs a URL (--qdrant-url)")

        # Fail BEFORE any chunking or embedding (paid) if the target collection is already there.
        from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta
        from tool.rag.FromQueryEmbeddingToRes.store.collection import new_store
        from tool.rag.FromQueryEmbeddingToRes.store.settings import DEFAULT_DIMENSION

        store = new_store(self.collection_name, self.qdrant, IndexMeta(model=self.model, dimension=DEFAULT_DIMENSION))
        try:
            if store.exists():
                raise FileExistsError(
                    f"Qdrant collection {self.collection_name!r} already exists: choose another --collection "
                    "or storage; this build never replaces an index")
        except BaseException:
            store.close()
            raise
        self.store = store
        self.created = False

    def _create(self, dimension: int) -> None:
        from tool.rag.FromQueryEmbeddingToRes.store.base import IndexMeta

        self.store.meta = IndexMeta(model=self.model, dimension=dimension)
        self.store.create()
        self.created = True

    def write(self, ids, texts, vectors, metadatas) -> None:
        import math

        from tool.rag.FromQueryEmbeddingToRes.store.base import StorePoint

        rows = [list(map(float, v)) for v in vectors]
        dimension = len(rows[0])
        if not self.created:
            self._create(dimension)
        for row, chunk_id in zip(rows, ids):
            if len(row) != self.store.meta.dimension:
                raise ValueError(f"embedding of {chunk_id!r} has {len(row)} dimensions, the index has {self.store.meta.dimension}")
            if not all(math.isfinite(x) for x in row) or not any(row):
                raise ValueError(f"embedding of {chunk_id!r} is empty, zero or not finite")
        self.store.upsert([StorePoint(id=i, vector=v, document=t, metadata=m)
                           for i, v, t, m in zip(ids, rows, texts, metadatas)])

    def count(self) -> int:
        return self.store.count() if self.created else 0

    def where(self) -> str:
        return str(self.qdrant.get("url") or self.qdrant.get("path"))

    def close(self) -> None:
        if self.store is not None:
            self.store.close()


def _validate_qdrant_metadata(batch_meta: list[dict], batch_start_index: int) -> None:
    """Qdrant payload values here are strings (like the migrated index); anything else is a bug upstream."""
    for offset, metadata in enumerate(batch_meta):
        bad = [k for k, v in metadata.items() if not isinstance(v, str)]
        if bad:
            raise ValueError(f"Invalid Qdrant metadata at chunk {batch_start_index + offset}: non-string keys {bad}")


def build_semantic_db(
    dataset_dir: Path,
    collection_name: str,
    semantic_threshold: float,
    embedding_backend: str,
    embedding_model: str,
    batch_size: int,
    qdrant: dict,
) -> int:
    """Chunk, embed and index the dataset into a NEW Qdrant collection described by `qdrant` (mode, url or path).

    Nothing is ever replaced: an existing collection or a non-empty storage folder is refused before any embedding."""
    if not dataset_dir.exists():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")
    if embedding_backend != "openai":
        raise ValueError("the index is built with the openai embedding (the local backend is no longer supported)")
    target = QdrantTarget(collection_name, qdrant or {}, embedding_model)
    validate = _validate_qdrant_metadata

    target.prepare()  # checks first: nothing is touched, nothing is embedded yet
    ids, texts, metadatas = collect_chunks(dataset_dir, semantic_threshold, embedding_backend, embedding_model)
    if not texts:
        raise RuntimeError("No chunks were produced from dataset/. Nothing to index.")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate chunk ids: the index would silently lose chunks")

    try:
        for start in range(0, len(texts), batch_size):
            end = min(start + batch_size, len(texts))
            batch_meta = metadatas[start:end]
            validate(batch_meta, start)
            vectors = embed(texts[start:end], backend=embedding_backend, model=embedding_model)
            if len(vectors) != end - start:
                raise ValueError(f"the embedding returned {len(vectors)} vectors for {end - start} chunks")
            target.write(ids[start:end], texts[start:end], vectors, batch_meta)
            print(f"Indexed chunks {start + 1}-{end} / {len(texts)}")
        count = target.count()
        if count != len(texts):
            raise RuntimeError(f"index has {count} chunks, expected {len(texts)}")
        print(f"Completed. Collection '{collection_name}' has {count} chunks.")
        print(f"Persistent DB path: {target.where()}")
        return count
    finally:
        target.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the semantic Qdrant index from dataset/ (a NEW collection)")
    parser.add_argument("--dataset-dir", default="dataset", help="Dataset directory")
    parser.add_argument("--collection", default="netflix_scout", help="Collection name")
    parser.add_argument("--semantic-threshold", type=float, default=0.78, help="Semantic chunk split threshold")
    parser.add_argument("--embedding-backend", choices=["openai"], default="openai")
    parser.add_argument("--embedding-model", default="text-embedding-3-small", help="Embedding model to use with the selected backend")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--qdrant-mode", choices=["embedded", "server"], default=os.getenv("VECTORSTORE_QDRANT_MODE") or "server")
    parser.add_argument("--qdrant-url", default=os.getenv("VECTORSTORE_QDRANT_URL") or "http://127.0.0.1:6333")
    parser.add_argument("--qdrant-path", default=os.getenv("VECTORSTORE_QDRANT_PATH"), help="Storage folder (mode embedded; must be new or empty)")
    return parser.parse_args()


def qdrant_settings(args: argparse.Namespace) -> dict:
    return {"mode": args.qdrant_mode, "url": args.qdrant_url if args.qdrant_mode == "server" else None,
            "path": args.qdrant_path if args.qdrant_mode == "embedded" else None}


if __name__ == "__main__":
    load_dotenv()
    args = parse_args()
    build_semantic_db(
        dataset_dir=Path(args.dataset_dir),
        collection_name=args.collection,
        semantic_threshold=args.semantic_threshold,
        embedding_backend=args.embedding_backend,
        embedding_model=args.embedding_model,
        batch_size=args.batch_size,
        qdrant=qdrant_settings(args),
    )