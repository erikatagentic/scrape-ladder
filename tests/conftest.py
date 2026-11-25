"""Shared test helpers. No test reaches the outside network: HTTP goes through an
httpx mock transport, DNS through a fake resolver, and the demo test uses loopback only."""
from __future__ import annotations

import asyncio
import mimetypes
from dataclasses import replace
from pathlib import Path
from typing import Callable

import httpx
import pytest

from scrape_ladder.api import build_ladder
from scrape_ladder.browser import Rendered
from scrape_ladder.ladder import Ladder
from scrape_ladder.models import ScrapeRequest, ScrapeResponse
from scrape_ladder.settings import Settings

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "fixtures" / "site"

# A global address that stands in for "some public web server". Nothing connects to it.
PUBLIC_IP = "93.184.215.14"
SITE_HOST = "site.example"


def ip(*parts: int) -> str:
    """Build an IPv4 address from its parts, so no private address sits in the source as text."""
    return ".".join(str(p) for p in parts)


class FakeResolver:
    def __init__(self, table: dict[str, list[str]] | None = None):
        self.table = {SITE_HOST: [PUBLIC_IP], **(table or {})}
        self.asked: list[str] = []

    def __call__(self, host: str) -> list[str]:
        self.asked.append(host)
        return list(self.table.get(host, []))


class Recorder:
    """An httpx handler that serves the fixture site for SITE_HOST and records each request."""

    def __init__(self, overrides: dict[tuple[str, str], Callable[[httpx.Request], httpx.Response]] | None = None):
        self.overrides = overrides or {}
        self.requests: list[httpx.Request] = []

    def paths(self, host: str = SITE_HOST) -> list[str]:
        return [r.url.path for r in self.requests if r.headers["host"].split(":")[0] == host]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.headers["host"].split(":")[0]
        key = (host, request.url.path)
        if key in self.overrides:
            return self.overrides[key](request)
        if host != SITE_HOST:
            return httpx.Response(404, text="unknown host in test")
        return serve_file(request.url.path)


def serve_file(path: str) -> httpx.Response:
    target = (SITE / path.lstrip("/")).resolve()
    if not target.is_file() or SITE not in target.parents:
        return httpx.Response(404, html="<h1>Page not found</h1>")
    content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    if content_type.startswith("text/") or content_type.endswith("json"):
        content_type += "; charset=utf-8"
    return httpx.Response(200, content=target.read_bytes(), headers={"content-type": content_type})


class FakeBrowser:
    """Stands in for Playwright: 'renders' by returning prepared HTML."""

    def __init__(self, html: str | None = None, *, status: int = 200, missing: str | None = None):
        self.html = html
        self.status = status
        self.missing = missing
        self.rendered: list[str] = []

    def availability(self) -> str | None:
        return self.missing

    async def render(self, url: str, guard) -> Rendered:
        guard.check(url)
        self.rendered.append(url)
        return Rendered(status=self.status, html=self.html or "", final_url=url)


NOT_INSTALLED = FakeBrowser(missing="browser not installed")

TEST_SETTINGS = Settings(polite_delay_s=0.0)


class Harness:
    def __init__(self, handler: Recorder, resolver: FakeResolver, browser, settings: Settings):
        self.handler = handler
        self.resolver = resolver
        self.browser = browser
        self.settings = settings
        self.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.ladder: Ladder = build_ladder(settings, self.client, resolver=resolver, browser=browser)

    async def scrape(self, **fields) -> ScrapeResponse:
        return await self.ladder.run(ScrapeRequest(**fields))


@pytest.fixture
def make_harness():
    made: list[Harness] = []

    def make(*, overrides=None, dns=None, browser=None, **settings) -> Harness:
        harness = Harness(
            Recorder(overrides), FakeResolver(dns), browser or NOT_INSTALLED, replace(TEST_SETTINGS, **settings),
        )
        made.append(harness)
        return harness

    yield make
    for harness in made:
        asyncio.run(harness.client.aclose())


def url(path: str) -> str:
    return f"http://{SITE_HOST}{path}"


def rung(response: ScrapeResponse, name: str):
    return next(r for r in response.ladder if r.name == name)
