"""Streaming extraction of single-film articles (with plot) from the pages-articles XML dump.

The dump is read through `bz2` as a stream and parsed with `iterparse`: the decompressed XML is
never written to disk and memory stays bounded (every page element is cleared after use).
"""
from __future__ import annotations

import bz2
import json
import logging
import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterator

import mwparserfromhell

from .clean_plot import extract_plot
from .config import ExtractConfig, PipelineConfig

log = logging.getLogger("ragwiki.extract")


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


def _template_names(code) -> set[str]:
    return {str(t.name).strip().lower() for t in code.filter_templates(recursive=False)}


def _categories(code) -> list[str]:
    out = []
    for link in code.filter_wikilinks():
        title = str(link.title).strip()
        if title.lower().startswith(("categoria:", "category:")):
            out.append(title.split(":", 1)[1].strip())
    return out


def infobox_params(code, template_names: list[str]) -> dict[str, str] | None:
    """Parameters of the first film infobox: normalized name -> wikitext value."""
    wanted = {n.lower() for n in template_names}
    for template in code.filter_templates(recursive=False):
        if str(template.name).strip().lower() in wanted:
            return {
                " ".join(str(p.name).strip().lower().split()): str(p.value).strip()
                for p in template.params
            }
    return None


def _may_be_a_film(text: str, cfg: ExtractConfig) -> bool:
    """Necessary condition, checked on the raw text before parsing: a film infobox or a `Film ...`
    category must appear. Never rejects a page that the full check would accept."""
    lowered = text.lower()
    if "[[categoria:film" in lowered or "[[category:film" in lowered:
        return True
    return any(re.search(r"\{\{\s*" + re.escape(name.lower()) + r"\s*[|\n}<]", lowered) for name in cfg.film_templates)


def classify_page(page: Page, cfg: ExtractConfig) -> tuple[dict | None, str]:
    """(candidate, reason). The reason is 'ok' for candidates, otherwise why the page was rejected."""
    if page.namespace != 0:
        return None, "not_article"
    if page.redirect or page.text.lstrip().lower().startswith("#redirect"):
        return None, "redirect"
    lowered = page.title.lower()
    if any(lowered.startswith(prefix) for prefix in cfg.excluded_title_prefixes):
        return None, "list_or_filmography"
    if not _may_be_a_film(page.text, cfg):  # cheap prefilter: skip the expensive parse
        return None, "not_a_film"
    code = mwparserfromhell.parse(page.text)
    templates = _template_names(code)
    if templates & {n.lower() for n in cfg.disambiguation_templates}:
        return None, "disambiguation"
    infobox = infobox_params(code, cfg.film_templates)
    flags: list[str] = []
    if infobox is None:
        # Secondary signal: a film category without infobox is accepted but flagged.
        if not any(c.lower().startswith("film ") for c in _categories(code)):
            return None, "not_a_film"
        flags.append("no_infobox")
    plot = extract_plot(
        page.text,
        headings=cfg.plot_headings,
        min_chars=cfg.min_plot_chars,
        min_words=cfg.min_plot_words,
    )
    if plot.reason != "ok" or plot.text is None:
        return None, plot.reason
    return {
        "page_id": page.page_id,
        "title": page.title,
        "revision_id": page.revision_id,
        "timestamp": page.timestamp,
        "infobox": infobox or {},
        "plot": plot.text,
        "plot_heading": plot.heading,
        "flags": flags + plot.flags,
    }, "ok"


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def run_extract(
    config: PipelineConfig,
    *,
    dump_path: Path | None = None,
    limit: int | None = None,
    allow_truncated: bool = False,
    resume: bool = True,
) -> dict:
    """Dump -> candidates.jsonl (+ rejected.jsonl, checkpoint). Returns the statistics."""
    cfg = config.extract
    out_dir = config.processed_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    source = dump_path or config.dump_path
    cand_path = out_dir / config.output.candidates_file
    rej_path = out_dir / config.output.rejected_file
    ckpt_path = out_dir / "extract_checkpoint.json"

    seen = 0
    stats: Counter[str] = Counter()
    mode = "w"
    if resume and ckpt_path.exists() and cand_path.exists():
        ckpt = json.loads(ckpt_path.read_text(encoding="utf-8"))
        if ckpt.get("source") == source.name and not ckpt.get("complete"):
            seen = ckpt["pages_seen"]
            stats.update(ckpt["stats"])
            mode = "r+"
            with cand_path.open("r+b") as handle:
                handle.truncate(ckpt["candidates_bytes"])
            with rej_path.open("r+b") as handle:
                handle.truncate(ckpt["rejected_bytes"])
            log.info("resuming after %d pages", seen)

    processed = 0
    with open_dump(source) as stream, cand_path.open("ab" if mode == "r+" else "wb") as cand, rej_path.open(
        "ab" if mode == "r+" else "wb"
    ) as rej:
        for index, page in enumerate(iter_pages(stream, allow_truncated=allow_truncated)):
            if index < seen:
                continue
            seen = index + 1
            try:
                candidate, reason = classify_page(page, cfg)
            except Exception as error:  # a broken page must not stop the pipeline
                candidate, reason = None, "parse_error"
                log.warning("page %s (%s) failed: %s", page.page_id, page.title, error)
            stats[reason] += 1
            if candidate is not None:
                cand.write((json.dumps(candidate, ensure_ascii=False, sort_keys=True) + "\n").encode())
                processed += 1
            elif reason in {"plot_too_short", "no_plot_section", "parse_error"}:
                line = {"page_id": page.page_id, "title": page.title, "reason": reason}
                rej.write((json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n").encode())
            if seen % cfg.checkpoint_every_pages == 0:
                cand.flush()
                rej.flush()
                _write_json(
                    ckpt_path,
                    {
                        "source": source.name,
                        "pages_seen": seen,
                        "stats": dict(stats),
                        "candidates_bytes": cand.tell(),
                        "rejected_bytes": rej.tell(),
                        "complete": False,
                    },
                )
                log.info("pages=%d films=%d", seen, stats["ok"])
            if limit is not None and stats["ok"] >= limit:
                break
        cand.flush()
        rej.flush()
        _write_json(
            ckpt_path,
            {
                "source": source.name,
                "pages_seen": seen,
                "stats": dict(stats),
                "candidates_bytes": cand.tell(),
                "rejected_bytes": rej.tell(),
                "complete": True,
            },
        )
    summary = {"pages_seen": seen, "stats": dict(sorted(stats.items()))}
    log.info("extract done: %s", summary)
    return summary
