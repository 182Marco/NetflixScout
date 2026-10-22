"""Terminal output of the TMDb tool."""

from .blocks import print_tmdb_notice
from .renderer import render_tmdb_calls

__all__ = ["print_tmdb_notice", "render_tmdb_calls"]
