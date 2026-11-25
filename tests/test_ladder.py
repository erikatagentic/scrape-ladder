"""Each rung's hit and skip reasons, plus the pages that must fail."""
import io

import httpx
from openpyxl import Workbook

from scrape_ladder.ladder import WALL_NOTE
from scrape_ladder.models import RUNGS

from .conftest import SITE, SITE_HOST, FakeBrowser, ip, rung, url


def statuses(response) -> dict[str, str]:
    return {r.name: r.status for r in response.ladder}


# ---------------------------------------------------------------- shape


async def test_every_response_lists_all_eight_rungs_in_order(make_harness):
    response = await make_harness().scrape(url=url("/article.html"))
    assert [r.name for r in response.ladder] == list(RUNGS)
    assert [r.number for r in response.ladder] == list(range(1, 9))


# ---------------------------------------------------------------- 1. official source


async def test_official_source_answers_with_a_named_csv_export(make_harness):
    harness = make_harness()
    response = await harness.scrape(url=url("/index.html"), export_url=url("/export.csv"))
    assert response.success and response.rung == "official_source" and response.rung_number == 1
    assert rung(response, "official_source").reason == "csv export with 6 rows"
    assert response.structured.columns == ["branch", "crop", "packets_out", "packets_back"]
    assert all(statuses(response)[n] == "not_reached" for n in RUNGS[1:7])
    assert "/index.html" not in harness.handler.paths()


async def test_official_source_skips_when_the_request_names_no_export(make_harness):
    response = await make_harness().scrape(url=url("/article.html"))
    assert rung(response, "official_source").status == "skipped"
    assert rung(response, "official_source").reason == "no export_url in the request"


async def test_official_source_failure_falls_through_to_the_page(make_harness):
    response = await make_harness().scrape(url=url("/article.html"), export_url=url("/missing.csv"))
    assert rung(response, "official_source").status == "failed"
    assert rung(response, "official_source").reason == "export answered 404"
    assert response.rung == "main_text"


async def test_official_source_refuses_an_export_on_a_private_address(make_harness):
    response = await make_harness().scrape(url=url("/article.html"), export_url=f"http://{ip(192, 168, 0, 9)}/x.csv")
    official = rung(response, "official_source")
    assert official.status == "refused" and "private address" in official.reason
    assert response.rung == "main_text"


# ---------------------------------------------------------------- 2. http fetch


async def test_http_fetch_reports_what_it_got(make_harness):
    response = await make_harness().scrape(url=url("/article.html"))
    fetch = rung(response, "http_fetch")
    assert fetch.status == "done"
    assert fetch.reason.startswith("200 text/html, ")


async def test_http_fetch_failure_stops_the_ladder(make_harness):
    response = await make_harness().scrape(url=url("/nope.html"))
    assert not response.success
    assert rung(response, "http_fetch").status == "failed"
    assert rung(response, "http_fetch").reason.startswith("status 404")
    assert rung(response, "main_text").reason.startswith("stopped at http_fetch: status 404")
    assert response.quality.passed is False


# ---------------------------------------------------------------- 3. structured parse


async def test_structured_parse_answers_for_a_csv_url(make_harness):
    response = await make_harness().scrape(url=url("/export.csv"))
    assert response.rung == "structured_parse"
    assert rung(response, "structured_parse").reason == "csv with 6 rows"
    assert response.structured.sample_rows[0]["crop"] == "beans"


async def test_structured_parse_answers_for_json(make_harness):
    response = await make_harness().scrape(url=url("/export.json"))
    assert response.rung == "structured_parse"
    assert response.structured.format == "json" and response.structured.row_count == 3


async def test_structured_parse_answers_for_xlsx(make_harness):
    book = Workbook()
    sheet = book.active
    sheet.append(["branch", "crop"])
    sheet.append(["Riverbend", "beans"])
    sheet.append(["Hillcrest", "kale"])
    buffer = io.BytesIO()
    book.save(buffer)
    xlsx = lambda r: httpx.Response(200, content=buffer.getvalue(), headers={"content-type": "application/octet-stream"})  # noqa: E731
    response = await make_harness(overrides={(SITE_HOST, "/report.xlsx"): xlsx}).scrape(url=url("/report.xlsx"))
    assert response.rung == "structured_parse"
    assert response.structured.format == "xlsx"
    assert response.structured.sample_rows == [{"branch": "Riverbend", "crop": "beans"}, {"branch": "Hillcrest", "crop": "kale"}]


