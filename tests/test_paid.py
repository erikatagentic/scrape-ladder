import ast
from pathlib import Path

import pytest

from scrape_ladder import paid
from scrape_ladder.settings import Settings

PAID_SOURCE = Path(paid.__file__).read_text()


@pytest.mark.parametrize("target", ["http://site.example/", "https://anything.example/x", ""])
def test_stub_always_says_disabled(target):
    assert paid.paid_fetch(target) == "disabled: paid fetches are off in this build"


def test_stub_imports_nothing_that_could_make_a_request():
    tree = ast.parse(PAID_SOURCE)
    imported = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert [getattr(n, "module", None) for n in imported] == ["__future__"]


def test_no_setting_switches_paid_fetches_on(monkeypatch):
    for name in ("SCRAPE_LADDER_PAID", "SCRAPE_LADDER_ENABLE_PAID", "ENABLE_PAID"):
        monkeypatch.setenv(name, "1")
    settings = Settings.from_env()
    assert not [f for f in vars(settings) if "paid" in f]
    assert paid.paid_fetch("http://site.example/") == paid.DISABLED
