"""Incremental decoder of one string field of a streamed JSON object.

The structured final answer arrives as raw JSON fragments (`{"answer":"Ecco\\n…`), cut at
arbitrary points. `AnswerFieldStream` returns only the text of the `answer` field that is
already fully decoded, so a channel never sees JSON syntax, escapes or half a character.

Contract (see `tests/test_answer_stream.py`):
- A fragment never contains an undecoded escape, a closing quote or any JSON structure. An
  escape cut between two chunks (`\\u00`, a lone `\\`) and a high surrogate waiting for its
  pair are held back, never emitted.
- Anything malformed (bad escape, unescaped control character, unpaired surrogate, value that
  is not a string, text before the object, object without the field) sets `failed`: nothing
  more is emitted, nothing is repaired and nothing is raised. Text already emitted stays valid.
- `done` is set at the closing quote; later chunks are ignored.
"""
from __future__ import annotations

from enum import Enum, auto

_SIMPLE_ESCAPES = {'"': '"', "\\": "\\", "/": "/", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t"}
_HEX = frozenset("0123456789abcdefABCDEF")
_WHITESPACE = frozenset(" \t\r\n")
_HIGH_SURROGATES = range(0xD800, 0xDC00)
_LOW_SURROGATES = range(0xDC00, 0xE000)


class _State(Enum):
    OBJECT = auto()  # waiting for the opening `{`
    KEY_OR_END = auto()  # between members: a key, a comma or the closing `}`
    KEY = auto()  # inside a key
    COLON = auto()  # after a key
    VALUE = auto()  # before the value of the key
    SKIP = auto()  # inside the value of another key
    ANSWER = auto()  # inside the string of the wanted field
    DONE = auto()
    FAILED = auto()


class AnswerFieldStream:
    def __init__(self, field: str) -> None:
        self._field = field
        self._state = _State.OBJECT
        self._key: list[str] = []
        self._key_escaped = False
        # Value skipping: nesting depth, inside a string, previous character was a backslash.
        self._depth = 0
        self._in_string = False
        self._skip_escaped = False
        # Decoding of the wanted string: pending escape ("\\", "\\u", "\\u00e"…) and high surrogate.
        self._escape: str | None = None
        self._high: int | None = None
        self._emitted: list[str] = []

    @property
    def done(self) -> bool:
        return self._state is _State.DONE

    @property
    def failed(self) -> bool:
        return self._state is _State.FAILED

    @property
    def emitted(self) -> str:
        return "".join(self._emitted)

    def feed(self, chunk: str) -> str:
        """The newly decoded text of the field contained in `chunk` ("" when there is none)."""
        out: list[str] = []
        for char in chunk:
            if self._state in (_State.DONE, _State.FAILED):
                break
            self._step(char, out)
        text = "".join(out)
        self._emitted.append(text)
        return text

    def _fail(self) -> None:
        self._state = _State.FAILED

    def _step(self, char: str, out: list[str]) -> None:
        handler = _HANDLERS[self._state]
        handler(self, char, out)

    def _object(self, char: str, out: list[str]) -> None:
        if char in _WHITESPACE:
            return
        if char == "{":
            self._state = _State.KEY_OR_END
        else:
            self._fail()

    def _key_or_end(self, char: str, out: list[str]) -> None:
        if char in _WHITESPACE or char == ",":
            return
        if char == '"':
            self._key, self._key_escaped = [], False
            self._state = _State.KEY
        else:
            self._fail()  # the closing `}` without the field is a failure too

    def _in_key(self, char: str, out: list[str]) -> None:
        if self._key_escaped:
            self._key.append(char)
            self._key_escaped = False
        elif char == "\\":
            self._key_escaped = True
        elif char == '"':
            self._state = _State.COLON
        else:
            self._key.append(char)

    def _colon(self, char: str, out: list[str]) -> None:
        if char in _WHITESPACE:
            return
        if char == ":":
            self._state = _State.VALUE
        else:
            self._fail()

    def _value(self, char: str, out: list[str]) -> None:
        if char in _WHITESPACE:
            return
        if "".join(self._key) == self._field:
            if char == '"':
                self._state = _State.ANSWER
            else:
                self._fail()
            return
        self._state = _State.SKIP
        self._depth, self._in_string, self._skip_escaped = 0, False, False
        self._skip(char, out)

    def _skip(self, char: str, out: list[str]) -> None:
        if self._in_string:
            if self._skip_escaped:
                self._skip_escaped = False
            elif char == "\\":
                self._skip_escaped = True
            elif char == '"':
                self._in_string = False
            return
        if char == '"':
            self._in_string = True
        elif char in "{[":
            self._depth += 1
        elif char in "}]":
            if self._depth == 0:
                self._fail()  # end of the object: the field never came
            else:
                self._depth -= 1
        elif char == "," and self._depth == 0:
            self._state = _State.KEY_OR_END

    def _answer(self, char: str, out: list[str]) -> None:
        if self._escape is not None:
            self._escape_step(char, out)
        elif char == "\\":
            self._escape = "\\"
        elif self._high is not None:
            self._fail()  # a high surrogate must be followed by the `\uDC00` escape of its pair
        elif char == '"':
            self._state = _State.DONE
        elif ord(char) < 0x20 or 0xD800 <= ord(char) < 0xE000:
            self._fail()  # unescaped control character, or a surrogate that is not text
        else:
            out.append(char)

    def _escape_step(self, char: str, out: list[str]) -> None:
        escape = self._escape or ""
        if escape == "\\":
            if char == "u":
                self._escape = "\\u"
            elif char in _SIMPLE_ESCAPES and self._high is None:
                out.append(_SIMPLE_ESCAPES[char])
                self._escape = None
            else:
                self._fail()
            return
        if char not in _HEX:
            self._fail()
            return
        escape += char
        if len(escape) < 6:
            self._escape = escape
            return
        self._escape = None
        self._unit(int(escape[2:], 16), out)

    def _unit(self, code: int, out: list[str]) -> None:
        if code in _HIGH_SURROGATES:
            if self._high is not None:
                self._fail()
            else:
                self._high = code
        elif code in _LOW_SURROGATES:
            if self._high is None:
                self._fail()
            else:
                out.append(chr(0x10000 + ((self._high - 0xD800) << 10) + (code - 0xDC00)))
                self._high = None
        elif self._high is not None:
            self._fail()
        else:
            out.append(chr(code))


_HANDLERS = {
    _State.OBJECT: AnswerFieldStream._object,
    _State.KEY_OR_END: AnswerFieldStream._key_or_end,
    _State.KEY: AnswerFieldStream._in_key,
    _State.COLON: AnswerFieldStream._colon,
    _State.VALUE: AnswerFieldStream._value,
    _State.SKIP: AnswerFieldStream._skip,
    _State.ANSWER: AnswerFieldStream._answer,
}
