"""Markdown → testo (markdown-it-py).

Il formato più gentile: è già testo + una sintassi leggera. Lo parsiamo (render →
HTML → testo) per gestire la sintassi in modo pulito invece di lasciarla grezza.
"""
from bs4 import BeautifulSoup
from markdown_it import MarkdownIt

from .base import Document

_md = MarkdownIt()


def load_markdown(path: str) -> list[Document]:
    with open(path, encoding="utf-8") as f:
        sorgente = f.read()
    html = _md.render(sorgente)
    text = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
    return [Document(text, {"source": path, "type": "markdown"})]
