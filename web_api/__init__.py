"""HTTP/SSE exposure of NetflixScout. All FastAPI, SSE and conversation-state code lives here;
the rest of the repository does not import this package."""
from .server import create_app

__all__ = ["create_app"]
