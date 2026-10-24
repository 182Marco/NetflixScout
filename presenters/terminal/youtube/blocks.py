"""Terminal print blocks for YouTube (same box style as `terminal/box.py`).

The content comes from the shared `presenters/youtube_view.py`; this module only decides the
terminal format. Every text in the view went through `printable`, so a video title cannot
drive the terminal; the trace, the metadata and the LLM prompt keep the API values unchanged.
"""
from __future__ import annotations

from ...youtube_view import YOUTUBE_NOTICE, VideoView, YoutubeCallsView, printable
from ..box import print_box

__all__ = ["YOUTUBE_NOTICE", "printable", "print_youtube_calls", "print_youtube_notice"]


def print_youtube_calls(view: YoutubeCallsView) -> None:
    text = view.labels
    print_box("▶️", view.title)
    print(f"  {view.source}")

    print()
    if not view.calls:
        print(f"  {text['no_calls']}")
    for url in view.calls:
        print(f"  {text['called']}: {url}")

    for search in view.searches:
        print(f"\n  🔎 {text['search']} {search.kind_label}: {search.q}")
        print(f"     {search.summary}")
        if search.error:
            print(f"     ⚠️  {text['error']}: {search.error}")

    if view.not_searched:
        print(f"\n  ⏭️  {text['not_searched']}: {view.not_searched}")
    if view.quota_paused:
        print(f"\n  ⛔ {view.quota_paused}")

    print()
    if not view.groups:
        print(f"  {text['no_videos']}")
    for group in view.groups:
        for video in group.confirmed:
            _print_video(video, text)
        if group.to_verify:
            print(f"  ❔ [{group.kind_label}] {text['to_verify']}")
        for video in group.to_verify:
            _print_video(video, text)

    for hint in view.hints:
        print(f"\n  💡 {hint}")


def _print_video(video: VideoView, text: dict[str, str]) -> None:
    print(
        f"  ▶ [{video.kind_label}] {video.title} — {video.channel}" + (f" ({video.published})" if video.published else "")
    )
    print(f"     {video.url}")
    if video.notes:
        print(f"     {text['notes']}: {', '.join(video.notes)}")


def print_youtube_notice() -> None:
    """Startup notice: YouTube Terms of Service and Google Privacy Policy links."""
    print(f"ℹ️  {YOUTUBE_NOTICE}\n")