async def test_structured_parse_skips_html(make_harness):
    response = await make_harness().scrape(url=url("/article.html"))
    skip = rung(response, "structured_parse")
    assert skip.status == "skipped" and skip.reason == "the response is text/html, not CSV, JSON or XLSX"


async def test_an_empty_csv_fails_and_does_not_try_html_rungs(make_harness):
    empty = lambda r: httpx.Response(200, text="a,b\n", headers={"content-type": "text/csv"})  # noqa: E731
    response = await make_harness(overrides={(SITE_HOST, "/empty.csv"): empty}).scrape(url=url("/empty.csv"))
    assert not response.success
    assert rung(response, "structured_parse").reason == "no rows"
    assert rung(response, "page_metadata").reason == "stopped at structured_parse: the response wasn't an HTML page"


# ---------------------------------------------------------------- 4. page metadata


async def test_page_metadata_answers_for_json_ld(make_harness):
    response = await make_harness().scrape(url=url("/product.html"))
    assert response.rung == "page_metadata" and response.rung_number == 4
    assert rung(response, "page_metadata").reason == "1 typed item(s): Product"
    product = response.metadata["json-ld"][0]
    assert product["offers"]["price"] == "18.00"


async def test_page_metadata_answers_for_microdata(make_harness):
    html = (
        '<html><body><div itemscope itemtype="http://schema.org/Event">'
        '<span itemprop="name">Seed swap</span></div></body></html>'
    )
    page = lambda r: httpx.Response(200, html=html)  # noqa: E731
    response = await make_harness(overrides={(SITE_HOST, "/event.html"): page}).scrape(url=url("/event.html"))
    assert response.rung == "page_metadata"
    assert "Event" in rung(response, "page_metadata").reason


async def test_page_metadata_skips_a_page_with_only_opengraph(make_harness):
    response = await make_harness().scrape(url=url("/article.html"))
    skip = rung(response, "page_metadata")
    assert skip.status == "skipped"
    assert skip.reason == "no typed JSON-LD or microdata item on the page (OpenGraph tags kept)"
    assert response.metadata["opengraph"][0]["og:title"] == "The seed library that outgrew its shelf"


async def test_page_metadata_steps_aside_when_selectors_are_asked_for(make_harness):
    response = await make_harness().scrape(url=url("/product.html"), selectors={"price": ".price"})
    assert rung(response, "page_metadata").status == "skipped"
    assert "selectors" in rung(response, "page_metadata").reason


# ---------------------------------------------------------------- 5. selectors


async def test_selectors_answer_when_every_selector_matches(make_harness):
    response = await make_harness().scrape(
        url=url("/product.html"),
        selectors={"title": "h1.title", "price": ".price", "kind": "meta[property='og:type']::attr(content)"},
    )
    assert response.rung == "selectors" and response.rung_number == 5
    assert response.fields["title"] == "Trail Mug, 12 oz"
    assert response.fields["price"] == "$18.00"
    assert response.fields["kind"] == "product"
    assert rung(response, "selectors").reason == "all 3 selectors matched"


async def test_selectors_fail_on_a_miss_and_the_ladder_climbs(make_harness):
    response = await make_harness().scrape(url=url("/article.html"), selectors={"title": "h1", "price": ".price"})
    sel = rung(response, "selectors")
    assert sel.status == "failed" and sel.reason == "selectors matched nothing for: price"
    assert response.fields["title"] == "The seed library that outgrew its shelf"
    assert response.rung == "main_text"


async def test_selectors_skip_when_none_are_asked_for(make_harness):
    response = await make_harness().scrape(url=url("/article.html"))
    assert rung(response, "selectors").reason == "no selectors in the request"


# ---------------------------------------------------------------- 6. main text


