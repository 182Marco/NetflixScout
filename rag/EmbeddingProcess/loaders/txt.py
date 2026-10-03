from .base import Document


def load_txt(path: str) -> list[Document]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return [Document(text, {"source": path, "type": "txt"})]
