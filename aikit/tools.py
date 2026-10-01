def definisci_tool(schema, nome):
    """Convert a schema class into the function-tool descriptor expected by the API."""
    return {
        "type": "function",
        "name": nome,
        "description": schema.__doc__,
        "parameters": schema.model_json_schema(),
        "strict": False,
    }


if __name__ == "__main__":
    domande = [SOLO] if SOLO else DOMANDE
    for domanda in domande:
        print("\n" + "=" * 72)
        print(f"D: {domanda}")
        risposta = chiedi(domanda)
        print(f"→ {risposta}")
