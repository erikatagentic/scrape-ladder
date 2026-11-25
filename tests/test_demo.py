"""The offline demo path, end to end over real loopback sockets.

This is the same path as `docker compose up` plus one curl: a static fixture server, the
API in front of it, and one POST to /scrape-url for the article.
"""
import importlib.util
import sys

import httpx
import pytest

from scrape_ladder.settings import Settings

from .conftest import ROOT


@pytest.fixture
def demo():
    spec = importlib.util.spec_from_file_location("demo_offline", ROOT / "scripts" / "demo_offline.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up here
    spec.loader.exec_module(module)
    running = module.start(api_port=0, fixture_port=0, settings=Settings(polite_delay_s=0.2))
    yield running
    running.stop()


def test_one_post_returns_the_article_with_its_rung_and_the_skipped_rungs(demo):
    response = httpx.post(f"{demo.api_url}/scrape-url", json={"url": demo.article_url}, timeout=30)
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is True
    assert body["rung"] == "main_text" and body["rung_number"] == 6
    assert "seed library" in body["text"].lower()
    skipped = {r["name"]: r["reason"] for r in body["ladder"] if r["status"] == "skipped"}
    assert skipped == {
        "official_source": "no export_url in the request",
        "structured_parse": "the response is text/html, not CSV, JSON or XLSX",
        "page_metadata": "no typed JSON-LD or microdata item on the page (OpenGraph tags kept)",
        "selectors": "no selectors in the request",
    }
    assert body["ladder"][7]["status"] == "disabled"
    # robots.txt was read first, then the page, with the polite delay between them.
    assert [f["purpose"] for f in body["telemetry"]["fetches"]] == ["robots", "page"]
    assert body["telemetry"]["polite_wait_ms"] >= 100


def test_the_demo_site_still_refuses_what_robots_txt_disallows(demo):
    target = demo.article_url.replace("article.html", "private/notes.html")
    body = httpx.post(f"{demo.api_url}/scrape-url", json={"url": target}, timeout=30).json()
    assert body["success"] is False
    assert body["ladder"][1]["status"] == "refused"
