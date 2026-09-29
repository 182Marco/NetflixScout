"""TXT → testo (lettura diretta).

Il caso più semplice: un file di testo è già testo. Nessuna libreria, solo
`read()`. Lo teniamo perché nel Data Loading (Modulo 2 · Lezione 4) il `.txt` era l'esercizio
degli studenti, e in Modulo 2 · Lezione 5 ci serve un caso "grezzo ma pulito da riformattare"
(il libro di Project Gutenberg: boilerplate + righe spezzate a ~70 caratteri).
"""
from .base import Document


def load_txt(path: str) -> list[Document]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    return [Document(text, {"source": path, "type": "txt"})]
