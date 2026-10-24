"""Root of the strict schema of the final answer call: the answer text and its list references."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from .list_ref import ListRef


class FinalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    lists: list[ListRef]
