"""The optional headless browser rung (Playwright, Chromium).

It's off unless Playwright is installed (`pip install .[browser]` then
`playwright install chromium`). Every request the page makes, redirect hops and
subresources included, is paused and checked by the same internal-address guard
before it leaves the browser. It's a plain headless Chromium with an honest user
agent, for pages that build their content with JavaScript, and nothing more.
"""
from __future__ import annotations

import asyncio
import importlib.util
from dataclasses import dataclass
from typing import Protocol

from .guard import Guard, UnsafeURL


@dataclass
class Rendered:
    status: int | None
    html: str
    final_url: str
    refused: int = 0


class Browser(Protocol):
    def availability(self) -> str | None:
        """None when ready, else the reason the rung is skipped."""

    async def render(self, url: str, guard: Guard) -> Rendered: ...


class PlaywrightBrowser:
    def __init__(self, *, mode: str = "auto", user_agent: str, timeout_s: float = 15.0):
        self.mode = mode
        self.user_agent = user_agent
        self.timeout_ms = int(timeout_s * 1000)

    def availability(self) -> str | None:
        if self.mode == "off":
            return "browser turned off in settings"
        if importlib.util.find_spec("playwright") is None:
            return "browser not installed"
        return None

    async def render(self, url: str, guard: Guard) -> Rendered:
        from playwright.async_api import async_playwright

        refused = 0

        async def allowed(request_url: str) -> bool:
            if not request_url.startswith(("http://", "https://")):
                return True  # data:, blob: and about: never leave the browser
            try:
                await asyncio.to_thread(guard.check, request_url)
                return True
            except UnsafeURL:
                return False

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(user_agent=self.user_agent, service_workers="block")
                page = await context.new_page()
                # A page opened by the page itself isn't guarded, so it is closed at once.
                context.on("page", lambda extra: asyncio.ensure_future(extra.close()) if extra is not page else None)
                session = await context.new_cdp_session(page)

                async def on_paused(event: dict) -> None:
                    nonlocal refused
                    request_id = event["requestId"]
                    if await allowed(event.get("request", {}).get("url", "")):
                        await session.send("Fetch.continueRequest", {"requestId": request_id})
                    else:
                        refused += 1
                        await session.send("Fetch.failRequest", {"requestId": request_id, "errorReason": "BlockedByClient"})

                session.on("Fetch.requestPaused", lambda event: asyncio.ensure_future(on_paused(event)))
                await session.send("Fetch.enable", {"patterns": [{"urlPattern": "*"}]})
                response = await page.goto(url, wait_until="networkidle", timeout=self.timeout_ms)
                html = await page.content()
                status = response.status if response is not None else None
                return Rendered(status=status, html=html, final_url=page.url, refused=refused)
            finally:
                await browser.close()
