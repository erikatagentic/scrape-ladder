"""Plain HTTP fetch behind the internal-address guard.

Redirects are followed by hand so every hop goes back through the guard. Each request
connects to an address the guard checked, with the real host name in the Host header
and in TLS, so a second DNS answer can't swap in a private address.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import urljoin

import httpx

from .guard import Guard, UnsafeURL
from .polite import PoliteDelay
from .telemetry import Telemetry

_REDIRECTS = {301, 302, 303, 307, 308}


class FetchError(RuntimeError):
    """The fetch didn't finish (network error, too many redirects, body too large)."""


class Refused(RuntimeError):
    """A per-hop check (robots.txt) said no before anything was sent."""


HopCheck = Callable[[str], Awaitable[None]]


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    redirects: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return self.body.decode(_charset(self.content_type), errors="replace")


def _charset(content_type: str) -> str:
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset" and value:
            return value.strip("\"' ")
    return "utf-8"


class Fetcher:
    def __init__(
        self,
        guard: Guard,
        client: httpx.AsyncClient,
        delay: PoliteDelay,
        *,
        user_agent: str,
        max_redirects: int = 5,
        max_bytes: int = 5_000_000,
    ):
        self.guard = guard
        self.client = client
        self.delay = delay
        self.user_agent = user_agent
        self.max_redirects = max_redirects
        self.max_bytes = max_bytes

    async def get(
        self,
        url: str,
        telemetry: Telemetry | None = None,
        *,
        purpose: str = "page",
        before_hop: HopCheck | None = None,
    ) -> FetchResult:
        current = url
        hops: list[str] = []
        while True:
            target = self.guard.check(current)  # raises UnsafeURL, on every hop
            if before_hop is not None:
                await before_hop(current)  # raises Refused, on every hop
            waited = await self.delay.wait(target.host)
            if telemetry is not None:
                telemetry.polite_wait_ms += int(waited * 1000)
            status, content_type, body, location, ms = await self._one(target)
            if telemetry is not None:
                telemetry.record_fetch(
                    purpose=purpose, url=current, status=status, ms=ms, bytes=len(body),
                    waited_ms=int(waited * 1000),
                )
            if status in _REDIRECTS and location:
                if len(hops) >= self.max_redirects:
                    raise FetchError(f"more than {self.max_redirects} redirects")
                hops.append(current)
                current = urljoin(current, location)
                continue
            return FetchResult(url, current, status, content_type, body, hops)

    async def _one(self, target) -> tuple[int, str, bytes, str | None, int]:
        headers = {
            "Host": target.host_header,
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/json,text/csv,*/*;q=0.5",
        }
        last_error: Exception | None = None
        for address in target.addresses:
            started = time.perf_counter()
            request = self.client.build_request(
                "GET", target.pinned_url(address), headers=headers,
                extensions={"sni_hostname": target.host},
            )
            try:
                response = await self.client.send(request, stream=True, follow_redirects=False)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            try:
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > self.max_bytes:
                        raise FetchError(f"body larger than {self.max_bytes} bytes")
            finally:
                await response.aclose()
            ms = int((time.perf_counter() - started) * 1000)
            content_type = response.headers.get("content-type", "")
            return response.status_code, content_type, bytes(body), response.headers.get("location"), ms
        raise FetchError(f"couldn't connect to {target.host}: {type(last_error).__name__}")


__all__ = ["Fetcher", "FetchError", "FetchResult", "Refused", "UnsafeURL"]
