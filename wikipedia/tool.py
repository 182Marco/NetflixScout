from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from turn import (
    OUTCOME_EMPTY,
    OUTCOME_ERROR,
    OUTCOME_OK,
    RESULT_FOLLOW_UP,
    TOOL_PARAM_TURN_ID,
    TOOL_PARAM_TURN_LANGUAGE,
    tool_outcome,
)

from .budget import PageKey, TurnRegistry, TurnState
from .config import WikipediaConfig
from .errors import WikipediaError, WikipediaRateLimited
from .http import HttpSession, RateLimitPause, Transport, TtlCache, get_json, urllib_transport
from .models import (
    Depth,
    PageHit,
    PageResult,
    Section,
    WikipediaToolInput,
    describe_validation_errors,
    normalize_text,
)
from .queries import article_params, lookup_params, search_term
from .relevance import (
    Screened,
    follow_up_reasons,
    keywords_mostly_absent,
    lookup_hints,
    match_title,
    screen_pages,
    verification,
)
from .sections import (
    clean_extract,
    keyword_report,
    lead_title,
    outline,
    scoring_terms,
    select_sections,
    split_sections,
)
from .settings import LANGUAGES, MIN_FOLLOW_UP_CHARS

MAX_CANDIDATES_LISTED = 5
from .trace import build_planner_summary, build_wikipedia_trace

WIKIPEDIA_TOOL_NAME = "wikipedia_search"

_DESCRIPTION = (
    "Read Wikipedia (MediaWiki API) for encyclopedic information about one person, film or cinema "
    "topic: in-depth biographies and careers, history, production, reception, influences, movements. "
    "Not for cast and crew lists, release dates, plots, ratings or streaming (tmdb_search) nor for "
    "videos (youtube_search). Fill `topic` and `kind`; `depth`: intro (lead of the best pages, simple "
    "facts), sections (some sections of one page), full (the whole article of one page, most relevant "
    "sections first). The result says which sections it returned and which it left out (`outline`, "
    "`omitted`): to read more, call again with `page` and `sections` (or depth full), or search "
    "another topic. `year`, `language`, `page` and `sections` only with values from the user or from "
    "an earlier result of this tool, never invented. Text is community-written (CC BY-SA), not verified."
)


def planner_schema() -> dict[str, Any]:
    """`WikipediaToolInput` JSON schema for the planner catalog, without the class docstring (the
    tool `description` already says what the tool does). Validation uses the model, not this dict."""
    schema = WikipediaToolInput.model_json_schema()
    schema.pop("description", None)
    return schema


def _failure(query: str, error: str, **details: Any) -> dict[str, Any]:
    return {
        "query": query,
        "chunks": [],
        "outcome": tool_outcome(OUTCOME_ERROR, error),
        "metadata": {"wikipedia": {"status": "error", "error": error, **details}},
        # No step: nothing was called.
        "trace": [],
    }


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def parse_pages(payload: dict[str, Any], language: str) -> list[PageHit]:
    """Pages of a `query` answer that exist, with the extract cleaned; anything malformed is skipped."""
    query = payload.get("query")
    rows = query.get("pages") if isinstance(query, dict) else None
    hits = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("missing") or row.get("invalid"):
            continue
        title = _text(row.get("title")).strip()
        if not title:
            continue
        props = row.get("pageprops")
        index = row.get("index")
        hits.append(
            PageHit(
                pageid=row.get("pageid") if isinstance(row.get("pageid"), int) else None,
                title=title,
                language=language,
                index=index if isinstance(index, int) else 0,
                extract=clean_extract(_text(row.get("extract"))),
                disambiguation=isinstance(props, dict) and "disambiguation" in props,
                touched=_text(row.get("touched")) or None,
            )
        )
    return hits


