"""HTML → testo (BeautifulSoup), togliendo prima il noise più ovvio.

Una pagina web è un albero di tag dove il contenuto utile è circondato da menu,
footer, banner, script. Se prendiamo tutto il testo, il *noise* finisce nel
prompt e confonde il modello: `ask()` arriva a citare il menu.

Qui rimuoviamo i tag più rumorosi — è il minimo sindacale. "Pulire bene" è un
mestiere a sé: è la prossima lezione (Modulo 2 · Lezione 5, Text Cleaning).
"""
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
