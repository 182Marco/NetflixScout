"""load(): un'unica porta d'ingresso.

Chi carica un documento non deve sapere quale libreria serve per quale file. Una
sola funzione smista per estensione e restituisce sempre dei `Document`.
Aggiungere un formato = aggiungere una riga qui e una funzione nel suo modulo.
"""
from pathlib import Path

from .base import Document
from .docx import load_docx
from .html import load_html
from .markdown import load_markdown
from .pdf import load_pdf
from .txt import load_txt


def load(path: str) -> list[Document]:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return load_pdf(path)
    if ext == ".docx":
        return load_docx(path)
    if ext in (".html", ".htm"):
        return load_html(path)
    if ext in (".md", ".markdown"):
        return load_markdown(path)
    if ext == ".txt":
        return load_txt(path)
    raise ValueError(f"Formato non supportato: {ext}")
