"""MovieLens 32M as a local read-only SQLite database.

- `config.py`: validated view of `CONFIG["movie_db"]` (the values live only in `app.py`).
- `schema.py`: tables, columns and DDL shared by ingestion and runtime.
- `tool/`: runtime code (orchestrator tool, parser, read-only SQL access).
- `harness/`: offline code, never imported at runtime (ingestion, fixtures, evaluation).
- `data/`: unzipped MovieLens CSV and the generated DB (git-ignored, not code).
"""
