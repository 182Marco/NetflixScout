"""Title normalisation and vector helpers (pure). Identical needs of the two retrievers, so one copy."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

import numpy as np


def norm(text: Any) -> str:
    t = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", t.lower())).strip()


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / (np.linalg.norm(v) or 1.0)
