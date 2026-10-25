from __future__ import annotations

import itertools
import json
import random

import pytest

from answer_stream import AnswerFieldStream

ANSWER = 'Ecco "Blade Runner" (1982)\n\tè\\bello/ 🎬 — ok'
DOCUMENT = json.dumps({"answer": ANSWER, "lists": [{"quote": 'a "answer" b', "id": 1}]})
ASCII_DOCUMENT = json.dumps({"answer": ANSWER, "lists": []}, ensure_ascii=True)  # \u escapes + surrogates


def _decode(chunks: list[str]) -> tuple[str, AnswerFieldStream, list[str]]:
    stream = AnswerFieldStream("answer")
    pieces = [stream.feed(chunk) for chunk in chunks]
    return "".join(pieces), stream, pieces


def _splits(text: str, cuts: tuple[int, ...]) -> list[str]:
    points = [0, *cuts, len(text)]
    return [text[a:b] for a, b in zip(points, points[1:])]


def _assert_clean(pieces: list[str]) -> None:
    for piece in pieces:
        assert "\\" not in piece or "\\" in ANSWER
        assert "�" not in piece
        assert not any(0xD800 <= ord(char) < 0xE000 for char in piece)


@pytest.mark.parametrize("document", [DOCUMENT, ASCII_DOCUMENT])
def test_every_single_and_double_cut_decodes_the_same_answer(document: str) -> None:
    for cut in range(len(document) + 1):
        text, stream, pieces = _decode(_splits(document, (cut,)))
        assert text == ANSWER and stream.done and not stream.failed
        _assert_clean(pieces)
    for a, b in itertools.combinations(range(0, len(document), 3), 2):
        text, stream, _ = _decode(_splits(document, (a, b)))
        assert text == ANSWER and stream.done


@pytest.mark.parametrize("document", [DOCUMENT, ASCII_DOCUMENT])
def test_one_character_chunks_and_random_chunking(document: str) -> None:
    assert _decode(list(document))[0] == ANSWER
    rng = random.Random(7)
    for _ in range(200):
        cuts = tuple(sorted(rng.sample(range(1, len(document)), rng.randint(1, 8))))
        text, _, pieces = _decode(_splits(document, cuts))
        assert text == ANSWER
        _assert_clean(pieces)


def test_split_escape_and_surrogate_pair_are_held_back() -> None:
    stream = AnswerFieldStream("answer")
    assert stream.feed('{"answer":"a\\') == "a"
    assert stream.feed("u00") == ""
    assert stream.feed("e8") == "è"
    assert stream.feed("\\uD83C") == ""  # high surrogate waits for its pair
    assert stream.feed("\\uDFAC") == "🎬"
    assert stream.feed('b"}') == "b"
    assert stream.done and stream.emitted == "aè🎬b"


@pytest.mark.parametrize(
    "document",
    [
        '{"answer":"\\uD83Cx"}',  # high surrogate without the low one
        '{"answer":"\\uD83C\\n"}',
        '{"answer":"\\uD83C"}',  # high surrogate then the closing quote
        '{"answer":"\\uDFAC"}',  # lone low surrogate
        '{"answer":"\\uD83C\\uD83C"}',
        '{"answer":"\\q"}',
        '{"answer":"\\u12G4"}',
        '{"answer":"a\nb"}',  # unescaped control character
        '{"answer":42}',
        '{"answer":null}',
        '{"lists":[]}',  # object without the field
        'x{"answer":"a"}',
        '"answer"',
        '{"answer" "a"}',
    ],
)
def test_malformed_json_fails_without_repairing(document: str) -> None:
    text, stream, pieces = _decode([document])
    assert stream.failed and not stream.done
    assert "�" not in text and not any(0xD800 <= ord(char) < 0xE000 for char in text)
    assert stream.feed("more text") == ""  # nothing is emitted after a failure


def test_failure_keeps_the_text_already_emitted() -> None:
    stream = AnswerFieldStream("answer")
    assert stream.feed('{"answer":"Buon') == "Buon"
    assert stream.feed("giorno \\q") == "giorno "
    assert stream.failed and stream.emitted == "Buongiorno "


def test_truncated_stream_emits_only_complete_units() -> None:
    for truncated, expected in [
        ('{"answer":"abc\\u00e', "abc"),
        ('{"answer":"abc\\', "abc"),
        ('{"answer":"abc\\uD83C', "abc"),
        ('{"answer":"abc\\uD83C\\uDF', "abc"),
        ('{"answer":"abc', "abc"),
    ]:
        text, stream, _ = _decode([truncated])
        assert text == expected and not stream.done and not stream.failed


def test_lists_before_answer_and_field_name_inside_other_strings() -> None:
    document = json.dumps({"lists": [{"quote": '"answer": "x"', "n": [1, {"a": "}"}]}], "other": 1.5, "answer": "ok"})
    for cut in range(len(document) + 1):
        text, stream, _ = _decode(_splits(document, (cut,)))
        assert text == "ok" and stream.done


def test_chunks_after_done_are_ignored() -> None:
    stream = AnswerFieldStream("answer")
    assert stream.feed('{"answer":"ab"') == "ab"
    assert stream.done
    assert stream.feed(',"lists":[]}') == ""
    assert stream.emitted == "ab"


def test_whitespace_around_the_structure_is_accepted() -> None:
    text, stream, _ = _decode([' \n{ "lists" : [ ] , "answer" :  "a b" }'])
    assert text == "a b" and stream.done


def test_fragments_never_hold_json_syntax_for_a_plain_answer() -> None:
    plain = json.dumps({"answer": "Ti consiglio Alien.", "lists": []})
    _, _, pieces = _decode(_splits(plain, (3, 11, 14, 25)))
    assert all("{" not in p and '"' not in p and "\\" not in p for p in pieces)
