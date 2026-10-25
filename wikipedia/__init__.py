"""Wikipedia tool: read-only, in-process access to the MediaWiki Action API for the orchestrator.

The LLM fills a typed input (topic, how deep to read); this package builds the requests from
constant fragments, sends them to fixed hosts, splits the article into sections and returns the
ones the question needs, with a description of what was left out so the orchestrator can decide
whether to read more. The model never builds URLs or sends free HTTP requests.
"""
