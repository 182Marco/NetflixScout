"""Requests of the tool as constant paths and parameters. Pure: no I/O.

The user's words appear only as the value of `q`; nothing else of the URL comes from them. The
embed values are the ones TVmaze documents (`cast`, `nextepisode`).
"""
from __future__ import annotations

Request = tuple[str, tuple[tuple[str, str], ...]]


def search_request(title: str) -> Request:
    return "/search/shows", (("q", title),)


def show_request(show_id: int, *, cast: bool, next_episode: bool) -> Request:
    embeds = (["cast"] if cast else []) + (["nextepisode"] if next_episode else [])
    return f"/shows/{int(show_id)}", tuple(("embed[]", name) for name in embeds)


def seasons_request(show_id: int) -> Request:
    return f"/shows/{int(show_id)}/seasons", ()


def episodes_request(show_id: int) -> Request:
    return f"/shows/{int(show_id)}/episodes", (("specials", "1"),)
