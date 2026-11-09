"""What the LLM parser extracts from a request (`SeriesSignals`), its instructions and the plain-request fallback."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .constants import SUBTYPES

class SeriesSignals(BaseModel):
    """What the retriever needs from a request about TV series, extracted by one LLM call."""
    level: Literal["series", "season", "episode", "tv_movie"] = Field(
        default="series", description="what the user is looking for: a whole TV series (default), a season, a single EPISODE (a scene or event of an episode), or a TV movie")
    positive_it: str = Field(description="what the user WANTS, one sentence of premise/plot/theme/atmosphere in ITALIAN; never what is to be avoided, never 'like X'")
    positive_en: str = Field(description="the same sentence in ENGLISH")
    series_title: str | None = Field(default=None, description="title of a NAMED series the request is about (to look inside it: its episodes or seasons), as written by the user")
    series_title_original: str | None = Field(default=None, description="original/English title of that series if you know it")
    season_number: int | None = None
    episode_number: int | None = None
    subtypes: list[str] = Field(default_factory=list, description=f"only if explicit, among: {', '.join(SUBTYPES)}")
    about_manga_or_original_work: bool = Field(default=False, description="true only if the user asks about manga/comics/the original work of an anime or franchise")
    year_from: int | None = None
    year_to: int | None = None
    countries: list[str] = Field(default_factory=list, description="production countries in ITALIAN, only if explicit")
    cast_names: list[str] = Field(default_factory=list, description="actors/voice actors named by the user")
    creator_names: list[str] = Field(default_factory=list, description="creators/directors named by the user")
    rare_terms: list[str] = Field(default_factory=list, description="single ITALIAN words of the plot that the user states verbatim: a character name, a place, an object. Never a phrase, never a theme, never translated; [] for thematic requests")
    list_children: bool = Field(default=False, description="true when the user asks for the LIST of the episodes (or seasons) of a named series/season, not for a scene")
    avoid_descriptions_it: list[str] = Field(default_factory=list, description="traits to avoid, each written POSITIVELY as what the unwanted series shows, in ITALIAN")
    avoid_titles: list[str] = Field(default_factory=list, description="series/TV movies named as things to avoid or already known (not references)")
    like_titles: list[str] = Field(default_factory=list, description="series cited as references of closeness")
    contradictory: bool = False
    contradiction_note: str = ""
    requested_count: int | None = None


INSTRUCTIONS = """You are the query parser of a TV-series search engine over Italian Wikipedia (series, seasons, single episodes with their plots, TV movies).
The user writes in any language; write the Italian fields in Italian. Fill the schema.
- level: "series" unless the user clearly looks for a single episode ("l'episodio in cui…", "quella puntata dove…"), a season, or a TV movie ("film TV").
- positive_it / positive_en: ONE sentence describing what is WANTED (premise, setting, themes, atmosphere, the scene of the episode). Never negations;
  for a cited reference series describe its themes, not "simile a X".
- series_title: when the request is about a NAMED series (or TV movie): either to look it up itself ("parlami di Lost", "dov'è la pagina di X") or to look inside it (its episodes, a season).
  A request like "serie come Dark" has like_titles=["Dark"], not series_title.
- avoid_descriptions_it: traits to avoid, written positively (what the unwanted series shows). avoid_titles: series to leave out.
- level "episode" also when the user asks which episodes a season has (with list_children=true, season_number if given); level "season" only for the season as a whole (its premise, its plot).
- year/countries/cast_names/creator_names/subtypes only when explicit. rare_terms: ONLY single Italian words that the user states verbatim and that must appear in the plot (a character name, a place, an object); never a phrase, never a theme, never a translation; empty for thematic requests (most requests).
- contradictory=true only if two demands cannot both be met by any series.
Return JSON only."""




def fallback(question: str) -> SeriesSignals:
    return SeriesSignals(positive_it=question, positive_en=question)
