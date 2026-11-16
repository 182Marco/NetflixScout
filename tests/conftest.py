from __future__ import annotations

import pytest

def pytest_configure(config) -> None:
    config.addinivalue_line(
        "markers", "integration: calls real services (Qdrant server, OpenAI); skipped when the server is down"
    )
    config.addinivalue_line(
        "markers", "qdrant_server: needs a running Qdrant server (QDRANT_URL); skipped otherwise"
    )
