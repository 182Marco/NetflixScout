"""loaders/ — leggere file eterogenei e normalizzarli in un `Document`.

    from loaders import load
    docs = load("report.pdf")      # -> list[Document], qualunque sia il formato

Quattro formati, quattro loader, una sola interfaccia. Da qui in poi nessuno deve
più sapere da quale formato veniva un documento.
"""
from .base import Document
from .dispatch import load

__all__ = ["Document", "load"]
