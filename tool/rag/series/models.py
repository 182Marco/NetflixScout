from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class SeriesRagToolInput(BaseModel):
    """Search TV series, seasons, episodes or TV movies by plot, theme, atmosphere or a named series. Write `query` as the user's whole request."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        min_length=1,
        description=(
            "The user's whole request, wanted and unwanted traits together ('come Dark ma senza viaggi nel tempo'); the tool extracts the level "
            "(series, season, episode, TV movie), the named series, season and episode numbers, years, countries, cast and exclusions itself."
        ),
    )
    k_final: int | None = Field(default=None, ge=1, le=10, description="How many results the user asks for; null if no number is given.")


def describe_validation_errors(exc: ValidationError) -> list[dict[str, str]]:
    """Field and type of each error, never the submitted values."""
    return [{"field": ".".join(str(p) for p in e["loc"]), "type": e["type"]} for e in exc.errors()]
