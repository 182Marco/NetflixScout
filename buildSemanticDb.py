from __future__ import annotations

import argparse
import hashlib
import math
import shutil
from pathlib import Path

from dotenv import load_dotenv

from aikit import chunk_semantic, clean, crea_collection, db_dir_for_backend, embed, indicizza, load, pipeline_for
from movie_metadata import iter_plot_rows


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


def _has_numpy_like_type(value: object) -> bool:
    return type(value).__module__.startswith("numpy") or hasattr(value, "dtype") and type(value).__module__.startswith("numpy")


def _validate_chroma_metadata_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (str, int, bool)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if _has_numpy_like_type(value):
        return False
    if isinstance(value, (list, tuple, set, dict)):
        return False
    if hasattr(value, "__dict__") and type(value).__module__ not in {"builtins", "__main__"}:
        return False
    return False


def _validate_batch_metadata(batch_meta: list[dict], batch_start_index: int) -> None:
    for local_index, metadata in enumerate(batch_meta):
        global_chunk_index = batch_start_index + local_index
        if not isinstance(metadata, dict):
            print("INVALID_CHROMA_METADATA: metadata entry is not a dict")
            print(f"  global_chunk_index={global_chunk_index}")
            print(f"  type(metadata)={type(metadata).__name__}")
            print(f"  repr(metadata)={metadata!r}")
            raise ValueError("metadata entry is not a dict")

        for key, value in metadata.items():
            if not _validate_chroma_metadata_value(value):
                movie_id = metadata.get("movie_id", "")
                title = metadata.get("title", "")
                print("INVALID_CHROMA_METADATA")
                print(f"  global_chunk_index={global_chunk_index}")
                print(f"  movie_id={movie_id!r}")
                print(f"  title={title!r}")
                print(f"  metadata_key={key!r}")
                print(f"  type(value)={type(value).__name__}")
                print(f"  repr(value)={value!r}")
                raise ValueError(f"Invalid Chroma metadata value at key {key!r}")



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


def build_semantic_db(
    dataset_dir: Path,
    db_dir: Path | None,
    collection_name: str,
    semantic_threshold: float,
    embedding_backend: str,
    embedding_model: str,
    batch_size: int,
) -> int:
    if not dataset_dir.exists():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    if db_dir is None:
        db_dir = db_dir_for_backend(embedding_backend)

    if db_dir.exists():
        shutil.rmtree(db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)

    collection = crea_collection(collection_name, db_dir=db_dir)

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

    if not texts:
        raise RuntimeError("No chunks were produced from dataset/. Nothing to index.")

    for start in range(0, len(texts), batch_size):
        end = min(start + batch_size, len(texts))
        batch_ids = ids[start:end]
        batch_texts = texts[start:end]
        batch_meta = metadatas[start:end]
        _validate_batch_metadata(batch_meta, start)
        vectors = embed(batch_texts, backend=embedding_backend, model=embedding_model)
        indicizza(collection, batch_ids, batch_texts, vectors, batch_meta)
        print(f"Indexed chunks {start + 1}-{end} / {len(texts)}")

    count = collection.count()
    print(f"Completed. Collection '{collection_name}' has {count} chunks.")
    print(f"Persistent DB path: {db_dir}")
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build semantic Chroma DB from dataset/")
    parser.add_argument("--dataset-dir", default="dataset", help="Dataset directory")
    parser.add_argument("--db-dir", default=None, help="Override persistent Chroma directory")
    parser.add_argument("--collection", default="netflix_scout", help="Collection name")
    parser.add_argument("--semantic-threshold", type=float, default=0.78, help="Semantic chunk split threshold")
    parser.add_argument("--embedding-backend", choices=["openai", "local"], default="openai")
    parser.add_argument("--embedding-model", default="text-embedding-3-small", help="Embedding model to use with the selected backend")
    parser.add_argument("--batch-size", type=int, default=128)
    return parser.parse_args()


if __name__ == "__main__":
    load_dotenv()
    args = parse_args()
    build_semantic_db(
        dataset_dir=Path(args.dataset_dir),
        db_dir=Path(args.db_dir) if args.db_dir else None,
        collection_name=args.collection,
        semantic_threshold=args.semantic_threshold,
        embedding_backend=args.embedding_backend,
        embedding_model=args.embedding_model,
        batch_size=args.batch_size,
    )