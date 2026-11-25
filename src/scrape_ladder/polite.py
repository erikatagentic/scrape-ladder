"""A per-host polite delay: at most one request to a host every `interval_s` seconds."""
from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable


class PoliteDelay:
    def __init__(
        self,
        interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.interval_s = max(0.0, interval_s)
        self._clock = clock
        self._sleep = sleep
        self._next_ok: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def wait(self, host: str) -> float:
        """Wait until `host` may be asked again. Returns the seconds waited."""
        async with self._lock:
            now = self._clock()
            ready_at = self._next_ok.get(host, now)
            waited = max(0.0, ready_at - now)
            self._next_ok[host] = max(now, ready_at) + self.interval_s
        if waited:
            await self._sleep(waited)
        return waited
