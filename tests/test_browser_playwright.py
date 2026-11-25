"""The real headless browser rung, against the fixture site on loopback.

Needs the optional extra: `pip install .[browser]` then `playwright install chromium`.
CI installs both, so these run there.
"""
import functools
import threading
from dataclasses import replace
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

pytest.importorskip("playwright")

from scrape_ladder.api import build_ladder  # noqa: E402
from scrape_ladder.guard import Guard  # noqa: E402
from scrape_ladder.models import ScrapeRequest  # noqa: E402

from .conftest import SITE, TEST_SETTINGS  # noqa: E402

LOOPBACK = "127.0.0.1"


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def site():
    server = ThreadingHTTPServer((LOOPBACK, 0), functools.partial(_Quiet, directory=str(SITE)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{LOOPBACK}:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


async def test_javascript_page_answers_at_the_browser_rung(site):
    # Loopback is refused by default, so this test names it as the one trusted host.
    settings = replace(TEST_SETTINGS, trusted_hosts=frozenset({LOOPBACK}))
    async with httpx.AsyncClient(trust_env=False) as client:
        ladder = build_ladder(settings, client)
        response = await ladder.run(ScrapeRequest(url=f"{site}/js-only.html"))
    assert response.success, response.quality.reasons
    assert response.rung == "headless_browser"
    assert "first Thursday" in response.text
    statuses = {r.name: r.status for r in response.ladder}
    assert statuses["main_text"] == "failed"


async def test_browser_refuses_requests_to_internal_addresses(site):
    from scrape_ladder.browser import PlaywrightBrowser

    # Without the trusted host, the browser's own request to loopback is blocked
    # before it leaves, so the render fails instead of reading the page.
    browser = PlaywrightBrowser(user_agent="scrape-ladder-test", timeout_s=10)
    with pytest.raises(Exception, match="ERR_BLOCKED_BY_CLIENT"):
        await browser.render(f"{site}/article.html", Guard())
