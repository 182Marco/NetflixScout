"""Phase 3: embeddings of the Italian-Wikipedia synopses and the dedicated Qdrant collection.

Isolated from the Phase 1 pipeline (it only READS `data/processed/films.jsonl`) and from the existing RAG: it never
touches the `netflix_scout` collection (see `settings.assert_own_collection`)."""
