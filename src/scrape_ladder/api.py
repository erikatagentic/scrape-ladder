"""FastAPI service: GET /health and POST /scrape-url."""
from __future__ import annotations

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from . import __version__
from .browser import Browser, PlaywrightBrowser
from .guard import Guard, Resolver, system_resolver
from .http_fetch import Fetcher
from .ladder import Ladder
from .models import ScrapeRequest, ScrapeResponse
from .paid import DISABLED
from .polite import PoliteDelay
from .robots import Robots
from .settings import Settings


def build_ladder(
    settings: Settings,
    client: httpx.AsyncClient,
    *,
    resolver: Resolver = system_resolver,
    browser: Browser | None = None,
) -> Ladder:
    guard = Guard(resolver=resolver, trusted_hosts=settings.trusted_hosts)
    fetcher = Fetcher(
        guard, client, PoliteDelay(settings.polite_delay_s),
        user_agent=settings.user_agent, max_redirects=settings.max_redirects, max_bytes=settings.max_bytes,
    )
    robots = Robots(fetcher, settings.robots_agent)
    if browser is None:
        browser = PlaywrightBrowser(mode=settings.browser, user_agent=settings.user_agent, timeout_s=settings.timeout_s)
    return Ladder(settings, guard, fetcher, robots, browser)


def create_app(
    settings: Settings | None = None,
    *,
    resolver: Resolver = system_resolver,
    transport: httpx.AsyncBaseTransport | None = None,
    browser: Browser | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # trust_env=False: no proxy settings are picked up from the environment.
        async with httpx.AsyncClient(transport=transport, timeout=settings.timeout_s, trust_env=False) as client:
            app.state.ladder = build_ladder(settings, client, resolver=resolver, browser=browser)
            yield

    app = FastAPI(title="scrape-ladder", version=__version__, lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict:
        why_not = app.state.ladder.browser.availability()
        return {"ok": True, "browser": why_not or "ready", "paid_fetch": DISABLED}

    @app.post("/scrape-url", response_model=ScrapeResponse)
    async def scrape_url(request: ScrapeRequest) -> ScrapeResponse:
        return await app.state.ladder.run(request)

    return app


app = create_app()
