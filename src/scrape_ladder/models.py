"""Request and response shapes for POST /scrape-url."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .blocks import Block
from .quality import Quality
from .structured import StructuredParse

RungStatus = Literal["answered", "done", "skipped", "failed", "refused", "disabled", "not_reached"]

RUNGS = (
    "official_source",
    "http_fetch",
    "structured_parse",
    "page_metadata",
    "selectors",
    "main_text",
    "headless_browser",
    "paid_fetch",
)


class ScrapeRequest(BaseModel):
    # Unknown fields are refused, so nothing in a request can switch on a paid fetch.
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=4096)
    export_url: str | None = Field(default=None, max_length=4096,
                                   description="A known CSV or JSON export for this page. Tried first.")
    selectors: dict[str, str] = Field(default_factory=dict, max_length=50)
    respect_robots: bool = True
    include_html: bool = False


class RungReport(BaseModel):
    number: int
    name: str
    status: RungStatus
    reason: str
    ms: int = 0


class ScrapeResponse(BaseModel):
    success: bool
    url: str
    final_url: str | None = None
    rung: str | None = None
    rung_number: int | None = None
    status_code: int | None = None
    content_type: str | None = None
    ladder: list[RungReport]
    text: str = ""
    fields: dict[str, str | None] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    structured: StructuredParse | None = None
    block: Block | None = None
    quality: Quality
    html: str | None = None
    warnings: list[str] = Field(default_factory=list)
    telemetry: dict[str, Any] = Field(default_factory=dict)
