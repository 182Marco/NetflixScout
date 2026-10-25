"""YouTube tool: read-only, in-process access to the YouTube Data API v3 for the orchestrator.

The LLM fills a typed input (film title, video kinds); this package builds the search
queries from constant fragments, sends them to fixed endpoints, filters the results and
returns them unchanged. The model never builds URLs or sends free HTTP requests.
"""
