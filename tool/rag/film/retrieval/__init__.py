"""The film index retriever: ONE dense search over the Wikipedia film collection (`wikipedia_films_it_v3`).

Positive filters (year, country, director, actor, rare plot words) run inside Qdrant; cited films, franchises and genres to avoid
are removed, the traits to avoid are penalised on the candidate pool, and an LLM reorders the top. No second ranking, no RRF, no
fallback to another index. Read-only: nothing here writes to Qdrant. Measured in pipelines/wikipedia_films/EVAL_REPORT.md."""
