"""The quality check every candidate answer must pass. HTTP 200 alone is not success."""
from __future__ import annotations

from pydantic import BaseModel, Field

from .blocks import Block


class Quality(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)


def check(
    *,
    status: int | None,
    block: Block | None,
    text: str | None = None,
    min_text_chars: int = 200,
    rows: int | None = None,
    fields: dict[str, str | None] | None = None,
    items: int | None = None,
) -> Quality:
    reasons: list[str] = []
    if not status or not 200 <= status < 300:
        reasons.append(f"status {status} isn't a 2xx")
    if block is not None and block.label != "ok" and (block.is_wall or block.label == "not_found"):
        reasons.append(f"{block.label}: {block.reason}")
    if text is not None and len(text.strip()) < min_text_chars:
        reasons.append(f"thin text: {len(text.strip())} characters, under {min_text_chars}")
    if rows is not None and rows < 1:
        reasons.append("no rows")
    if fields is not None:
        missing = sorted(name for name, value in fields.items() if not value)
        if missing:
            reasons.append(f"selectors matched nothing for: {', '.join(missing)}")
    if items is not None and items < 1:
        reasons.append("no typed JSON-LD or microdata item")
    return Quality(passed=not reasons, reasons=reasons)
