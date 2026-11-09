"""Streaming reader of the pages-articles XML dump (copied from pipelines/wikipedia_films/extract_films.py:
Page, iter_pages, open_dump; this package must not import the film project).

The dump is read through `bz2` as a stream and parsed with `iterparse`: the decompressed XML is
never written to disk and memory stays bounded (every page element is cleared after use).
"""
from __future__ import annotations

import bz2
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterator


log = logging.getLogger("series.dump")


@dataclass(frozen=True)
class Page:
    page_id: int
    title: str
    namespace: int
    redirect: bool
    revision_id: str
    timestamp: str
    text: str


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def iter_pages(stream: IO[bytes], *, allow_truncated: bool = False) -> Iterator[Page]:
    """Yield pages from an XML stream. A truncated stream (partial sample) ends quietly only if
    `allow_truncated`; otherwise the error is raised."""
    root = None
    try:
        for event, elem in ET.iterparse(stream, events=("start", "end")):
            if event == "start":
                if root is None:
                    root = elem
                continue
            if _local(elem.tag) != "page":
                continue
            fields: dict[str, str] = {}
            revision: dict[str, str] = {}
            redirect = False
            for child in elem:
                name = _local(child.tag)
                if name == "redirect":
                    redirect = True
                elif name == "revision":
                    for sub in child:
                        revision[_local(sub.tag)] = sub.text or ""
                else:
                    fields[name] = child.text or ""
            elem.clear()
            if root is not None:
                root.clear()
            try:
                yield Page(
                    page_id=int(fields["id"]),
                    title=fields.get("title", ""),
                    namespace=int(fields.get("ns", "0")),
                    redirect=redirect,
                    revision_id=revision.get("id", ""),
                    timestamp=revision.get("timestamp", ""),
                    text=revision.get("text", ""),
                )
            except (KeyError, ValueError):
                log.warning("malformed page element skipped")
    except (EOFError, ET.ParseError) as error:
        if not allow_truncated:
            raise
        log.warning("stream ended early (%s): expected for a partial sample", error)


def open_dump(path: Path) -> IO[bytes]:
    return bz2.BZ2File(path, "rb")
