from __future__ import annotations

from pydantic import BaseModel, Field


class TitleRef(BaseModel):
    """A film the user cites. `title_original` is the international/original title (what the corpora index); `title_it` the Italian one."""
    title_it: str = Field(description="Italian title as commonly used in Italy")
    title_original: str = Field(description="original or English title")
    year: int | None = Field(default=None, description="release year if you are sure, else null")
    summary_it: str = Field(description="2-3 sentence plot summary of this film in ITALIAN, no spoilers beyond the premise")
    summary_en: str = Field(description="the same 2-3 sentence plot summary in ENGLISH")


class Signals(BaseModel):
    """What the retriever needs from a request, extracted once (same parse for every corpus and strategy)."""
    positive_it: str = Field(description="what the user WANTS, one sentence of plot/theme/atmosphere in ITALIAN. Never contains what is to be avoided "
                                         "and never says 'like X': describe the themes, situation and tone of X in plain words")
    positive_en: str = Field(description="the same sentence in ENGLISH")
    like_titles: list[TitleRef] = Field(default_factory=list, description="films cited as references of closeness")
    avoid_titles: list[TitleRef] = Field(default_factory=list, description="films cited as things to avoid / excluded (a cited reference that must also be excluded goes in like_titles only)")
    avoid_franchise_names: list[str] = Field(default_factory=list, description="franchises/sagas to exclude entirely (e.g. 'Alien', 'Matrix', 'Hannibal Lecter'); original names")
    avoid_descriptions_it: list[str] = Field(default_factory=list, description="narrative traits to avoid, each written POSITIVELY as what the unwanted film shows, in ITALIAN, "
                                                                               "never negated ('possessioni demoniache e esorcismi', not 'senza possessioni')")
    avoid_descriptions_en: list[str] = Field(default_factory=list, description="the same traits, same order, in ENGLISH")
    avoid_genres: list[str] = Field(default_factory=list, description="film genres/subgenres to exclude, one or two words in ENGLISH (e.g. 'horror', 'war', 'romance', 'zombie')")
    keep_genres: list[str] = Field(default_factory=list, description="film genres the user wants, one or two words in ENGLISH")
    avoid_genres_it: list[str] = Field(default_factory=list, description="the same genres as they are named by Italian Wikipedia (e.g. 'horror', 'guerra', 'zombie', 'romantico', 'splatter')")
    keep_genres_it: list[str] = Field(default_factory=list, description="the genres to keep, as named by Italian Wikipedia")
    avoid_formats: list[str] = Field(default_factory=list, description="formats to exclude among: series, short, animated, tv_film, documentary (only if the user says so)")
    year_from: int | None = None
    year_to: int | None = None
    countries: list[str] = Field(default_factory=list, description="requested production countries, in ITALIAN")
    directors: list[str] = Field(default_factory=list)
    actors: list[str] = Field(default_factory=list)
    rare_terms: list[str] = Field(default_factory=list, description="concrete words that must appear in the plot (a character name, place, object); [] for thematic requests")
    contradictory: bool = Field(default=False, description="true if part of the request contradicts another part and cannot be satisfied as asked")
    contradiction_note: str = Field(default="", description="in ITALIAN: which parts contradict, and which coherent part can be served")
    requested_count: int | None = None
