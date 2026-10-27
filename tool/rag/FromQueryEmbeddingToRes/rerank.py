"""Reranking helpers for candidate chunks."""

import os
from functools import lru_cache

import cohere
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

load_dotenv(".env")

cohere_client = cohere.ClientV2(api_key=os.getenv("COHERE_API_KEY") or "manca")


@lru_cache(maxsize=1)
def _default_client() -> OpenAI:
    return OpenAI()



def _documento_per_rerank(chunk):
    """Prefix the plot with title, year and genres: the plot alone rarely names its genre."""
    intestazione = []
    if chunk.get("title"):
        anno = chunk.get("release_year") or ""
        intestazione.append(f"Title: {chunk['title']}" + (f" ({anno})" if anno else ""))
    if chunk.get("genres"):
        intestazione.append(f"Genres: {chunk['genres']}")
    if not intestazione:
        return chunk["testo"]
    return "\n".join(intestazione) + "\n\n" + chunk["testo"]


def rerank_cohere(query, chunks, model, cohere_api_client=None):
    """Rerank candidate chunks with Cohere's cross-encoder API."""
    active_client = cohere_api_client or cohere_client
    risposta = active_client.rerank(
        model=model,
        query=query,
        documents=[_documento_per_rerank(chunk) for chunk in chunks],
        top_n=len(chunks),
    )
    riordinati = []
    for result in risposta.results:
        riordinati.append({**chunks[result.index], "score": result.relevance_score})
    return riordinati



def _candidate_line(index, chunk, plot_chars=600):
    year = f" ({chunk['release_year']})" if chunk.get("release_year") else ""
    genres = f" | {chunk['genres']}" if chunk.get("genres") else ""
    return f"[{index}] {chunk.get('title') or '?'}{year}{genres} | {str(chunk.get('testo') or '')[:plot_chars]}"


def rerank_llm_request(request, wanted, avoid, chunks, model, openai_client=None):
    """List-wise LLM rerank for "like X, not like Y": the model knows the cited films, which a cross-encoder given
    a description cannot use as a contrast. Candidates are ranked best to worst; unlisted ones keep their order after."""
    elenco = "\n".join(_candidate_line(i, chunk) for i, chunk in enumerate(chunks))
    instructions = (
        "You rank candidate films for a recommendation request. Use your own knowledge of the films named in the request. "
        "Best = clearly the same kind of story and experience as the film the user likes AND clearly unlike what they want to avoid. "
        "Penalise candidates that resemble the film to avoid, its franchise, tone or style. Never prefer a candidate because it is famous. "
        "Return ALL candidate indices, best first, each once."
    )
    prompt = f"Request: {request}\nWanted (English): {wanted}\nAvoid (English): {avoid}\n\nCandidates:\n{elenco}"
    active_client = openai_client or _default_client()
    risposta = active_client.responses.parse(model=model, instructions=instructions, input=prompt, text_format=Ordine)
    ordine = []
    for i in risposta.output_parsed.indici:
        if 0 <= i < len(chunks) and i not in ordine:
            ordine.append(i)
    ordine += [i for i in range(len(chunks)) if i not in ordine]
    return [{**chunks[i], "score": float(len(chunks) - position)} for position, i in enumerate(ordine)]


class Ordine(BaseModel):
    """Indices of chunks ordered from most to least relevant."""
    indici: list[int]


def rerank_llm(query, chunks, model, openai_client=None, verbose=False):
    """Rerank candidate chunks with a general-purpose LLM."""
    elenco = ""
    for i, chunk in enumerate(chunks):
        elenco += f"[{i}] {_documento_per_rerank(chunk)}\n\n"
    prompt = (f"Domanda: {query}\n\nPassaggi numerati:\n\n{elenco}"
              "Ordina TUTTI i passaggi dal più al meno utile per rispondere alla domanda. "
              "Restituisci gli indici in quell'ordine, ognuno una sola volta.")
    active_client = openai_client or _default_client()
    risposta = active_client.responses.parse(model=model, input=prompt, text_format=Ordine)
    if verbose:
        print(f"  [llm] {risposta.usage.input_tokens} token in, {risposta.usage.output_tokens} out")

    ordine = []
    for i in risposta.output_parsed.indici:
        if 0 <= i < len(chunks) and i not in ordine:
            ordine.append(i)
    for i in range(len(chunks)):
        if i not in ordine:
            ordine.append(i)
    riordinati = []
    for posizione, i in enumerate(ordine):
        riordinati.append({**chunks[i], "score": float(len(chunks) - posizione)})
    return riordinati


def cerca_due_stadi(query, candidati, k_finale, backend, *, cohere_model=None, llm_model=None):
    """Rerank a first-stage candidate list and return the top final chunks."""
    if backend == "cohere":
        if not cohere_model:
            raise ValueError("Serve cohere_model per il backend cohere.")
        riordinati = rerank_cohere(query, candidati, model=cohere_model)
    else:
        if not llm_model:
            raise ValueError("Serve llm_model per il backend llm.")
        riordinati = rerank_llm(query, candidati, model=llm_model)
    return riordinati[:k_finale]
