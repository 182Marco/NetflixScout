"""RAGWikipediaSeries: data preparation for a hierarchical RAG of TV series, seasons and episodes.

Independent from the film RAG (`tool/RAGWikipediaFilm`): it never writes there and never touches the
film collections. Generic read-only components (dump reader, plot cleaning, Wikidata client) are
re-exported by `common.py`. Not wired into the agent.
"""
