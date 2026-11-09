"""Live check of the domain classifier (gpt-4o-mini, costs a few cents): the anime cases that used to be blocked, the non-film controls, and every question of the routing
cases (all of them are film/series questions and must stay cinematic).   python -m movie_db.harness.evaluation.run_classifier_eval --live"""
from __future__ import annotations

import sys

ANIME_AND_CONTROLS = (
    ("Consigliami un anime", True), ("Consigliami un anime di avventura", True),
    ("Cerco un anime di avventura con un ragazzo che vuole diventare il più forte spadaccino", True),
    ("Quali sono i migliori anime sui samurai?", True), ("Anime mecha con una guerra tra colonie spaziali", True),
    ("What is a good anime about time travel?", True), ("Consigliami un anime di Studio Ghibli", True),
    ("Dimmi gli episodi della seconda stagione di Attack on Titan", True), ("Consigliami una serie animata per adulti", True),
    ("Il manga di Dragon Ball è stato adattato in anime: quando è uscito l'anime?", True),
    ("Consigliami una serie TV di fantascienza", True), ("Consigliami un film horror", True), ("Chi ha diretto Parasite?", True),
    ("Consigliami un manga", False), ("Consigliami un manga di avventura con samurai", False), ("Consigliami un videogioco di ruolo", False),
    ("Consigliami un fumetto Marvel da leggere", False), ("Consigliami un libro di fantascienza", False), ("Come si fa la carbonara?", False),
    ("Chi ha vinto lo scudetto nel 2005?", False), ("Spiegami la teoria della relatività", False),
)


def main() -> int:
    if "--live" not in sys.argv:
        print(__doc__); return 2
    from dotenv import load_dotenv
    load_dotenv()
    from movie_db.harness.evaluation.routing_cases import ROUTING_CASES, SERIES_ROUTING_CASES
    from query_classifier.query_classifier import classify_query_domain
    bad = [(q, w) for q, w in ANIME_AND_CONTROLS if classify_query_domain(q, [])["is_cinema"] is not w]
    print(f"anime and controls: {len(ANIME_AND_CONTROLS) - len(bad)}/{len(ANIME_AND_CONTROLS)}", *bad, sep="\n  ")
    cases = [*ROUTING_CASES, *SERIES_ROUTING_CASES]
    blocked = [c.question for c in cases if not classify_query_domain(c.question, list(c.history)[-6:])["is_cinema"]]
    print(f"routing questions kept cinematic: {len(cases) - len(blocked)}/{len(cases)}", *blocked, sep="\n  ")
    return 0 if not bad and not blocked else 1


if __name__ == "__main__":
    sys.exit(main())
