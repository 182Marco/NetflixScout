"""Box header shared by every terminal block, so all tools print the same style."""
from __future__ import annotations


def print_box(emoji: str, title: str) -> None:
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print(f"║  {emoji}  {title.upper():<62}║")
    print("╚" + "═" * 68 + "╝")
