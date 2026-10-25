"""Output channels and how the app knows which one to use.

The channel is declared explicitly by the entry point that received the input,
because it is the only place that really knows where the input came from:

- `python app.py` runs `if __name__ == "__main__": main()`; `main()` reads the
  query with `input()` from the terminal and passes `OutputChannel.terminal`.
- The FastAPI server (`web_api/`) imports `app.handle_query` (so `__name__` is not
  "__main__"), receives the query in the HTTP request and uses the web channel
  (`WebObserver` live, `present(turn, OutputChannel.web)` at the end).

Guessing with `sys.stdin.isatty()` (True when stdin is an interactive terminal) is
deliberately avoided: it is False with pipes (`echo "..." | python app.py`), in
Docker without `-t`, in some IDE runners and in tests.
"""
from __future__ import annotations

from enum import Enum


class OutputChannel(str, Enum):
    terminal = "terminal"
    web = "web"
