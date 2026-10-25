"""Manual check of the streamed structured answer against the real model. ONE call to the LLM.

Not a test and never imported at runtime. It answers what the offline tests cannot: does the model
write `answer` before `lists` in the strict JSON, how big are the deltas, how long until the first
text, and does `AnswerFieldStream` give exactly the answer that `json.loads` gives?

    python -m web_api.harness.live_stream_check --live

Run it only with the owner's go-ahead: it spends one call of `orchestrator.llm_model`.
"""
from __future__ import annotations

import argparse
import json
import time
from typing import Any

from openai import OpenAI

from answer_stream import AnswerFieldStream
from app import CONFIG
from web_lists import final_output

PROMPT = (
    "Consiglia due film di fantascienza anni 80 con una frase ciascuno. Usa il Markdown con una "
    "lista e almeno una virgolette e una lettera accentata. Non hai risultati di tool: nessuna "
    "lista da compilare (`lists` vuoto)."
)


def _key_order(raw: str) -> list[str]:
    return [key for key, _ in json.loads(raw, object_pairs_hook=lambda pairs: pairs)]


def run_check() -> dict[str, Any]:
    spec = final_output()
    decoder = AnswerFieldStream(spec["answer_field"])
    raw: list[str] = []
    shown: list[str] = []
    sizes: list[int] = []
    first_raw = first_text = None
    ended = None
    started = time.monotonic()
    stream = OpenAI().responses.create(
        model=CONFIG["orchestrator"]["llm_model"],
        instructions=spec["instructions"],
        input=[{"role": "user", "content": PROMPT}],
        text={"format": spec["text_format"]},
        stream=True,
    )
    for event in stream:
        if event.type == "response.output_text.delta":
            first_raw = first_raw if first_raw is not None else time.monotonic() - started
            raw.append(event.delta)
            sizes.append(len(event.delta))
            text = decoder.feed(event.delta)
            if text:
                first_text = first_text if first_text is not None else time.monotonic() - started
                shown.append(text)
        elif event.type in ("response.completed", "response.incomplete", "response.failed", "error"):
            ended = event.type
            break
    document = "".join(raw)
    parsed = json.loads(document)
    return {
        "ended": ended,
        "key_order": _key_order(document),
        "answer_first": _key_order(document)[:1] == ["answer"],
        "deltas": len(sizes),
        "delta_chars_min_max": [min(sizes, default=0), max(sizes, default=0)],
        "seconds_to_first_delta": first_raw,
        "seconds_to_first_answer_text": first_text,
        "decoder_equals_json": "".join(shown) == parsed["answer"],
        "decoder_failed": decoder.failed,
        "clean_fragments": not any("\\" in piece or "�" in piece for piece in shown),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="really call the model (one call)")
    if not parser.parse_args().live:
        parser.error("pass --live to spend the call")
    print(json.dumps(run_check(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
