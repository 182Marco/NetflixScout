from bs4 import BeautifulSoup

from .base import Document

NOISE = ["script", "style", "nav", "footer", "header", "aside"]


def load_html(path: str) -> list[Document]:
    with open(path, encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")
    for tag in soup(NOISE):           # via il noise più ovvio
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return [Document(text, {"source": path, "type": "html"})]
