from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from turn import TOOL_PARAM_TURN_LANGUAGE

from .auth import YoutubeCredentials, load_credentials
from .config import YoutubeConfig
from .errors import (
    YoutubeApiNotEnabled,
    YoutubeAuthError,
    YoutubeConfigError,
    YoutubeError,
    YoutubeQuotaExceeded,
    YoutubeRateLimited,
)
from .http import HttpSession, Transport, get_json, urllib_transport
from .models import KindOutcome, VideoHit, VideoKind, YoutubeToolInput, describe_validation_errors
from .queries import build_search_params
from .quota import QuotaBucket, QuotaLatch
from .relevance import parse_duration, prescreen, screen, screen_details
from .settings import DESCRIPTION_EXCERPT_CHARS, NOTE_REGION, VIDEO_IDS_MAX, WATCH_URL
from .trace import build_youtube_trace

YOUTUBE_TOOL_NAME = "youtube_search"

_DESCRIPTION = (
    "Search YouTube (official Data API) for videos about one identified film: interviews with "
    "the director (director_interview) or with the cast (cast_interview), making-of, behind the "
    "scenes and featurettes, the authors' "
    "commentary. Trailers only when the user explicitly asks for YouTube or accepts searching "
    "there; otherwise trailers come from tmdb_search. Fill `title` and `kinds` (1-3, most "
    "important first; only the first ones are searched in a turn); fill `year`, `director`, "
    "`cast` and `alternative_titles` only with values from the user or the conversation, never "
    "invented. "
    "Results are YouTube search results: not verified as official and not linked to a film ID."
)

_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
# Errors that would fail again for every other kind of the same run: the kinds left are
# not searched (no useless calls). Quota and rate limits also pause later runs (quota.py);
# key and API errors do not, as they do not consume quota.
_RUN_STOPPING = frozenset(
    {YoutubeQuotaExceeded.code, YoutubeRateLimited.code, YoutubeAuthError.code, YoutubeApiNotEnabled.code}
)
TURN_LIMIT = "turn_limit"


def _failure(query: str, error: str, **details: Any) -> dict[str, Any]:
    return {
        "query": query,
        "chunks": [],
        "metadata": {"youtube": {"status": "error", "error": error, **details}},
        # No step: nothing was called.
        "trace": [],
    }


@dataclass
class _Candidate:
    video_id: str
    title: str
    channel: str
    description: str
    published_at: str | None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _search_candidates(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], int, int]:
    """(videos, returned, invalid IDs) from a `search.list` answer, in API order."""
    items = [item for item in payload.get("items") or [] if isinstance(item, dict)]
    videos, invalid = [], 0
    for item in items:
        ident = item.get("id") if isinstance(item.get("id"), dict) else {}
        video_id = ident.get("videoId")
        if not isinstance(video_id, str) or not _VIDEO_ID.match(video_id):
            invalid += 1
            continue
        snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
        videos.append({"video_id": video_id, **snippet})
    return videos, len(items), invalid


