"""Terminal blocks of the turn flow shared by every tool: story lines, unknown steps and
the final answer."""
from __future__ import annotations

from turn import StoryLine

from .box import print_box
from .texts import texts

STORY_MARKS = {"progress": "⏳", "info": "💡", "ok": "✅", "warn": "⚠️"}


def print_story_line(line: StoryLine) -> None:
    """One sentence of the turn story; flushed so it shows while the next step runs."""
    print(f"{STORY_MARKS.get(line.level, '•')} {line.text}", flush=True)


def print_generic_step(title: str, data: dict) -> None:
    print_box("⚙️", title)
    for key, value in data.items():
        print(f"  {key}: {value}")


def print_answer_header(language: str = "it") -> None:
    title = f"║  🤖  {texts(language)['answer_title']}"
    print("\n")
    print("╔" + "═" * 68 + "╗")
    print(title + " " * max(69 - len(title) - 1, 1) + "║")
    print("╚" + "═" * 68 + "╝")
    print()


def print_answer_text(text: str) -> None:
    """A piece of the answer, without a newline: the answer is written as it arrives."""
    print(text, end="", flush=True)


def print_answer_end() -> None:
    print("\n")


def print_final_answer(answer: str, language: str = "it") -> None:
    print_answer_header(language)
    print(answer)
    print()


def print_compact_notice(language: str = "it") -> None:
    print(texts(language)["compact"])
