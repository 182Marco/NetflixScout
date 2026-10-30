"""What the web entry point passes to `handle_query(final_output=...)`.

The final answer call then returns `{"answer", "lists"}` in one strict JSON: the answer text
(unchanged in content) plus references to the resources it presents. The call is streamed: the
text of `answer` reaches the channel while it is written, the lists only when the JSON is
complete. The references are only claims: `attach_lists` checks every one against the tool
results of the turn.
"""
from __future__ import annotations

from typing import Any

from .json_schema import json_schema

INSTRUCTIONS = (
    "Rispondi con un JSON con due campi. `answer` è la risposta completa per l'utente, scritta "
    "come sempre (stesso contenuto, stile e Markdown che useresti senza questo formato). "
    "`lists` raggruppa in liste tematiche i film, le serie e i video che la risposta PRESENTA "
    "o consiglia come risultato; non inserire titoli citati solo per negarli, escluderli, "
    "confrontarli o ricordarli di passaggio. Usa solo risorse presenti nei risultati dei tool "
    "di questo turno e leggi gli id da lì: per TMDb dal riferimento 'TMDb movie/NNN' o "
    "'TMDb tv/NNN' (media_type movie o tv, id numerico), da tmdb_url (…/movie/NNN, …/tv/NNN); "
    "per YouTube (source youtube) il video_id è il campo `video_id` del video. Non inventare id. `answer` non contiene mai URL o link. "
    "`quote` è una frase o riga che copi ESATTAMENTE da `answer` e che contiene il titolo della "
    "risorsa mentre la presenta. `reason` è una frase breve (massimo 140 caratteri) nella "
    "lingua della risposta. `list_id` è uno slug minuscolo stabile (lettere, numeri, trattini); "
    "riusa lo stesso slug se continui un tema già trattato. `kind` è movies, series, videos o "
    "mixed. Al massimo 4 liste da 12 elementi. Se non presenti titoli o video, `lists` è []."
)


# Name of the field with the answer text: the orchestrator streams its decoded text while the
# JSON is written (it knows the name from this data, it never imports this package).
ANSWER_FIELD = "answer"


def final_output() -> dict[str, Any]:
    return {"text_format": json_schema(), "instructions": INSTRUCTIONS, "answer_field": ANSWER_FIELD}
