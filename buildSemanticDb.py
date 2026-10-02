from rag.EmbeddingProcess.buildSemanticDb import *


if __name__ == "__main__":
    from rag.EmbeddingProcess.buildSemanticDb import build_semantic_db, parse_args
    from pathlib import Path
    from dotenv import load_dotenv

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
