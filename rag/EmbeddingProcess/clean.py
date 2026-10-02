"""clean.py — pulire il testo grezzo prima di chunking/embedding.

Il testo che esce dai loader (Modulo 2 · Lezione 4) è **grezzo**: boilerplate, righe spezzate,
whitespace a caso, header ripetuti, numeri di pagina. Se lo diamo così a
chunking/embedding, il *noise* si porta dietro tutta la pipeline (chunk sporchi
→ embedding sporchi → retrieval peggiore).

Idea di fondo — la stessa di Modulo 2 · Lezione 3: **funzioni pure `str -> str`** (ogni step fa
UNA cosa) + un piccolo runner che le compone. Nessun framework: una pipeline è
solo una lista di funzioni applicate in ordine. Il docente sceglie step diversi
per documenti diversi (un `.txt` di Gutenberg non ha lo stesso noise di un PDF).

    from rag.EmbeddingProcess import clean, load
    from rag.EmbeddingProcess.clean import normalize_whitespace, reflow_paragraphs

    text = load("libro.txt")[0].text
    pulito = clean(text, [normalize_whitespace, reflow_paragraphs])

Gli step parametrici (soglie, elenchi di heading) sono **factory**: restituiscono
uno step `str -> str` già configurato, così la pipeline resta una lista di
funzioni uniformi.
"""
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


# ---------------------------------------------------------------- una ricetta per tipo di file
# La "conoscenza" del noise di ogni formato sta QUI. Per lavorare su un nuovo tipo
# di documento: si aggiunge la funzione-step qui sopra e la si registra in questa
# mappa. Nient'altro da toccare — `ask.py` usa `pipeline_for()` in automatico.
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

# ricetta di riserva per estensioni non ancora previste
DEFAULT_STEPS = [normalize_unicode, normalize_whitespace]


def pipeline_for(path: str) -> list:
    """La ricetta di cleaning giusta per l'estensione del file."""
    from pathlib import Path
    return PIPELINES.get(Path(path).suffix.lower(), DEFAULT_STEPS)


def clean_file(path: str) -> str:
    """Carica un file (loader di Modulo 2 · Lezione 4) e lo ripulisce con la sua pipeline.

    Un solo posto da toccare per un documento nuovo: gli step qui sopra + la mappa
    `PIPELINES`. Chi vuole vedere l'effetto sul chatbot usa `ask.py`.
    """
    from .loaders import load          # import pigro: clean.py resta un modulo di sole funzioni
    grezzo = "\n".join(d.text for d in load(path))
    return clean(grezzo, pipeline_for(path))
