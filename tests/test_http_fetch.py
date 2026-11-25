import httpx
import pytest

from scrape_ladder.guard import Guard, UnsafeURL
from scrape_ladder.http_fetch import Fetcher, FetchError
from scrape_ladder.polite import PoliteDelay
from scrape_ladder.settings import DEFAULT_USER_AGENT

from .conftest import PUBLIC_IP, SITE_HOST, FakeResolver, Recorder, ip, rung, url

PRIVATE = ip(10, 1, 2, 3)


def redirect_to(location: str):
    return lambda request: httpx.Response(302, headers={"location": location})


def fetcher(handler, table=None, **kwargs) -> Fetcher:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Fetcher(Guard(resolver=FakeResolver(table)), client, PoliteDelay(0), user_agent=DEFAULT_USER_AGENT, **kwargs)


async def test_connects_to_the_checked_address_with_the_real_host_and_an_honest_agent():
    handler = Recorder()
    result = await fetcher(handler).get(url("/article.html"))
    sent = handler.requests[0]
    assert sent.url.host == PUBLIC_IP
    assert sent.headers["host"] == SITE_HOST
    assert sent.extensions["sni_hostname"] == SITE_HOST
    assert sent.headers["user-agent"].startswith("scrape-ladder/")
    assert result.status == 200 and result.final_url == url("/article.html")


async def test_redirect_to_a_private_ip_is_refused_before_it_is_requested():
    handler = Recorder({(SITE_HOST, "/go"): redirect_to(f"http://{PRIVATE}/admin")})
    with pytest.raises(UnsafeURL, match="private address"):
        await fetcher(handler).get(url("/go"))
    assert [r.url.path for r in handler.requests] == ["/go"]


async def test_redirect_to_a_name_that_resolves_private_is_refused():
    handler = Recorder({(SITE_HOST, "/go"): redirect_to("http://sneaky.example/")})
    with pytest.raises(UnsafeURL, match="resolves to a private address"):
        await fetcher(handler, {"sneaky.example": [PRIVATE]}).get(url("/go"))
    assert len(handler.requests) == 1


async def test_redirect_to_the_metadata_address_is_refused():
    handler = Recorder({(SITE_HOST, "/go"): redirect_to("http://169.254.169.254/latest/")})
    with pytest.raises(UnsafeURL, match="metadata"):
        await fetcher(handler).get(url("/go"))


async def test_safe_redirects_are_followed_and_listed():
    handler = Recorder({(SITE_HOST, "/old"): redirect_to("/article.html")})
    result = await fetcher(handler).get(url("/old"))
    assert result.final_url == url("/article.html")
    assert result.redirects == [url("/old")]


async def test_redirect_loops_stop():
    handler = Recorder({(SITE_HOST, "/loop"): redirect_to("/loop")})
    with pytest.raises(FetchError, match="redirects"):
        await fetcher(handler, max_redirects=3).get(url("/loop"))
    assert len(handler.requests) == 4


async def test_body_size_is_capped():
    with pytest.raises(FetchError, match="larger than"):
        await fetcher(Recorder(), max_bytes=100).get(url("/article.html"))


async def test_redirect_to_private_ip_through_the_whole_ladder(make_harness):
    harness = make_harness(overrides={(SITE_HOST, "/go"): redirect_to(f"http://{PRIVATE}/")})
    response = await harness.scrape(url=url("/go"))
    assert not response.success
    fetch = rung(response, "http_fetch")
    assert fetch.status == "refused" and "private address" in fetch.reason
    assert PRIVATE not in [r.url.host for r in harness.handler.requests]


async def test_polite_delay_spaces_requests_to_one_host():
    now = [100.0]
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    delay = PoliteDelay(1.5, clock=lambda: now[0], sleep=fake_sleep)
    assert await delay.wait("a.example") == 0
    assert await delay.wait("a.example") == pytest.approx(1.5)
    assert await delay.wait("b.example") == 0
    now[0] += 10
    assert await delay.wait("a.example") == 0
    assert slept == [pytest.approx(1.5)]


async def test_polite_wait_shows_up_in_telemetry(make_harness):
    harness = make_harness(polite_delay_s=0.05)
    response = await harness.scrape(url=url("/article.html"))
    # robots.txt and the page are two requests to one host, so the page waited.
    assert response.telemetry["fetch_count"] == 2
    assert response.telemetry["polite_wait_ms"] >= 30
