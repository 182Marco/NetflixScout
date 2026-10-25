"""TMDb tool: read-only access to The Movie Database API for the orchestrator.

The LLM picks typed operations; this package validates them, resolves missing IDs, maps
each operation to a fixed endpoint, enforces the per-turn HTTP budget and normalizes the
results. The model never builds URLs or sends free HTTP requests.
"""
