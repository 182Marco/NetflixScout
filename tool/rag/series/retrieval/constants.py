"""Collection, default server and the closed vocabularies of the series index."""
from __future__ import annotations



COLLECTION = "wikipedia_series_it_v1"
URL = "http://127.0.0.1:6333"   # default only for the helpers; the tool passes the configured one
LEVELS = ("series", "season", "episode", "tv_movie")
SUBTYPES = ("tv_series", "miniseries", "serial", "web_series", "anime", "animated_series", "programme")
