"""PDF → testo, pagina per pagina (pypdf).

Il PDF non è testo lineare: è un layout di blocchi. `pypdf` estrae il testo di
ogni pagina; teniamo il numero di pagina nei metadata (utile per citazioni e
debug del retrieval). Regge il testo lineare; su tabelle/colonne/scansioni va in
crisi → lì servono parser gestiti (vedi Modulo 2 · Lezione 6, LlamaParse).
"""
from pypdf import PdfReader

from .base import Document


def load_pdf(path: str) -> list[Document]:
    reader = PdfReader(path)
    docs = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        docs.append(Document(text, {"source": path, "page": i + 1, "type": "pdf"}))
    return docs
