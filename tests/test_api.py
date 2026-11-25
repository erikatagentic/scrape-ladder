import httpx
from fastapi.testclient import TestClient

from scrape_ladder.api import create_app

from .conftest import NOT_INSTALLED, TEST_SETTINGS, FakeResolver, Recorder, url


def client() -> TestClient:
    app = create_app(TEST_SETTINGS, resolver=FakeResolver(), transport=httpx.MockTransport(Recorder()),
                     browser=NOT_INSTALLED)
    return TestClient(app)


def test_health_names_the_browser_and_paid_state():
    with client() as c:
        body = c.get("/health").json()
    assert body == {"ok": True, "browser": "browser not installed",
                    "paid_fetch": "disabled: paid fetches are off in this build"}


def test_scrape_url_returns_the_article_and_the_ladder():
    with client() as c:
        response = c.post("/scrape-url", json={"url": url("/article.html")})
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True and body["rung"] == "main_text"
    assert [r["status"] for r in body["ladder"][:5]] == ["skipped", "done", "skipped", "skipped", "skipped"]
    assert body["quality"] == {"passed": True, "reasons": []}
    assert body["telemetry"]["fetch_count"] == 2


def test_a_request_cannot_ask_for_a_paid_fetch():
    with client() as c:
        response = c.post("/scrape-url", json={"url": url("/article.html"), "enable_paid": True})
    assert response.status_code == 422


def test_missing_url_is_a_validation_error():
    with client() as c:
        assert c.post("/scrape-url", json={}).status_code == 422
