import httpx

from .conftest import SITE_HOST, rung, url


async def test_disallowed_path_is_refused_and_never_fetched(make_harness):
    harness = make_harness()
    response = await harness.scrape(url=url("/private/notes.html"))
    assert not response.success
    fetch = rung(response, "http_fetch")
    assert fetch.status == "refused"
    assert fetch.reason == "robots.txt disallows this path"
    assert harness.handler.paths() == ["/robots.txt"]
    assert "robots.txt disallows this path" in response.quality.reasons


async def test_redirect_into_a_disallowed_path_is_refused(make_harness):
    redirect = lambda request: httpx.Response(301, headers={"location": "/private/notes.html"})  # noqa: E731
    harness = make_harness(overrides={(SITE_HOST, "/moved"): redirect})
    response = await harness.scrape(url=url("/moved"))
    assert rung(response, "http_fetch").status == "refused"
    assert "/private/notes.html" not in harness.handler.paths()


async def test_missing_robots_file_means_allowed(make_harness):
    harness = make_harness(overrides={(SITE_HOST, "/robots.txt"): lambda r: httpx.Response(404)})
    response = await harness.scrape(url=url("/private/notes.html"))
    assert rung(response, "http_fetch").status == "done"


async def test_robots_server_error_means_refused(make_harness):
    harness = make_harness(overrides={(SITE_HOST, "/robots.txt"): lambda r: httpx.Response(503)})
    response = await harness.scrape(url=url("/article.html"))
    fetch = rung(response, "http_fetch")
    assert fetch.status == "refused" and "couldn't be read" in fetch.reason
    assert harness.handler.paths() == ["/robots.txt"]


async def test_robots_rules_are_read_once_per_site(make_harness):
    harness = make_harness()
    await harness.scrape(url=url("/article.html"))
    await harness.scrape(url=url("/thin.html"))
    assert harness.handler.paths().count("/robots.txt") == 1


async def test_request_can_turn_the_robots_check_off_and_is_told_so(make_harness):
    harness = make_harness()
    response = await harness.scrape(url=url("/private/notes.html"), respect_robots=False)
    assert rung(response, "http_fetch").status == "done"
    assert "/robots.txt" not in harness.handler.paths()
    assert "robots.txt check turned off by the request" in response.warnings


async def test_robots_rules_for_our_own_agent_token(make_harness):
    rules = "User-agent: scrape-ladder\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    harness = make_harness(overrides={(SITE_HOST, "/robots.txt"): lambda r: httpx.Response(200, text=rules)})
    response = await harness.scrape(url=url("/article.html"))
    assert rung(response, "http_fetch").status == "refused"
