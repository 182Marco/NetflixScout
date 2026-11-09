"""Request → `Signals`, one LLM call. A failure never breaks the turn: the plain request is searched with no exclusions."""
from __future__ import annotations

from openai import OpenAI

from .models import Signals

INSTRUCTIONS = """You are the query parser of a film recommendation engine. The user writes in any language; write the Italian fields in Italian. Fill the schema.

Positive part:
- positive_it / positive_en: ONE sentence describing the kind of film the user WANTS: story situation, themes, atmosphere, setting, genre.
  It must never contain what the user wants to AVOID, and never be a negation (an embedding of "without X" is close to X).
  When the user cites a film as a reference ("come X"), describe X's themes, situation and tone in plain words; do not write "simile a X".
- like_titles: films cited as references of closeness. For each give the Italian title, the original/English title, the year only if you are sure,
  and a short plot summary in Italian and in English (you know these films; stay factual and non-spoiler).

Negative part (be exact, and never wider than the user's words):
- avoid_titles: films the user names as things to avoid that are NOT also references. A film cited as reference that must also be left out
  ("simili a X, escludi X") goes only in like_titles (cited films are always removed from the answer).
- avoid_franchise_names: when the user excludes a saga/franchise/sequels ("niente altri film di Alien", "escludi tutta la saga", "non voglio sequel",
  "niente Batman", "ma non i film della Terra di Mezzo"), list the franchise names in their original form (e.g. "Alien", "The Matrix", "Hannibal Lecter",
  "Batman", "Middle-earth", "The Hobbit", "Lord of the Rings"). Include every name that identifies the saga.
- avoid_descriptions_it / avoid_descriptions_en: every narrative trait, element or subgenre to avoid, each described POSITIVELY as what the
  unwanted film shows ("possessioni demoniache, esorcismi e fenomeni soprannaturali"; "serial killer che uccide in serie"; "viaggi nel tempo e paradossi temporali").
  One item per excluded thing; same order in both languages. Never negate. A vague dislike stays a description, never a genre filter.
- A "non X" / "senza X" where X is a setting, period, subgenre or trait ("non fantasy medievale", "senza ambientazioni innevate") ALWAYS yields an avoid_descriptions entry
  (what that unwanted film shows), even when X also appears in avoid_genres_it.
- avoid_genres_it: only when the exclusion is a film genre or subgenre named as such ("non zombie movie", "non splatter", "non commedie romantiche"), as named
  by Italian Wikipedia. Never a broad genre that is also wanted. keep_genres_it: the genres wanted.
- Do not put in avoid_* anything the user wants.

Filters: year_from/year_to, countries (Italian), directors, actors only when explicit. rare_terms: concrete words that must occur in the plot (a character name,
a place, an object); empty for thematic requests.
Contradiction: set contradictory=true ONLY when two demands of the request cannot both be met by any film (e.g. "horror ma che non faccia paura", "fantascienza senza
tecnologia", "simile a X ma senza nulla in comune con X", "thriller lento e contemplativo ma con tantissima azione", "film di guerra senza guerra"). A request that merely
EXCLUDES a trait, subgenre, franchise or film from a genre that can exist without it ("horror psicologico senza elementi soprannaturali", "fantascienza senza alieni",
"come X ma non della saga di X") is NOT contradictory. In contradiction_note (Italian) say what contradicts and which coherent part can be served; positive_* then describe
the coherent part.
requested_count: the number of films asked, if any.
Return JSON only."""


def parse(question: str, *, client: OpenAI, model: str, effort: str | None = None) -> Signals:
    extra = {"reasoning": {"effort": effort}} if effort else {}
    resp = client.responses.parse(model=model, instructions=INSTRUCTIONS, input=question, text_format=Signals, **extra)
    if resp.output_parsed is None:
        raise RuntimeError("the parser returned no output")
    return resp.output_parsed


def fallback(question: str) -> Signals:
    return Signals(positive_it=question, positive_en=question)
