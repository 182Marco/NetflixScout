"""llm_client.py — parla col modello e tiene il conto della spesa.

È il client costruito a Modulo 2 · Lezione 3, promosso in aikit/ (coi prezzi inclusi, che a
Modulo 2 · Lezione 3 stavano in pricing.py). NON si tocca, si importa:

    from aikit.llm_client import LLMClient

    llm = LLMClient()
    risposta = llm.chat([{"role": "user", "content": "Ciao!"}],
                        instructions="Sei un assistente cortese.")
    print(risposta, llm.costo_totale)
"""
from dotenv import load_dotenv
from openai import OpenAI, APIError, AuthenticationError

load_dotenv()

# prezzo input / output in USD per 1.000.000 di token (giugno 2026,
# fonte openai.com/api/pricing — cambiano nel tempo, vanno verificati)
PRICING = {
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
    "gpt-5.6-luna": {"input": 0.20, "output": 1.20},   # da Modulo 3 · Lezione 9 (prezzi del 30/07/2026)
    "gpt-4.1":      {"input": 2.00, "output": 8.00},
}


def cost_usd(model, input_tokens, output_tokens):
    """Costo in dollari di una chiamata, dati i token consumati (Modulo 2 · Lezione 2)."""
    prezzi = PRICING[model]
    return (input_tokens / 1_000_000 * prezzi["input"]
            + output_tokens / 1_000_000 * prezzi["output"])


class LLMClient:
    def __init__(self, model="gpt-4.1-mini", temperature=0.7):
        self.model = model
        self.temperature = temperature
        self._client = OpenAI(max_retries=3, timeout=30)
        self.costo_totale = 0.0
        self.n_chiamate = 0
        self.ultimo_uso = (0, 0, 0.0)        # (input, output, costo) dell'ultima chiamata

    def chat(self, messaggi, instructions=None):
        try:
            r = self._client.responses.create(
                model=self.model,
                instructions=instructions,
                input=messaggi,
                temperature=self.temperature,
            )
        except AuthenticationError:
            raise SystemExit("Chiave API non valida o assente: controlla il file .env")
        except APIError as e:
            self.ultimo_uso = (0, 0, 0.0)
            return f"[errore API: {type(e).__name__} — riprova tra poco]"

        u = r.usage
        costo = cost_usd(self.model, u.input_tokens, u.output_tokens)
        self.costo_totale += costo
        self.n_chiamate += 1
        self.ultimo_uso = (u.input_tokens, u.output_tokens, costo)
        return r.output_text
