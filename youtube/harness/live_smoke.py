"""Optional live check of how YouTube reads the `q` operators (7 `search.list` calls).

    python -m youtube.harness.live_smoke --live

`search.list` has its own quota bucket of 100 calls a day per Google project (1 unit each):
this run uses 7. It answers the question left open in `youtube/queries.py` ("assumed
precedence, to confirm with the live smoke test") by sending, for a film with almost no
interviews (Critters 3) and for a control with many (Oppenheimer), the query the tool builds
and simpler variants of it, and printing only how many raw results each one returned and
the first titles (third-party text: control characters removed).

How to read it:
- control current-form query = 0            -> the operators are not read as assumed (fix `queries.py`);
- control > 0 but Critters current-form = 0 -> the tool query is too strict for obscure films;
  if the relaxed variants return videos, a broader second search is worth adding;
- every Critters variant = 0 or unrelated    -> YouTube has (almost) nothing on that film.
Not a pytest test; it needs `YOUTUBE_API_KEY` in `.env`. Only masked URLs are printed.
"""
from __future__ import annotations

import argparse

from ..auth import load_credentials
from ..http import HttpSession, get_json, urllib_transport
from ..models import VideoKind, YoutubeToolInput
from ..quota import QuotaLatch
from ..queries import build_search_params

MAX_TITLES_SHOWN = 5


def _clean(text: object) -> str:
    return "".join(char if char.isprintable() else " " for char in str(text))[:90]


def _variants() -> list[tuple[str, str]]:
    critters = YoutubeToolInput(query="x", title="Critters 3", kinds=["cast_interview"], cast=["Leonardo DiCaprio"])
    control = YoutubeToolInput(query="x", title="Oppenheimer", kinds=["cast_interview"], cast=["Cillian Murphy"])
    current = lambda request: build_search_params(request, VideoKind.cast_interview, max_results=3)["q"]  # noqa: E731
    return [
        ("control, query built by the tool", current(control)),
        ("control, title AND person only", '"Oppenheimer" "Cillian Murphy"'),
        ("Critters 3, query built by the tool", current(critters)),
        ("Critters 3, title AND person only", '"Critters 3" "Leonardo DiCaprio"'),
        ("Critters 3, title AND interview", '"Critters 3" interview'),
        ("Critters 3, title only", '"Critters 3"'),
        ("Critters 3, no quotes", "Critters 3 Leonardo DiCaprio interview"),
    ]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Live YouTube query smoke check (7 search calls).")
    parser.add_argument("--live", action="store_true", required=True, help="Required: this run calls the real API.")
    parser.parse_args(argv)

    session = HttpSession(credentials=load_credentials(), transport=urllib_transport, latch=QuotaLatch())
    for label, q in _variants():
        params = {"part": "snippet", "type": "video", "order": "relevance", "maxResults": "9", "q": q}
        data = get_json(session, "/search", params)
        items = [item for item in data.get("items") or [] if isinstance(item, dict)]
        print(f"\n{label}\n  q: {q}\n  raw results: {len(items)}")
        for item in items[:MAX_TITLES_SHOWN]:
            snippet = item.get("snippet") or {}
            print(f"    - {_clean(snippet.get('title'))}  [{_clean(snippet.get('channelTitle'))}]")
    for call in session.recorder.calls:
        print(f"\ncalled: {call}")


if __name__ == "__main__":
    main()
