"""The ladder: try each polite, free rung in order and stop at the first good answer.

Every rung gets a line in the response, so a caller can see which rung answered and
why each lower rung was skipped or failed. A candidate answer only counts when it
passes the quality check.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from . import blocks, extract, paid, quality, structured
from .blocks import Block
from .browser import Browser
from .guard import Guard, UnsafeURL
from .http_fetch import Fetcher, FetchError, FetchResult, Refused
from .models import RUNGS, RungReport, ScrapeRequest, ScrapeResponse
from .quality import Quality
from .robots import Robots
from .settings import Settings
from .structured import StructuredParse
from .telemetry import Telemetry

WALL_NOTE = "this build doesn't try to get past bot walls"


@dataclass
class Failure:
    status: str  # "refused" or "failed"
    reason: str


@dataclass
class Candidate:
    """What one extraction rung produced from a page."""

    name: str
    status: str
    reason: str
    quality: Quality | None = None


@dataclass
class _Run:
    request: ScrapeRequest
    telemetry: Telemetry = field(default_factory=Telemetry)
    reports: dict[str, RungReport] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    fetched: FetchResult | None = None
    html: str | None = None
    text: str = ""
    fields: dict[str, str | None] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    structured: StructuredParse | None = None
    block: Block | None = None

    def mark(self, name: str, status: str, reason: str, started: float | None = None) -> None:
        ms = int((time.perf_counter() - started) * 1000) if started is not None else 0
        self.reports[name] = RungReport(number=RUNGS.index(name) + 1, name=name, status=status, reason=reason, ms=ms)

    def note(self, *reasons: str) -> None:
        for reason in reasons:
            if reason not in self.reasons:
                self.reasons.append(reason)


class Ladder:
    def __init__(self, settings: Settings, guard: Guard, fetcher: Fetcher, robots: Robots, browser: Browser):
        self.settings = settings
        self.guard = guard
        self.fetcher = fetcher
        self.robots = robots
        self.browser = browser

    async def run(self, request: ScrapeRequest) -> ScrapeResponse:
        run = _Run(request)
        if not request.respect_robots:
            run.warnings.append("robots.txt check turned off by the request")

        # 1. Official source: a known CSV or JSON export named in the request.
        if await self._official_source(run):
            return self._finish(run, "official_source")

        # 2. Plain HTTP fetch behind the internal-address guard.
        started = time.perf_counter()
        got = await self._fetch(request.url, run, purpose="page")
        if isinstance(got, Failure):
            run.mark("http_fetch", got.status, got.reason, started)
            run.note(got.reason)
            return self._stop(run, "http_fetch", got.reason)
        run.fetched = got
        media = got.content_type.split(";", 1)[0].strip() or "no content type"
        kind = structured.kind_of(got.final_url, got.content_type)
        if kind is None:
            run.html = got.text
            run.block = blocks.classify(run.html, got.status, min_text_chars=self.settings.min_text_chars)
        if not 200 <= got.status < 300:
            reason = f"status {got.status}"
            if run.block is not None and run.block.label != "ok":
                reason += f" ({run.block.reason})"
            run.mark("http_fetch", "failed", reason, started)
            run.note(reason)
            return self._stop(run, "http_fetch", reason, wall=bool(run.block and run.block.is_wall))
        if run.block is not None and run.block.is_wall:
            run.mark("http_fetch", "failed", f"{got.status} but {run.block.reason}", started)
            run.note(f"{run.block.label}: {run.block.reason}")
            return self._stop(run, "http_fetch", run.block.reason, wall=True)
        detail = f"{got.status} {media}, {len(got.body)} bytes"
        if got.redirects:
            detail += f", after {len(got.redirects)} redirect(s)"
        if run.block is not None and run.block.label != "ok":
            detail += f"; block check: {run.block.reason}"
        run.mark("http_fetch", "done", detail, started)

        # 3. Structured parse for CSV, JSON and XLSX.
        started = time.perf_counter()
        if kind is not None:
            answered = self._structured(run, got, kind, started)
            if answered:
                return self._finish(run, "structured_parse")
            return self._stop(run, "structured_parse", "the response wasn't an HTML page")
        run.mark("structured_parse", "skipped", f"the response is {media}, not CSV, JSON or XLSX", started)

        # 4-6. Page metadata, selectors, main text: no network, cheapest first.
        for candidate in self._html_rungs(run, run.html or "", got.final_url, got.status, run.block):
            run.mark(candidate.name, candidate.status, candidate.reason)
            if candidate.quality is not None and not candidate.quality.passed:
                run.note(*candidate.quality.reasons)
            if candidate.status == "answered":
                return self._finish(run, candidate.name)

        # 7. Headless browser, only when installed.
        if await self._headless_browser(run, got.final_url):
            return self._finish(run, "headless_browser")
        return self._finish(run, None)

    # ------------------------------------------------------------------ rungs

    async def _official_source(self, run: _Run) -> bool:
        started = time.perf_counter()
        url = run.request.export_url
        if not url:
            run.mark("official_source", "skipped", "no export_url in the request")
            return False
        got = await self._fetch(url, run, purpose="export")
        if isinstance(got, Failure):
            run.mark("official_source", got.status, got.reason, started)
            return False
        kind = structured.kind_of(got.final_url, got.content_type)
        if not 200 <= got.status < 300:
            run.mark("official_source", "failed", f"export answered {got.status}", started)
        elif kind is None:
            run.mark("official_source", "failed", "the export isn't CSV, JSON or XLSX", started)
        else:
            try:
                parsed = structured.parse(got.body, kind)
            except Exception as exc:  # noqa: BLE001 - a broken export is a failed rung
                run.mark("official_source", "failed", f"couldn't parse the {kind} export ({type(exc).__name__})", started)
                return False
            check = quality.check(status=got.status, block=None, rows=parsed.row_count)
            if check.passed:
                run.structured = parsed
                run.fetched = got
                run.mark("official_source", "answered", f"{kind} export with {parsed.row_count} rows", started)
                return True
            run.mark("official_source", "failed", "; ".join(check.reasons), started)
        return False

    def _structured(self, run: _Run, got: FetchResult, kind: str, started: float) -> bool:
        try:
            parsed = structured.parse(got.body, kind)
        except Exception as exc:  # noqa: BLE001
            reason = f"couldn't parse the {kind} ({type(exc).__name__})"
            run.mark("structured_parse", "failed", reason, started)
            run.note(reason)
            return False
        run.structured = parsed
        check = quality.check(status=got.status, block=None, rows=parsed.row_count)
        if check.passed:
            run.mark("structured_parse", "answered", f"{kind} with {parsed.row_count} rows", started)
            return True
        run.mark("structured_parse", "failed", "; ".join(check.reasons), started)
        run.note(*check.reasons)
        return False

    def _html_rungs(self, run: _Run, html: str, url: str, status: int | None, block: Block | None) -> list[Candidate]:
        """Run rungs 4-6 on one page, in order, up to the first that answers."""
        out: list[Candidate] = []
        request = run.request
        min_chars = self.settings.min_text_chars

        run.metadata = extract.page_metadata(html, url)
        items = extract.typed_items(run.metadata)
        if request.selectors:
            out.append(Candidate("page_metadata", "skipped", "the request names selectors, so metadata alone doesn't answer"))
        elif items:
            check = quality.check(status=status, block=block, items=len(items))
            types = ", ".join(sorted({str(i["@type"]) for i in items}))
            if check.passed:
                out.append(Candidate("page_metadata", "answered", f"{len(items)} typed item(s): {types}", check))
                return out
            out.append(Candidate("page_metadata", "failed", "; ".join(check.reasons), check))
        else:
            extra = " (OpenGraph tags kept)" if run.metadata.get("opengraph") else ""
            out.append(Candidate("page_metadata", "skipped", f"no typed JSON-LD or microdata item on the page{extra}"))

        if not request.selectors:
            out.append(Candidate("selectors", "skipped", "no selectors in the request"))
        else:
            run.fields = extract.select_fields(html, request.selectors)
            check = quality.check(status=status, block=block, fields=run.fields)
            if check.passed:
                out.append(Candidate("selectors", "answered", f"all {len(run.fields)} selectors matched", check))
                return out
            out.append(Candidate("selectors", "failed", "; ".join(check.reasons), check))

        run.text = extract.main_text(html, url)
        check = quality.check(status=status, block=block, text=run.text, min_text_chars=min_chars)
        if check.passed:
            out.append(Candidate("main_text", "answered", f"{len(run.text)} characters of main text", check))
        else:
            out.append(Candidate("main_text", "failed", "; ".join(check.reasons), check))
        return out

    async def _headless_browser(self, run: _Run, url: str) -> bool:
        started = time.perf_counter()
        why_not = self.browser.availability()
        if why_not:
            run.mark("headless_browser", "skipped", why_not)
            return False
        try:
            rendered = await self.browser.render(url, self.guard)
        except Exception as exc:  # noqa: BLE001 - a crashed render is a failed rung
            run.mark("headless_browser", "failed", f"render failed ({type(exc).__name__})", started)
            return False
        if rendered.refused:
            run.warnings.append(f"the browser refused {rendered.refused} request(s) to internal addresses")
        block = blocks.classify(rendered.html, rendered.status, min_text_chars=self.settings.min_text_chars)
        if block.is_wall:
            reason = f"the rendered page is a wall ({block.reason}); {WALL_NOTE}"
            run.mark("headless_browser", "failed", reason, started)
            run.note(f"{block.label}: {block.reason}")
            return False
        candidates = self._html_rungs(run, rendered.html, rendered.final_url, rendered.status, block)
        last = candidates[-1]
        if last.status == "answered":
            run.html, run.block = rendered.html, block
            run.reasons.clear()
            run.mark("headless_browser", "answered", f"rendered with JavaScript, then {last.name}: {last.reason}", started)
            return True
        failed = [c.reason for c in candidates if c.status == "failed"]
        run.note(*failed)
        run.mark("headless_browser", "failed", "rendered, but nothing passed quality: " + "; ".join(failed), started)
        return False

    # ---------------------------------------------------------------- helpers

    async def _fetch(self, url: str, run: _Run, *, purpose: str) -> FetchResult | Failure:
        async def robots_check(hop: str) -> None:
            verdict = await self.robots.check(hop, run.telemetry)
            if not verdict.allowed:
                raise Refused(verdict.reason)

        hook = robots_check if run.request.respect_robots else None
        try:
            return await self.fetcher.get(url, run.telemetry, purpose=purpose, before_hop=hook)
        except UnsafeURL as exc:
            return Failure("refused", str(exc))
        except Refused as exc:
            return Failure("refused", str(exc))
        except FetchError as exc:
            return Failure("failed", str(exc))

    def _stop(self, run: _Run, at: str, reason: str, *, wall: bool = False) -> ScrapeResponse:
        for name in RUNGS[RUNGS.index(at) + 1:]:
            if name in ("headless_browser", "paid_fetch"):
                continue
            run.mark(name, "skipped", f"stopped at {at}: {reason}")
        if wall:
            run.mark("headless_browser", "skipped", WALL_NOTE)
        else:
            run.mark("headless_browser", "skipped", f"stopped at {at}: {reason}")
        return self._finish(run, None)

    def _finish(self, run: _Run, answered: str | None) -> ScrapeResponse:
        for name in RUNGS:
            if name == "paid_fetch":
                notice = paid.paid_fetch(run.request.url)
                status, _, reason = notice.partition(": ")
                run.mark(name, status, reason)
            elif name not in run.reports:
                run.mark(name, "not_reached", f"answered at {answered}" if answered else "not reached")
        got = run.fetched
        if answered:
            final_quality = Quality(passed=True, reasons=[])
        else:
            final_quality = Quality(passed=False, reasons=run.reasons or ["no rung produced an answer"])
        return ScrapeResponse(
            success=answered is not None,
            url=run.request.url,
            final_url=got.final_url if got else None,
            rung=answered,
            rung_number=RUNGS.index(answered) + 1 if answered else None,
            status_code=got.status if got else None,
            content_type=got.content_type if got else None,
            ladder=[run.reports[name] for name in RUNGS],
            text=run.text,
            fields=run.fields,
            metadata=run.metadata,
            structured=run.structured,
            block=run.block,
            quality=final_quality,
            html=run.html if run.request.include_html else None,
            warnings=run.warnings,
            telemetry=run.telemetry.to_dict(),
        )
