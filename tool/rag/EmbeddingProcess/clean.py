import re
import unicodedata
from collections import Counter

Step = "Callable[[str], str]"


# ---------------------------------------------------------------- runner
def clean(text: str, steps: list) -> str:
    """Applica gli step in ordine. Una pipeline è solo una lista di funzioni."""
    for step in steps:
        text = step(text)
    return text


# ---------------------------------------------------------------- step base (str -> str)
def normalize_unicode(text: str) -> str:
    """Forma unicode canonica (NFC): 'e´' → 'é', accenti compositi uniformati."""
    return unicodedata.normalize("NFC", text)


def strip_control_chars(text: str) -> str:
    """Via i caratteri di controllo invisibili (tranne \\n e \\t)."""
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c)[0] != "C")


def normalize_whitespace(text: str) -> str:
    """Spazi/tab multipli → uno; niente spazi a fine riga; max una riga vuota."""
    text = text.replace("\t", " ")
    text = re.sub(r"[ ]{2,}", " ", text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def dehyphenate(text: str) -> str:
    """Riunisce le parole spezzate a fine riga: 'lit-\\nerature' → 'literature'.

    Tipico dei PDF impaginati a giustezza fissa. Uniamo solo se prima e dopo il
    trattino ci sono lettere (non tocchiamo 'e-mail' o '2019-2020').
    """
    return re.sub(r"([A-Za-zÀ-ÿ])-\n([A-Za-zÀ-ÿ])", r"\1\2", text)


def reflow_paragraphs(text: str) -> str:
    """Ricompone i paragrafi spezzati a ~70 caratteri (Gutenberg & co.).

    Il singolo '\\n' dentro un paragrafo è un a-capo di impaginazione, non una
    vera interruzione: lo trasformiamo in spazio. La riga vuota (paragrafo)
    resta. Così il testo torna a "scorrere".
    """
    paragrafi = re.split(r"\n\s*\n", text)
    ricomposti = [" ".join(p.split()) for p in paragrafi if p.strip()]
    return "\n\n".join(ricomposti)


def remove_page_numbers(text: str) -> str:
    """Elimina le righe fatte solo da un numero (numeri di pagina dei PDF)."""
    return "\n".join(l for l in text.split("\n") if not l.strip().isdigit())


# ---------------------------------------------------------------- step factory (parametrici)
def remove_repeated_lines(min_repeats: int = 3, max_len: int = 80):
    """Rimuove le righe (corte) che si ripetono: header/footer ricorrenti.

    Es. 'Published as a conference paper at ICLR 2019' su ogni pagina. Contiamo
    le righe: se una riga corta compare almeno `min_repeats` volte, è quasi
    sicuramente un elemento di impaginazione, non contenuto.
    """
    def step(text: str) -> str:
        conteggio = Counter(l.strip() for l in text.split("\n") if l.strip())
        ripetute = {r for r, n in conteggio.items() if n >= min_repeats and len(r) <= max_len}
        return "\n".join(l for l in text.split("\n") if l.strip() not in ripetute)
    return step


def remove_citation_markers():
    """Toglie i riferimenti tipo '[12]' (note/citazioni delle pagine web)."""
    return lambda text: re.sub(r"\[\d+\]", "", text)


def keep_between_markers(start: str, end: str):
    """Tiene solo il corpo tra due marcatori (boilerplate di Project Gutenberg).

    Es. start='*** START', end='*** END': butta licenza, crediti, metadata che
    stanno prima/dopo il testo vero.
    """
    def step(text: str) -> str:
        lines = text.split("\n")
        i = next((k for k, l in enumerate(lines) if start in l), None)
        j = next((k for k, l in enumerate(lines) if end in l), None)
        if i is None:
            i = -1
        if j is None:
            j = len(lines)
        return "\n".join(lines[i + 1:j])
    return step


def drop_sections(headings: list):
    """Tronca il testo alla prima sezione 'di coda' (Note, Bibliografia,

    Collegamenti esterni, Voci correlate…): boilerplate tipico di Wikipedia che
    non serve al contenuto.
    """
    def step(text: str) -> str:
        lines = text.split("\n")
        for k, l in enumerate(lines):
            if l.strip() in headings:
                return "\n".join(lines[:k]).strip()
        return text
    return step



PIPELINES = {
    ".txt": [                                  # libro Gutenberg: boilerplate + righe a ~70 char
        keep_between_markers("*** START", "*** END"),
        normalize_unicode,
        reflow_paragraphs,
    ],
    ".pdf": [                                   # PDF impaginato: sillabazione, header, n° pagina
        dehyphenate,
        remove_repeated_lines(min_repeats=3),
        remove_page_numbers,
        normalize_whitespace,
    ],
    ".html": [                                  # pagina web: note [n], sezioni di coda, whitespace
        remove_citation_markers(),
        drop_sections(["Note", "Bibliografia", "Voci correlate", "Collegamenti esterni"]),
        normalize_whitespace,
    ],
}


DEFAULT_STEPS = [normalize_unicode, normalize_whitespace]


def pipeline_for(path: str) -> list:
    from pathlib import Path
    return PIPELINES.get(Path(path).suffix.lower(), DEFAULT_STEPS)


def clean_file(path: str) -> str:

    from .loaders import load
    grezzo = "\n".join(d.text for d in load(path))
    return clean(grezzo, pipeline_for(path))