@dataclass
class _Run:
    """One tool run: lookup or opening of an article, selection of the text to hand out."""

    config: WikipediaConfig
    session: HttpSession
    request: WikipediaToolInput
    # The one edition this run asks: the planner's choice, else `default_language`. The other
    # edition is never tried here; a later step asks for it if the planner decides to.
    edition: str
    searches: list[dict[str, Any]] = field(default_factory=list)
    opens: list[dict[str, Any]] = field(default_factory=list)
    pages: list[PageResult] = field(default_factory=list)
    kept: list[Screened] = field(default_factory=list)
    dropped: dict[str, int] = field(default_factory=dict)
    searched_ok: bool = False
    budget_hit: bool = False
    error: str | None = None
    # Pages found by a search for `sections`/`full` but not opened, none being certain enough.
    candidates: list[dict[str, Any]] = field(default_factory=list)

    @property
    def state(self) -> TurnState:
        return self.session.state

    def context_left(self) -> int:
        return self.state.context_left(self.config.context_chars_per_turn)

    # --- lookup -----------------------------------------------------------------------------

    def _lookup(self, language: str) -> bool:
        """Search one edition. False when the request failed (the run then stops searching)."""
        row: dict[str, Any] = {
            "language": language, "q": search_term(self.request), "result": None, "error": None,
            "returned": 0, "kept": 0, "filtered_out": {},
        }
        self.searches.append(row)
        self.state.languages_tried.add(language)
        try:
            payload = get_json(self.session, language, lookup_params(self.request, max_results=self.config.max_results))
        except WikipediaError as exc:
            row["result"], row["error"], self.error = "error", exc.code, exc.code
            return False
        pages = parse_pages(payload, language)
        kept, dropped = screen_pages(self.request, pages)
        self.searched_ok = True
        self.kept, self.dropped = kept[: self.config.max_results], dropped
        row.update(result="ok" if kept else "empty", returned=len(pages), kept=len(self.kept), filtered_out=dropped)
        return True

    # --- delivery ---------------------------------------------------------------------------

    def _deliver(
        self,
        *,
        key: PageKey,
        sections: list[Section],
        depth: str,
        wanted: list[str],
        whole_article: bool,
        screened: tuple[str, list[str]],
        touched: str | None,
    ) -> None:
        language, title = key
        delivered = self.state.delivered_for(key)
        selection = select_sections(
            sections,
            depth=depth,
            wanted=wanted,
            terms=scoring_terms(self.request.keywords, self.request.query, self.request.topic),
            already=delivered,
            budget=self.context_left(),
            language=language,
        )
        chars = sum(len(item.text) for item in selection.delivered)
        self.state.context_used += chars
        delivered.update(normalize_text(item.section.title) for item in selection.delivered if not item.truncated)
        self.budget_hit = self.budget_hit or selection.budget_hit
        self.pages.append(
            PageResult(
                title=title,
                language=language,
                verification=screened[0],
                notes=screened[1],
                last_revised=touched,
                total_chars=sum(section.chars for section in sections) if whole_article else None,
                delivered_chars=chars,
                sections=[item.section.title for item in selection.delivered],
                outline=outline(sections, delivered, language) if whole_article else None,
                omitted=[{"title": s.title, "chars": s.chars} for s in selection.omitted] if whole_article else [],
                unknown_sections=list(selection.unknown),
                truncated=any(item.truncated for item in selection.delivered),
                keywords=(
                    keyword_report(self.request.keywords, sections, delivered, whole_article=whole_article)
                    if self.request.keywords
                    else None
                ),
                text=[{"section": item.section.title, "text": item.text} for item in selection.delivered],
            )
        )

    def _deliver_leads(self, language: str) -> None:
        for row in self.kept:
            page = row.page
            lead = [Section(title=lead_title(language), level=1, text=page.extract)]
            self._deliver(
                key=(language, page.title), sections=lead, depth="intro", wanted=[], whole_article=False,
                screened=(row.verification, row.notes), touched=page.touched,
            )

    def _open(self, language: str, title: str) -> PageHit | None:
        """Download one article whole (the cache serves a second reading); None if there is none."""
        row: dict[str, Any] = {"language": language, "title": title, "result": None, "error": None}
        self.opens.append(row)
        self.state.languages_tried.add(language)
        try:
            payload = get_json(self.session, language, article_params(title))
        except WikipediaError as exc:
            row["result"], row["error"], self.error = "error", exc.code, exc.code
            return None
        pages = parse_pages(payload, language)
        # The request worked: not finding the page is a result the planner can act on.
        self.searched_ok = True
        if any(page.disambiguation for page in pages):
            self.dropped["disambiguation"] = self.dropped.get("disambiguation", 0) + 1
            row["result"] = "ambiguous"
            return None
        hit = next((page for page in pages if page.extract.strip()), None)
        row["result"] = "ok" if hit else "not_found"
        if hit:
            self.state.opened.add((language, hit.title))
        return hit

    def _deliver_article(self, hit: PageHit, screened: tuple[str, list[str]]) -> None:
        sections = split_sections(hit.extract, hit.language)
        self._deliver(
            key=(hit.language, hit.title),
            sections=sections,
            depth=self.request.depth.value,
            wanted=self.request.sections,
            whole_article=True,
            screened=screened,
            touched=hit.touched,
        )

    def execute(self) -> None:
        request = self.request
        if request.page is not None:
            hit = self._open(self.edition, request.page)
            if hit is not None:
                match = match_title(request.page, hit.title)
                notes = [] if match in ("exact", "qualified") else ["title_partial"]
                self._deliver_article(hit, (verification(notes), notes))
            return
        if not self._lookup(self.edition) or not self.kept:
            return
        if request.depth is Depth.intro:
            self._deliver_leads(self.edition)
            return
        # A whole article is downloaded only for a page whose title is the one asked. Otherwise nothing
        # is downloaded: the candidates are listed and the planner picks one (`page`) or searches again.
        confirmed = next((row for row in self.kept if row.verification == "confirmed"), None)
        if confirmed is None:
            self.candidates = [
                {"title": row.page.title, "language": self.edition, "verification": row.verification}
                for row in self.kept[:MAX_CANDIDATES_LISTED]
            ]
            return
        hit = self._open(self.edition, confirmed.page.title)
        if hit is not None:
            self._deliver_article(hit, (confirmed.verification, confirmed.notes))

    # --- result -----------------------------------------------------------------------------

    def result(self, query: str) -> dict[str, Any]:
        config, state = self.config, self.state
        hints = lookup_hints(self.request, self.kept, self.dropped) if self.searched_ok else []
        untried = [language for language in LANGUAGES if language not in state.languages_tried]
        other_edition = untried[0] if untried else None
        absent = any(keywords_mostly_absent(page.keywords) for page in self.pages)
        reasons = [] if self.error == WikipediaRateLimited.code else follow_up_reasons(
            pages=self.pages,
            searched=self.searched_ok,
            dropped=self.dropped,
            budget_hit=self.budget_hit,
            http_left=state.http_left(config.max_calls_per_turn),
            context_left=self.context_left(),
            other_language_untried=other_edition is not None,
            keywords_absent=absent,
            unopened_candidates=bool(self.candidates),
        )
        if self.pages:
            status = "ok"
        elif self.error:
            status = "error"
        else:
            status = "empty"
        metadata: dict[str, Any] = {
            "status": status,
            "source": "Wikipedia",
            "language": self.edition,
            "context": {
                "used": state.context_used,
                "budget": config.context_chars_per_turn,
                "exhausted": self.context_left() < MIN_FOLLOW_UP_CHARS,
            },
            "calls_left": state.http_left(config.max_calls_per_turn),
            "pages": [
                {
                    "title": page.title,
                    "language": page.language,
                    "verification": page.verification,
                    "notes": page.notes,
                    "total_chars": page.total_chars,
                    "delivered_chars": page.delivered_chars,
                    "sections_delivered": page.sections,
                    "outline": page.outline,
                    "omitted": page.omitted,
                    "unknown_sections": page.unknown_sections,
                    "truncated": page.truncated,
                    "keywords": page.keywords,
                    # Last: the part that grows. The orchestrator shows the planner `follow_up.summary`.
                    "text": page.text,
                }
                for page in self.pages
            ],
            "hints": hints,
        }
        if self.candidates:
            # Titles only: nothing from these pages is a source until one is opened.
            metadata["candidates"] = self.candidates
        if self.dropped.get("not_relevant"):
            metadata["not_relevant"] = self.dropped["not_relevant"]
        if self.error:
            metadata["error"] = self.error
        if status == "error":
            outcome = tool_outcome(OUTCOME_ERROR, self.error)
        else:
            outcome = tool_outcome(OUTCOME_EMPTY if status == "empty" else OUTCOME_OK)
        return {
            "query": query,
            "outcome": outcome,
            # Everything the model reads is in metadata; URLs and the licence are in the trace.
            "chunks": [],
            "metadata": {"wikipedia": metadata},
            "trace": build_wikipedia_trace(self.session.calls, self.session.reused, self.searches, self.opens, self.pages, hints),
            RESULT_FOLLOW_UP: {
                "available": bool(reasons),
                "reasons": reasons,
                "summary": build_planner_summary(
                    self.pages,
                    reasons,
                    context_used=state.context_used,
                    context_budget=config.context_chars_per_turn,
                    calls_left=state.http_left(config.max_calls_per_turn),
                    edition=self.edition,
                    languages_tried=sorted(state.languages_tried),
                    other_edition=other_edition,
                    candidates=self.candidates,
                    dropped=self.dropped,
                ),
            },
        }


