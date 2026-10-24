"""Shared fixtures of the web_lists tests: steps as the tools emit them and a fake LLM callback."""
from __future__ import annotations

import json
from typing import Any

from turn import TraceStep, TurnResult

TMDB_STEP = TraceStep(
    kind="tmdb_calls",
    title="TMDb",
    data={
        "calls": ["https://api.themoviedb.org/3/movie/157336?api_key=***"],
        "attributions": ["justwatch"],
        "items": [
            {"id": 157336, "media_type": "movie", "title": "Interstellar", "overview": "Space.",
             "vote_average": 8.4, "release_date": "2014-11-05", "original_language": "en",
             "poster_path": "/gEU2.jpg"},
            {"id": 1396, "media_type": "tv", "title": "Breaking Bad", "overview": "Chemistry.",
             "vote_average": 8.9, "release_date": "2008-01-20", "original_language": "en",
             "poster_path": "/ggFH.jpg"},
        ],
    },
)
YOUTUBE_STEP = TraceStep(
    kind="youtube_calls",
    title="YouTube",
    data={
        "calls": [],
        "videos": [
            {"kind": "director_interview", "title": "Nolan\x07 on Interstellar", "channel": "Canale",
             "url": "https://www.youtube.com/watch?v=t3NQUGtQeAo", "published_at": "2014-11-10T00:00:00Z",
             "description_excerpt": "Intervista.", "notes": [], "verification": "confirmed"},
        ],
    },
)


ANSWER = (
    "Ecco cosa ho trovato.\n\n"
    "- **Interstellar** (2014): un viaggio nello spazio.\n"
    "- Breaking Bad: la serie sulla chimica.\n"
    "- Nolan on Interstellar: intervista su YouTube.\n"
)

MOVIE_REF = {"source": "tmdb", "media_type": "movie", "id": 157336,
             "quote": "**Interstellar** (2014): un viaggio nello spazio.", "reason": "Spazio."}
TV_REF = {"source": "tmdb", "media_type": "tv", "id": 1396,
          "quote": "Breaking Bad: la serie sulla chimica.", "reason": "Serie."}
VIDEO_REF = {"source": "youtube", "video_id": "t3NQUGtQeAo",
             "quote": "Nolan on Interstellar: intervista su YouTube.", "reason": "Intervista."}


def make_turn(
    refs: list | None = None,
    *,
    steps: list[TraceStep] | None = None,
    answer: str = ANSWER,
    blocked: bool = False,
) -> TurnResult:
    """A finished web turn. `refs` are the raw lists of the final call (a list of lists)."""
    return TurnResult(
        query="q", language="it", blocked=blocked, answer=answer,
        steps=[TMDB_STEP, YOUTUBE_STEP] if steps is None else steps,
        item_refs=refs if refs is not None else [raw_list(MOVIE_REF, TV_REF, VIDEO_REF)],
    )


def raw_list(*items: dict[str, Any], list_id: str = "Film di Nolan", kind: str = "mixed") -> dict[str, Any]:
    return {"list_id": list_id, "title": "Film di Nolan", "kind": kind, "items": list(items)}


class FakeResponses:
    """`client.responses` of the orchestrator: records every call and answers with `outputs`."""

    def __init__(self, *outputs: str | Exception) -> None:
        self.outputs = list(outputs)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        out = self.outputs[min(len(self.calls), len(self.outputs)) - 1]
        if isinstance(out, Exception):
            raise out
        return type("Response", (), {"output_text": out})()


class FakeClient:
    def __init__(self, *outputs: str | Exception) -> None:
        self.responses = FakeResponses(*outputs)


def structured(answer: str, *lists: dict[str, Any]) -> str:
    return json.dumps({"answer": answer, "lists": list(lists)})
