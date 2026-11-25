import pytest

from scrape_ladder.guard import Guard, UnsafeURL, ip_problem

from .conftest import PUBLIC_IP, FakeResolver, ip

PRIVATE_10 = ip(10, 0, 0, 5)
PRIVATE_192 = ip(192, 168, 1, 20)
PRIVATE_172 = ip(172, 16, 4, 4)
METADATA = "169.254.169.254"


def guard(table=None, trusted=frozenset()):
    return Guard(resolver=FakeResolver(table), trusted_hosts=trusted)


def test_public_host_passes_and_returns_checked_addresses():
    target = guard().check("https://site.example/a?b=1")
    assert target.host == "site.example"
    assert target.addresses == (PUBLIC_IP,)
    assert target.port == 443


@pytest.mark.parametrize(
    "address, words",
    [
        ("127.0.0.1", "loopback"),
        (PRIVATE_10, "private"),
        (PRIVATE_192, "private"),
        (PRIVATE_172, "private"),
        (ip(169, 254, 3, 9), "link-local"),
        (METADATA, "metadata"),
        ("0.0.0.0", "unspecified"),
        ("::1", "loopback"),
        ("::ffff:127.0.0.1", "loopback"),
        (ip(100, 64, 0, 1), "not a public address"),
    ],
)
def test_ip_literals_that_are_not_public_are_refused(address, words):
    host = f"[{address}]" if ":" in address else address
    with pytest.raises(UnsafeURL, match=words):
        guard().check(f"http://{host}/")


def test_host_that_resolves_to_a_private_address_is_refused():
    with pytest.raises(UnsafeURL, match="resolves to a private address"):
        guard({"inside.example": [PRIVATE_10]}).check("http://inside.example/")


def test_one_private_answer_among_public_ones_is_enough_to_refuse():
    with pytest.raises(UnsafeURL, match="resolves to a cloud metadata address"):
        guard({"mixed.example": [PUBLIC_IP, METADATA]}).check("http://mixed.example/")


@pytest.mark.parametrize("bad", ["http://localhost/", "http://admin.localhost/", "http://LOCALHOST./x"])
def test_local_names_are_refused(bad):
    with pytest.raises(UnsafeURL, match="local name"):
        guard().check(bad)


@pytest.mark.parametrize(
    "bad, words",
    [
        ("file:///etc/passwd", "scheme"),
        ("ftp://site.example/", "scheme"),
        ("http://user:pw@site.example/", "user name or password"),
        ("http://site.example\\@evil.example/", "backslash"),
        ("http:///nohost", "no host"),
        ("http://nowhere.example/", "doesn't resolve"),
    ],
)
def test_malformed_or_odd_urls_are_refused(bad, words):
    with pytest.raises(UnsafeURL, match=words):
        guard().check(bad)


def test_trusted_host_skips_only_the_address_check():
    trusted = guard({"fixture.test": [PRIVATE_172]}, trusted=frozenset({"fixture.test"}))
    assert trusted.check("http://fixture.test/article.html").addresses == (PRIVATE_172,)
    with pytest.raises(UnsafeURL):
        trusted.check("http://other.test/")  # not listed, and doesn't resolve


def test_pinned_url_keeps_path_query_and_port():
    target = guard().check("http://site.example:8081/p/q.html?x=1")
    assert target.pinned_url(PUBLIC_IP) == f"http://{PUBLIC_IP}:8081/p/q.html?x=1"
    assert target.host_header == "site.example:8081"
    assert target.pinned_url("2001:db8::1").startswith("http://[2001:db8::1]:8081/")


def test_ip_problem_is_none_for_a_public_address():
    assert ip_problem(PUBLIC_IP) is None
    assert ip_problem("not-an-ip") == "not an IP address"
