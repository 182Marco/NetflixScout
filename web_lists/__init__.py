"""Web-only lists: the bot's answer grouped in themed lists of TMDb titles and YouTube videos.

The terminal never imports this package. The web entry point calls, after the turn:

    turn = handle_query(app, query, history, final_output=final_output())
    payload = attach_lists(to_payload(turn), turn)
"""
from .attach_lists import attach_lists
from .final_output import final_output

__all__ = ["attach_lists", "final_output"]
