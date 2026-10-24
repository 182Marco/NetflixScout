"""Accepted references + what the tools returned -> the `lists` of the web payload.

A reference not found in the index is dropped, a repeated one is kept once per list, a list left
without items is dropped. No tool is called: the data are the ones of the steps.
"""
from __future__ import annotations

from typing import Any

from ..schema.llm.list_ref import ItemRef, ListRef
from ..schema.payload.item import Item
from ..schema.payload.web_list import WebList
from .item_key import ref_key
from .tmdb_item import tmdb_item
from .youtube_item import youtube_item


def _hydrate_item(ref: ItemRef, index: dict[str, dict[str, Any]]) -> Item | None:
    record = index.get(ref_key(ref))
    if record is None:
        return None
    return youtube_item(record, ref.reason) if ref.source == "youtube" else tmdb_item(record, ref.reason)


def _hydrate_list(ref: ListRef, index: dict[str, dict[str, Any]]) -> WebList | None:
    items = {item.key: item for item in (_hydrate_item(r, index) for r in ref.items) if item}
    if not items:
        return None
    return WebList(list_id=ref.list_id, title=ref.title, kind=ref.kind, items=list(items.values()))


def hydrate_lists(refs: list[ListRef], index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    lists = (_hydrate_list(ref, index) for ref in refs)
    return [web_list.model_dump(mode="json", exclude_unset=True) for web_list in lists if web_list]
