from scrape_ladder import blocks, quality
from scrape_ladder.blocks import Block

LONG = "<p>" + "Plain words about seeds and shelves. " * 20 + "</p>"


def label(html: str, status: int = 200) -> str:
    return blocks.classify(html, status).label


def test_real_page_is_ok():
    assert label(LONG) == "ok"


def test_rate_limit_by_status_and_by_words():
    assert label(LONG, 429) == "rate_limited"
    assert label("<p>Too many requests. Try again soon.</p>") == "rate_limited"


def test_challenge_phrases():
    assert label("<h1>Checking your browser</h1>") == "challenge"
    assert label("<p>Please verify you are human.</p>") == "challenge"
    assert label("<p>Access denied</p>", 403) == "challenge"


def test_login_wall_by_words_and_by_password_field():
    assert label("<p>Please sign in to continue.</p>") == "login_wall"
    assert label('<form><input type="password" name="pw"></form>') == "login_wall"


def test_a_long_article_that_mentions_a_captcha_is_still_ok():
    html = "<p>A short history of the captcha and why sites use one.</p>" + LONG * 3
    assert label(html) == "ok"


def test_forbidden_status_without_words_is_a_wall():
    assert label(LONG, 403) == "challenge"


def test_not_found():
    assert label("<h1>Page not found</h1>", 404) == "not_found"


def test_javascript_shell_and_thin_page():
    assert label("<div id='app'></div><script>build()</script>") == "js_shell"
    assert label("<p>Coming soon.</p>") == "thin"


def test_walls_are_the_three_stopping_labels():
    assert Block(label="challenge").is_wall and Block(label="login_wall").is_wall
    assert not Block(label="thin").is_wall and not Block().is_wall


def test_quality_200_alone_is_not_success():
    check = quality.check(status=200, block=Block(label="challenge", reason="x"), text="y" * 500)
    assert not check.passed and check.reasons == ["challenge: x"]


def test_quality_thin_text_and_bad_status():
    check = quality.check(status=500, block=Block(), text="short", min_text_chars=200)
    assert not check.passed
    assert check.reasons == ["status 500 isn't a 2xx", "thin text: 5 characters, under 200"]


def test_quality_rows_fields_and_items():
    assert not quality.check(status=200, block=None, rows=0).passed
    assert not quality.check(status=200, block=None, fields={"a": "1", "b": None}).passed
    assert not quality.check(status=200, block=None, items=0).passed
    assert quality.check(status=200, block=None, rows=3, fields={"a": "1"}, items=1).passed
