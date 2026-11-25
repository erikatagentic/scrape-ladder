"""Settings read from environment variables. Every default is the polite one."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from . import __version__

DEFAULT_USER_AGENT = f"scrape-ladder/{__version__} (polite open-source scraper; honors robots.txt)"
ROBOTS_AGENT = "scrape-ladder"


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _hosts(name: str) -> frozenset[str]:
    raw = os.environ.get(name, "")
    return frozenset(h.strip().lower().rstrip(".") for h in raw.split(",") if h.strip())


@dataclass(frozen=True)
class Settings:
    user_agent: str = DEFAULT_USER_AGENT
    robots_agent: str = ROBOTS_AGENT
    # Seconds between two requests to the same host, robots.txt fetches included.
    polite_delay_s: float = 1.0
    timeout_s: float = 15.0
    max_redirects: int = 5
    max_bytes: int = 5_000_000
    # Exact host names that skip the internal-address check. Empty by default. The
    # offline demo sets it to its fixture host, which lives on a private network.
    trusted_hosts: frozenset[str] = field(default_factory=frozenset)
    # "auto" uses the headless browser only when Playwright is installed; "off" never does.
    browser: str = "auto"
    min_text_chars: int = 200

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            user_agent=os.environ.get("SCRAPE_LADDER_USER_AGENT", "").strip() or DEFAULT_USER_AGENT,
            polite_delay_s=_float("SCRAPE_LADDER_POLITE_DELAY_S", 1.0),
            timeout_s=_float("SCRAPE_LADDER_TIMEOUT_S", 15.0),
            max_redirects=_int("SCRAPE_LADDER_MAX_REDIRECTS", 5),
            max_bytes=_int("SCRAPE_LADDER_MAX_BYTES", 5_000_000),
            trusted_hosts=_hosts("SCRAPE_LADDER_TRUSTED_HOSTS"),
            browser=os.environ.get("SCRAPE_LADDER_BROWSER", "auto").strip().lower() or "auto",
            min_text_chars=_int("SCRAPE_LADDER_MIN_TEXT_CHARS", 200),
        )