def _details(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {}
    for item in payload.get("items") or []:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
            content = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
            rows[item["id"]] = {"snippet": snippet, "content": content}
    return rows


def _region_note(content: dict[str, Any]) -> str | None:
    restriction = content.get("regionRestriction")
    if not isinstance(restriction, dict):
        return None
    blocked = restriction.get("blocked") or []
    allowed = restriction.get("allowed")
    if NOTE_REGION in blocked or (isinstance(allowed, list) and NOTE_REGION not in allowed):
        return f"blocked_in:{NOTE_REGION}"
    return None


def _count(counts: dict[str, int], reason: str) -> None:
    counts[reason] = counts.get(reason, 0) + 1


def overall_status(outcomes: list[KindOutcome]) -> str:
    searched_ok = [o for o in outcomes if o.status == "searched" and o.result in ("ok", "empty")]
    if not searched_ok:
        return "error"
    complete = len(searched_ok) == len(outcomes)
    if any(o.hits for o in searched_ok):
        return "ok" if complete else "partial"
    return "empty" if complete else "partial"


@dataclass
class _Run:
    """One tool run: searches, one `/videos` lookup, relevance filter, outcomes.

    The search snippet only drops what its title already proves (`prescreen`); anchors,
    homonyms and kind are decided after `/videos`, on the full description, or on the
    snippet when `/videos` could not be read.
    """

    config: YoutubeConfig
    session: HttpSession
    request: YoutubeToolInput
    outcomes: list[KindOutcome] = field(default_factory=list)
    queries: dict[str, str] = field(default_factory=dict)
    candidates: dict[VideoKind, list[_Candidate]] = field(default_factory=dict)
    details_error: str | None = None

    def search(self) -> None:
        limit = self.config.max_searches_per_turn
        stop: str | None = None
        for position, kind in enumerate(self.request.kinds):
            if position >= limit:
                self.outcomes.append(KindOutcome(kind=kind, status="not_searched", reason=TURN_LIMIT))
                continue
            stop = stop or self.session.latch.blocked(QuotaBucket.search)
            if stop:
                self.outcomes.append(KindOutcome(kind=kind, status="not_searched", reason=stop))
                continue
            params = build_search_params(self.request, kind, max_results=self.config.max_results)
            self.queries[kind.value] = params["q"]
            outcome = KindOutcome(kind=kind, status="searched")
            self.outcomes.append(outcome)
            try:
                payload = get_json(self.session, "/search", params)
            except YoutubeError as exc:
                outcome.result, outcome.error = "error", exc.code
                if exc.code in _RUN_STOPPING:
                    stop = exc.code
                continue
            videos, outcome.returned, invalid = _search_candidates(payload)
            if invalid:
                outcome.filtered_out["invalid_id"] = invalid
            kept: list[_Candidate] = []
            for video in videos:
                dropped = prescreen(self.request, title=_text(video.get("title")))
                if dropped is not None:
                    _count(outcome.filtered_out, dropped.reason or "filtered")
                    continue
                kept.append(
                    _Candidate(
                        video_id=video["video_id"],
                        title=_text(video.get("title")),
                        channel=_text(video.get("channelTitle")),
                        description=_text(video.get("description")),
                        published_at=_text(video.get("publishedAt")) or None,
                    )
                )
            self.candidates[kind] = kept

    def lookup(self) -> tuple[dict[str, dict[str, Any]], set[str]]:
        ids = list(dict.fromkeys(c.video_id for kept in self.candidates.values() for c in kept))[:VIDEO_IDS_MAX]
        if not ids:
            return {}, set()
        params = {"part": "snippet,contentDetails", "id": ",".join(ids), "maxResults": str(len(ids))}
        try:
            return _details(get_json(self.session, "/videos", params)), set(ids)
        except YoutubeError as exc:
            self.details_error = exc.code
            return {}, set()

    def finish(self, details: dict[str, dict[str, Any]], looked_up: set[str]) -> None:
        # A video shown for an earlier kind is not repeated for a later one.
        shown: set[str] = set()
        for outcome in self.outcomes:
            if outcome.status != "searched" or outcome.result == "error":
                continue
            for candidate in self.candidates.get(outcome.kind, []):
                if len(outcome.hits) >= self.config.max_results:
                    break
                if candidate.video_id in shown:
                    _count(outcome.filtered_out, "duplicate_of_other_kind")
                    continue
                hit = self._hit(outcome, candidate, details, looked_up)
                if hit is not None:
                    outcome.hits.append(hit)
                    shown.add(hit.video_id)
            outcome.result = "ok" if outcome.hits else "empty"

    def _hit(
        self,
        outcome: KindOutcome,
        candidate: _Candidate,
        details: dict[str, dict[str, Any]],
        looked_up: set[str],
    ) -> VideoHit | None:
        row = details.get(candidate.video_id)
        if row is None and candidate.video_id in looked_up:
            # `/videos` answered without it: removed or private since the search.
            _count(outcome.filtered_out, "unavailable")
            return None
        notes: list[str] = []
        if row is not None:
            snippet, content = row["snippet"], row["content"]
            title = _text(snippet.get("title")) or html.unescape(candidate.title)
            channel = _text(snippet.get("channelTitle")) or html.unescape(candidate.channel)
            description = _text(snippet.get("description")) or html.unescape(candidate.description)
            duration = parse_duration(_text(content.get("duration")))
            region = _region_note(content)
        else:
            # The search snippet escapes HTML: decoded, nothing else changed.
            title = html.unescape(candidate.title)
            channel = html.unescape(candidate.channel)
            description = html.unescape(candidate.description)
            duration, region = None, None
            notes.append("title_from_search")
        screening = screen(
            self.request,
            outcome.kind,
            title=title,
            description=description,
            published_at=candidate.published_at,
        )
        screening = screen_details(
            screening,
            outcome.kind,
            title=title,
            description=description,
            duration_seconds=duration,
        )
        if not screening.kept:
            _count(outcome.filtered_out, screening.reason or "filtered")
            return None
        notes = [*screening.notes, *notes, *([region] if region else [])]
        return VideoHit(
            video_id=candidate.video_id,
            url=WATCH_URL.format(candidate.video_id),
            title=title,
            channel=channel,
            published_at=candidate.published_at,
            description_excerpt=description[:DESCRIPTION_EXCERPT_CHARS] or None,
            duration_seconds=duration,
            matched_on=list(screening.matched_on),
            notes=notes,
        )


@dataclass(kw_only=True)
class YoutubeTool:
    """Read-only YouTube tool: typed input, constant queries, one search per kind, no cache."""

    config: YoutubeConfig
    name: str = YOUTUBE_TOOL_NAME
    description: str = _DESCRIPTION
    input_schema: dict[str, Any] = field(default_factory=lambda: YoutubeToolInput.model_json_schema())
    # Loaded from `.env` on first use; injected in tests.
    credentials: YoutubeCredentials | None = None
    transport: Transport = urllib_transport
    # Shared across the turns of this tool (one tool per app); forgotten on restart.
    latch: QuotaLatch = field(default_factory=QuotaLatch)

    def _credentials(self) -> YoutubeCredentials:
        if self.credentials is None:
            self.credentials = load_credentials()
        return self.credentials

    def run(
        self,
        *,
        query: str,
        params: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        arguments = dict(params or {})
        # Searches are not restricted by language: the turn language is not used.
        arguments.pop(TOOL_PARAM_TURN_LANGUAGE, None)
        if query:
            arguments["query"] = query
        try:
            request = YoutubeToolInput.model_validate(arguments)
        except ValidationError as exc:
            return _failure(query, "invalid_request", errors=describe_validation_errors(exc))
        try:
            credentials = self._credentials()
        except YoutubeConfigError as exc:
            return _failure(request.query, exc.code, detail=str(exc))

        session = HttpSession(credentials=credentials, transport=self.transport, latch=self.latch)
        run = _Run(config=self.config, session=session, request=request)
        run.search()
        run.finish(*run.lookup())

        metadata: dict[str, Any] = {
            "status": overall_status(run.outcomes),
            "source": "YouTube",
            "kinds": [outcome.model_dump(mode="json") for outcome in run.outcomes],
            "not_searched": [o.kind.value for o in run.outcomes if o.status == "not_searched"],
        }
        if run.details_error:
            metadata["details_error"] = run.details_error
        paused = None
        if self.latch.blocked(QuotaBucket.search) == YoutubeQuotaExceeded.code:
            paused = self.latch.paused_until(QuotaBucket.search)
        return {
            "query": request.query,
            # Everything is in metadata (all of it reaches the prompt, URLs included).
            "chunks": [],
            "metadata": {"youtube": metadata},
            # Outside "metadata": the orchestrator puts metadata in the LLM prompt.
            "trace": build_youtube_trace(session.recorder.calls, run.outcomes, run.queries, quota_paused_until=paused),
        }