async def test_main_text_answers_for_the_article(make_harness):
    response = await make_harness().scrape(url=url("/article.html"))
    assert response.success and response.rung == "main_text" and response.rung_number == 6
    assert "seed library" in response.text.lower()
    assert "green dot" in response.text
    assert rung(response, "main_text").reason.endswith("characters of main text")
    assert rung(response, "headless_browser").status == "not_reached"


# ---------------------------------------------------------------- 7. headless browser


async def test_browser_rung_skips_when_playwright_is_not_installed(make_harness):
    response = await make_harness().scrape(url=url("/js-only.html"))
    assert not response.success
    assert rung(response, "headless_browser").status == "skipped"
    assert rung(response, "headless_browser").reason == "browser not installed"
    assert "js_shell" == response.block.label


async def test_browser_rung_answers_for_a_javascript_page(make_harness):
    rendered = (SITE / "article.html").read_text()
    browser = FakeBrowser(rendered)
    response = await make_harness(browser=browser).scrape(url=url("/js-only.html"))
    assert response.success and response.rung == "headless_browser" and response.rung_number == 7
    assert rung(response, "main_text").status == "failed"
    assert rung(response, "headless_browser").reason.startswith("rendered with JavaScript, then main_text")
    assert browser.rendered == [url("/js-only.html")]
    assert response.quality.passed


async def test_browser_rung_fails_when_the_render_is_a_wall(make_harness):
    browser = FakeBrowser((SITE / "challenge.html").read_text())
    response = await make_harness(browser=browser).scrape(url=url("/js-only.html"))
    assert not response.success
    assert WALL_NOTE in rung(response, "headless_browser").reason


async def test_real_playwright_wrapper_reports_not_installed(monkeypatch):
    from scrape_ladder import browser as browser_module

    monkeypatch.setattr(browser_module.importlib.util, "find_spec", lambda name: None)
    assert browser_module.PlaywrightBrowser(user_agent="x").availability() == "browser not installed"
    assert browser_module.PlaywrightBrowser(mode="off", user_agent="x").availability() == "browser turned off in settings"


# ---------------------------------------------------------------- pages that must fail quality


async def test_challenge_page_with_status_200_is_a_failure(make_harness):
    browser = FakeBrowser("<p>never used</p>")
    response = await make_harness(browser=browser).scrape(url=url("/challenge.html"))
    assert response.status_code == 200
    assert not response.success and response.rung is None
    assert response.block.label == "challenge"
    assert any(r.startswith("challenge:") for r in response.quality.reasons)
    assert rung(response, "http_fetch").status == "failed"
    assert rung(response, "headless_browser").reason == WALL_NOTE
    assert browser.rendered == []


async def test_thin_page_with_status_200_is_a_failure(make_harness):
    response = await make_harness().scrape(url=url("/thin.html"))
    assert response.status_code == 200
    assert not response.success
    assert response.block.label == "thin"
    assert any(r.startswith("thin text:") for r in response.quality.reasons)
    assert rung(response, "main_text").status == "failed"


async def test_login_wall_is_a_failure(make_harness):
    html = '<html><body><h1>Members only</h1><form><input type="password"></form></body></html>'
    page = lambda r: httpx.Response(200, html=html)  # noqa: E731
    response = await make_harness(overrides={(SITE_HOST, "/members.html"): page}).scrape(url=url("/members.html"))
    assert not response.success and response.block.label == "login_wall"


# ---------------------------------------------------------------- 8. paid fetch


async def test_paid_rung_is_disabled_when_everything_else_fails(make_harness):
    response = await make_harness().scrape(url=url("/thin.html"))
    paid = rung(response, "paid_fetch")
    assert (paid.status, paid.reason) == ("disabled", "paid fetches are off in this build")


async def test_paid_rung_is_disabled_when_a_lower_rung_answers(make_harness):
    response = await make_harness().scrape(url=url("/article.html"))
    assert rung(response, "paid_fetch").status == "disabled"
    assert response.rung != "paid_fetch"


async def test_include_html_returns_the_page(make_harness):
    response = await make_harness().scrape(url=url("/article.html"), include_html=True)
    assert response.html and "<article>" in response.html
    assert (await make_harness().scrape(url=url("/article.html"))).html is None
