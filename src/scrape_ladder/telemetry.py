"""Request-local telemetry. Nothing here outlives the request it describes."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Telemetry:
    started: float = field(default_factory=time.perf_counter)
    fetches: list[dict[str, Any]] = field(default_factory=list)
    polite_wait_ms: int = 0
    robots: dict[str, Any] = field(default_factory=dict)

    def record_fetch(self, **entry: Any) -> None:
        self.fetches.append(entry)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_ms": int((time.perf_counter() - self.started) * 1000),
            "fetch_count": len(self.fetches),
            "bytes_read": sum(f.get("bytes", 0) for f in self.fetches),
            "polite_wait_ms": self.polite_wait_ms,
            "robots": self.robots,
            "fetches": self.fetches,
        }
