from pypdf import PdfReader

from .base import Document


def load_pdf(path: str) -> list[Document]:
    reader = PdfReader(path)
    docs = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        docs.append(Document(text, {"source": path, "page": i + 1, "type": "pdf"}))
    return docs
