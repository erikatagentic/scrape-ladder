"""robots.txt respect, on by default.

Follows RFC 9309 on errors: a 4xx answer means there are no rules, so the page is
allowed; a 5xx answer or a failed fetch means the site's rules are unknown, so the
page is refused.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from .guard import UnsafeURL
from .http_fetch import FetchError, Fetcher
from .telemetry import Telemetry


@dataclass(frozen=True)
class RobotsVerdict:
    allowed: bool
    reason: str


class Robots:
    def __init__(self, fetcher: Fetcher, agent: str):
        self.fetcher = fetcher
        self.agent = agent
        self._cache: dict[str, RobotFileParser | str] = {}

    async def check(self, url: str, telemetry: Telemetry | None = None) -> RobotsVerdict:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        rules = self._cache.get(origin)
        cached = rules is not None
        if rules is None:
            rules = await self._load(origin, telemetry)
            self._cache[origin] = rules
        if telemetry is not None:
            telemetry.robots = {"origin": origin, "cached": cached}
        if isinstance(rules, str):
            allowed = rules == "allow_all"
            reason = "no robots.txt rules (4xx answer)" if allowed else "robots.txt couldn't be read, so the page is refused"
            return RobotsVerdict(allowed, reason)
        if rules.can_fetch(self.agent, url):
            return RobotsVerdict(True, "robots.txt allows this path")
        return RobotsVerdict(False, "robots.txt disallows this path")

    async def _load(self, origin: str, telemetry: Telemetry | None) -> RobotFileParser | str:
        try:
            result = await self.fetcher.get(f"{origin}/robots.txt", telemetry, purpose="robots")
        except (FetchError, UnsafeURL):
            return "disallow_all"
        if 400 <= result.status < 500:
            return "allow_all"
        if not 200 <= result.status < 300:
            return "disallow_all"
        parser = RobotFileParser()
        parser.parse(result.text.splitlines())
        return parser
