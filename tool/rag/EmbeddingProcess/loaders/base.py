from dataclasses import dataclass, field


@dataclass
class Document:
    text: str
    metadata: dict = field(default_factory=dict)

    def __repr__(self):
        anteprima = " ".join(self.text.split())[:60]
        return f"Document({self.metadata}, text={anteprima!r}…)"
