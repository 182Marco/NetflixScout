"""Plot extraction and cleaning from Italian Wikipedia wikitext.

Parsing is done on the mwparserfromhell node tree (nested templates, refs and links are handled by
the parser, never by regular expressions on markup). Only the text of the plot section is kept.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

import mwparserfromhell
from mwparserfromhell.nodes import (
    Argument,
    Comment,
    ExternalLink,
    Heading,
    HTMLEntity,
    Tag,
    Template,
    Text,
    Wikilink,
)
from mwparserfromhell.wikicode import Wikicode

# Wikilink namespaces that carry no narrative (images, categories, interlanguage...).
DROP_LINK_PREFIXES = ("file:", "immagine:", "image:", "categoria:", "category:", "media:", "wikipedia:")
# Tags whose content is never narrative.
DROP_TAGS = {"ref", "references", "table", "gallery", "math", "timeline", "imagemap", "score", "noinclude"}
# Inline templates that wrap narrative text: name -> 1-based positional argument holding the text.
INLINE_TEMPLATES = {"nowrap": 1, "lang": 2, "corsivo": 1, "grassetto": 1, "smallcaps": 1}
LEAD_MARKUP_RE = re.compile(r"^[\s*#:;]+")
MULTISPACE_RE = re.compile(r"[ \t   ]+")
SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?])")
EMPTY_PARENS_RE = re.compile(r"\(\s*\)")
INVISIBLE_RE = re.compile(r"[​‌‍⁠﻿­]")


@dataclass
class PlotResult:
    text: str | None
    heading: str | None = None
    reason: str = "ok"  # ok | no_plot_section | plot_too_short
    flags: list[str] = field(default_factory=list)


def normalize_heading(title: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", title).strip().strip(":").lower())


def _render(nodes) -> str:
    parts: list[str] = []
    for node in nodes:
        if isinstance(node, Text):
            parts.append(str(node.value))
        elif isinstance(node, HTMLEntity):
            parts.append(node.normalize())
        elif isinstance(node, (Comment, Argument, Heading)):
            continue
        elif isinstance(node, Wikilink):
            title = str(node.title).strip()
            if title.lower().lstrip(":").startswith(DROP_LINK_PREFIXES):
                continue
            parts.append(_render(node.text.nodes) if node.text is not None else _render(node.title.nodes))
        elif isinstance(node, ExternalLink):
            if node.title is not None:
                parts.append(_render(node.title.nodes))
        elif isinstance(node, Template):
            name = str(node.name).strip().lower()
            index = INLINE_TEMPLATES.get(name)
            if index is not None and node.has(str(index)):
                parts.append(_render(node.get(str(index)).value.nodes))
        elif isinstance(node, Tag):
            tag = str(node.tag).strip().lower()
            if tag in DROP_TAGS:
                continue
            if tag == "br":
                parts.append("\n")
            elif node.contents is not None:
                inner = _render(node.contents.nodes)
                parts.append(f"\n\n{inner}\n\n" if tag in {"p", "div", "blockquote"} else inner)
        else:
            parts.append(str(node))
    return "".join(parts)


def _normalize_text(raw: str) -> str:
    text = unicodedata.normalize("NFC", INVISIBLE_RE.sub("", raw.replace("\r\n", "\n")))
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [MULTISPACE_RE.sub(" ", LEAD_MARKUP_RE.sub("", line)).strip() for line in block.split("\n")]
        joined = " ".join(line for line in lines if line)
        joined = SPACE_BEFORE_PUNCT_RE.sub(r"\1", EMPTY_PARENS_RE.sub("", joined))
        joined = MULTISPACE_RE.sub(" ", joined).strip()
        if joined:
            paragraphs.append(joined)
    return "\n\n".join(paragraphs)


def clean_wikitext(wikitext: str | Wikicode) -> str:
    """Wikitext fragment -> plain narrative text, paragraphs separated by a blank line."""
    code = mwparserfromhell.parse(wikitext) if isinstance(wikitext, str) else wikitext
    return _normalize_text(_render(code.nodes))


def find_plot_section(wikitext: str, headings: list[str]) -> tuple[Wikicode | None, str | None, list[str]]:
    """First section (with its subsections) whose heading is a plot heading."""
    wanted = {normalize_heading(h) for h in headings}
    code = mwparserfromhell.parse(wikitext)
    matches: list[tuple[Wikicode, str]] = []
    for section in code.get_sections(include_lead=False, include_headings=True, flat=False):
        found = section.filter_headings(recursive=False)
        if not found:
            continue
        title = normalize_heading(str(found[0].title))
        if title in wanted:
            matches.append((section, str(found[0].title).strip()))
    if not matches:
        return None, None, []
    flags = ["multiple_plot_sections"] if len(matches) > 1 else []
    return matches[0][0], matches[0][1], flags


def extract_plot(wikitext: str, *, headings: list[str], min_chars: int, min_words: int) -> PlotResult:
    section, heading, flags = find_plot_section(wikitext, headings)
    if section is None:
        return PlotResult(None, None, "no_plot_section")
    text = clean_wikitext(section)
    if len(text) < min_chars or len(text.split()) < min_words:
        return PlotResult(text or None, heading, "plot_too_short", flags)
    return PlotResult(text, heading, "ok", flags)
