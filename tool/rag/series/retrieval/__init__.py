"""Dense retriever over `wikipedia_series_it_v1` (series, seasons, episodes, TV movies), split by concern:

- `constants`  collection, default server, closed vocabularies
- `text`       title normalisation, vector helpers (pure)
- `signals`    what the LLM parser extracts (`SeriesSignals`), its instructions, the plain-request fallback
- `index`      read-only Qdrant access: `Item`, `SeriesIndex` (lookups, navigation, filters)
- `search`     the search itself: filters evaluated by Qdrant, exclusions as a penalty, optional reorder; `run`
- `service`    the only module that talks to OpenAI: embedder, parser call, LLM reorder

Same shape as the film index: ONE dense retriever, every search bound to one level, no RRF, no fusion, no fallback to another index.
The names below are the package's public surface (what the tool, the harnesses and the pipeline's evaluation import)."""
from __future__ import annotations

from .constants import COLLECTION, LEVELS, SUBTYPES, URL
from .index import Item, SeriesIndex, item_from_point
from .search import Embed, Output, Reorder, Settings, run, search
from .service import Order, _openai, make_embed, make_parse, make_reorder
from .signals import INSTRUCTIONS, SeriesSignals, fallback
from .text import base_title_norm, norm, unit

__all__ = ["COLLECTION", "LEVELS", "SUBTYPES", "URL", "INSTRUCTIONS", "Item", "SeriesIndex", "item_from_point", "Embed", "Output", "Reorder", "Settings", "run", "search",
           "Order", "_openai", "make_embed", "make_parse", "make_reorder", "SeriesSignals", "fallback", "base_title_norm", "norm", "unit"]
