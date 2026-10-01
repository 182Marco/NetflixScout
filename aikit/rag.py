"""Generic retrieval and answer-generation helpers for RAG pipelines."""

from dotenv import load_dotenv
from openai import OpenAI

from aikit import vectorstore

load_dotenv()

client = OpenAI()

def recupera(query, collection_name, k, embedding_backend, embedding_model, db_dir=None):
    """Retrieve the top-k chunks for a query from a vector collection."""
    collection = vectorstore.apri_collection(
        collection_name,
        db_dir=db_dir,
    )
    return vectorstore.search(
        collection,
        query,
        k,
        backend=embedding_backend,
        model=embedding_model,
    )


def genera(chunks, domanda, model, instructions, storia=None, openai_client=None):
    """Generate an answer from retrieved chunks using the supplied prompt rules."""
    documenti = ""
    for chunk in chunks:
        meta = []
        if chunk.get("title"):
            meta.append(f"titolo: {chunk['title']}")
        if chunk.get("release_year"):
            meta.append(f"anno: {chunk['release_year']}")
        if chunk.get("release_date"):
            meta.append(f"data_uscita: {chunk['release_date']}")
        if chunk.get("genres"):
            meta.append(f"generi: {chunk['genres']}")
        if chunk.get("cast"):
            meta.append(f"cast: {chunk['cast']}")
        meta_testo = "\n".join(meta)
        documenti += (
            f"<documento>\n{meta_testo}\n<trama>\n{chunk['testo']}\n"
            "</trama>\n</documento>\n"
        )
    prompt = f"<documenti>\n{documenti}</documenti>\n\n<domanda>\n{domanda}\n</domanda>"

    if storia is None:
        storia = []
    active_client = openai_client or client
    response = active_client.responses.create(
        model=model,
        instructions=instructions,
        input=storia + [{"role": "user", "content": prompt}],
    )
    return response.output_text


def rispondi(
    query,
    *,
    collection_name,
    k,
    embedding_backend,
    embedding_model,
    model,
    instructions,
    db_dir=None,
    storia=None,
    openai_client=None,
):
    """Run retrieve + generate with fully explicit configuration."""
    chunks = recupera(
        query,
        collection_name=collection_name,
        k=k,
        embedding_backend=embedding_backend,
        embedding_model=embedding_model,
        db_dir=db_dir,
    )
    return genera(
        chunks,
        query,
        model=model,
        instructions=instructions,
        storia=storia,
        openai_client=openai_client,
    ), chunks
