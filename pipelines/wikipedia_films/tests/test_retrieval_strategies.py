import numpy as np
import pytest

from pipelines.wikipedia_films.retrieval import strategies as S
from pipelines.wikipedia_films.retrieval.corpus import Corpus, Film, norm
from pipelines.wikipedia_films.retrieval.models import Signals, TitleRef


class FakeCorpus(Corpus):
    """In-memory corpus: unit vectors on a plane; no Qdrant, no API."""
    def __init__(self, films, key="new"):
        self.key, self.lang, self.collection = key, "it", "fake"
        self.films = films
        self._vocab = None

    def embed(self, texts):
        return np.vstack([_vec(t) for t in texts])

    def search(self, vector, *, limit, flt=None, with_vectors=False):
        sc = sorted(self.films, key=lambda f: -float(f.vector @ vector))
        for f in sc:
            f.score = float(f.vector @ vector)
        return sc[:limit]

    def resolve(self, title_it, title_original, year):
        for f in self.films:
            if norm(f.title) in (norm(title_it), norm(title_original)):
                return f
        return None

    def positive_filter(self, sg):
        return None


def _vec(text):
    angle = {"horror": 0.0, "possessione": 0.5, "thriller": 1.5, "commedia": 3.0}.get(text.split()[0], 0.2)
    return np.array([np.cos(angle), np.sin(angle)], dtype=np.float32)


def film(pid, title, angle, **kw):
    return Film(pid, title, kw.get("original"), kw.get("year", 2000), kw.get("genres", []), "plot", franchise_ids=kw.get("fr", []),
                vector=np.array([np.cos(angle), np.sin(angle)], dtype=np.float32))


def signals(**kw):
    base = dict(positive_it="horror psicologico", positive_en="psych horror")
    base.update(kw)
    return Signals(**base)


def test_cited_film_and_franchise_are_removed():
    corpus = FakeCorpus([film("a", "Alien", 0.0, original="Alien"), film("b", "Aliens", 0.05), film("c", "Predator", 0.1), film("d", "Se7en", 0.2)])
    ctx = S.build_context(corpus, signals(like_titles=[TitleRef(title_it="Alien", title_original="Alien", summary_it="x", summary_en="x")],
                                          avoid_franchise_names=["Alien"]))
    assert [f.title for f in S.s1(ctx)["films"]][:2] == ["Aliens", "Predator"]
    assert [f.title for f in S.s2n(ctx)["films"]][:2] == ["Predator", "Se7en"]


def test_franchise_ids_exclude_crossovers_by_id():
    corpus = FakeCorpus([film("a", "Alien", 0.0, fr=["Q1"]), film("b", "Prometheus", 0.05, fr=["Q1"]), film("c", "Se7en", 0.2, fr=[])])
    ctx = S.build_context(corpus, signals(like_titles=[TitleRef(title_it="Alien", title_original="Alien", summary_it="x", summary_en="x")]))
    assert [f.title for f in S.s2f(ctx)["films"]] == ["Se7en"]
    assert S.s2f(S.build_context(FakeCorpus([], key="old"), signals())) is None


def test_penalty_demotes_films_close_to_the_trait_to_avoid():
    corpus = FakeCorpus([film("a", "Possessed", 0.45), film("b", "Quiet", 0.3), film("c", "Ghost", 0.5)])
    ctx = S.build_context(corpus, signals(positive_it="horror psicologico", avoid_descriptions_it=["possessione demoniaca"], avoid_descriptions_en=["possession"]))
    order = [f.title for f in S.s3(ctx)["films"]]
    assert order[0] == "Quiet" and order.index("Possessed") > order.index("Quiet")


def test_genre_and_format_exclusions():
    corpus = FakeCorpus([film("a", "Z", 0.0, genres=["film horror splatter"]), film("b", "Y", 0.1, genres=["film horror"])])
    ctx = S.build_context(corpus, signals(avoid_genres_it=["splatter"], keep_genres_it=["horror"]))
    assert [f.title for f in S.s4(ctx)["films"]] == ["Y"]


def test_a_genre_that_is_also_wanted_is_not_excluded():
    corpus = FakeCorpus([film("a", "Z", 0.0, genres=["film horror"])])
    ctx = S.build_context(corpus, signals(avoid_genres_it=["horror"], keep_genres_it=["horror psicologico"]))
    assert ctx.avoid_genre_terms == []
