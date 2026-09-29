from __future__ import annotations

import argparse
import hashlib
import shutil
from pathlib import Path

from dotenv import load_dotenv

from aikit.chunk import chunk_semantic
from aikit.clean import clean, pipeline_for
from aikit.embeddings import embed
from aikit.loaders import load
from aikit import vectorstore


SUPPORTED_LOADER_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".md", ".markdown", ".txt"}


def _stable_id(relative_path: str, index: int) -> str:
    digest = hashlib.sha1(relative_path.encode("utf-8")).hexdigest()[:12]
    return f"{digest}-{index:06d}"


def _read_text_fallback(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _iter_texts(dataset_dir: Path):
    for path in sorted(p for p in dataset_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(dataset_dir).as_posix()
        if path.suffix.lower() in SUPPORTED_LOADER_EXTENSIONS:
            docs = load(str(path))
            for i, doc in enumerate(docs):
                yield rel, i, doc.text
        else:
            yield rel, 0, _read_text_fallback(path)


def build_semantic_db(
    dataset_dir: Path,
    db_dir: Path,
    collection_name: str,
    semantic_threshold: float,
    embedding_backend: str,
    batch_size: int,
) -> int:
    if not dataset_dir.exists():
        raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")

    if db_dir.exists():
        shutil.rmtree(db_dir)
    db_dir.mkdir(parents=True, exist_ok=True)

    # Reuse AIKit vectorstore logic while redirecting persistence location.
    vectorstore.CHROMA_DIR = db_dir
    collection = vectorstore.crea_collection(collection_name)

    ids: list[str] = []
    texts: list[str] = []
    metadatas: list[dict] = []

    print(f"Scanning documents under: {dataset_dir}")
    for rel, doc_index, raw_text in _iter_texts(dataset_dir):
        cleaned = clean(raw_text, pipeline_for(rel))
        if not cleaned.strip():
            continue

        chunks = chunk_semantic(cleaned, semantic_threshold)
        chunks = [c.strip() for c in chunks if c and c.strip()]
        if not chunks:
            continue

        print(f"  {rel}: {len(chunks)} chunk")
        for i, chunk_text in enumerate(chunks):
            ids.append(_stable_id(rel, i))
            texts.append(chunk_text)
            metadatas.append({"source": rel, "doc_index": doc_index, "chunk_index": i})

    if not texts:
        raise RuntimeError("No chunks were produced from dataset/. Nothing to index.")

    for start in range(0, len(texts), batch_size):
        end = min(start + batch_size, len(texts))
        batch_ids = ids[start:end]
        batch_texts = texts[start:end]
        batch_meta = metadatas[start:end]
        vectors = embed(batch_texts, backend=embedding_backend)
        vectorstore.indicizza(collection, batch_ids, batch_texts, vectors, batch_meta)
        print(f"Indexed chunks {start + 1}-{end} / {len(texts)}")

    count = collection.count()
    print(f"Completed. Collection '{collection_name}' has {count} chunks.")
    print(f"Persistent DB path: {db_dir}")
    return count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build semantic Chroma DB from dataset/")
    parser.add_argument("--dataset-dir", default="dataset", help="Dataset directory")
    parser.add_argument("--db-dir", default="semanticDb", help="Persistent Chroma directory")
    parser.add_argument("--collection", default="netflix_scout", help="Collection name")
    parser.add_argument("--semantic-threshold", type=float, default=0.78, help="Semantic chunk split threshold")
    parser.add_argument("--embedding-backend", choices=["openai", "local"], default="openai")
    parser.add_argument("--batch-size", type=int, default=128)
    return parser.parse_args()


if __name__ == "__main__":
    load_dotenv()
    args = parse_args()
    build_semantic_db(
        dataset_dir=Path(args.dataset_dir),
        db_dir=Path(args.db_dir),
        collection_name=args.collection,
        semantic_threshold=args.semantic_threshold,
        embedding_backend=args.embedding_backend,
        batch_size=args.batch_size,
    )