@dataclass(kw_only=True)
class WikipediaTool:
    """Read-only Wikipedia tool: typed input, constant requests, whole articles handed out by section."""

    config: WikipediaConfig
    name: str = WIKIPEDIA_TOOL_NAME
    description: str = _DESCRIPTION
    input_schema: dict[str, Any] = field(default_factory=planner_schema)
    transport: Transport = urllib_transport
    # Shared by the turns of this tool (one tool per app): the cache and the pause outlive a run,
    # the registry holds the budgets of the turns being run.
    cache: TtlCache | None = None
    pause: RateLimitPause = field(default_factory=RateLimitPause)
    registry: TurnRegistry = field(default_factory=TurnRegistry)

    def __post_init__(self) -> None:
        if self.cache is None:
            self.cache = TtlCache(self.config.cache_ttl)

    def run(
        self,
        *,
        query: str,
        params: dict[str, Any] | None = None,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        arguments = dict(params or {})
        # The language of the question does not choose the edition (English by default whatever the
        # answer's language): the planner does, with `language`.
        arguments.pop(TOOL_PARAM_TURN_LANGUAGE, None)
        turn_id = arguments.pop(TOOL_PARAM_TURN_ID, None)
        if query:
            arguments["query"] = query
        try:
            request = WikipediaToolInput.model_validate(arguments)
        except ValidationError as exc:
            return _failure(query, "invalid_request", errors=describe_validation_errors(exc))

        assert self.cache is not None
        session = HttpSession(
            transport=self.transport,
            state=self.registry.state(turn_id),
            max_calls=self.config.max_calls_per_turn,
            cache=self.cache,
            pause=self.pause,
        )
        run = _Run(config=self.config, session=session, request=request, edition=request.language or self.config.default_language)
        run.execute()
        return run.result(request.query)
