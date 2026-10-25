"""Web output channel: the JSON form of a turn (`to_payload`) and its live events (`WebObserver`)."""

from .observer import WebObserver
from .payload import to_payload

__all__ = ["WebObserver", "to_payload"]
