"""Block detection: is the fetched page the real page, or something standing in for it?

A challenge page, a login wall or a rate-limit notice can all come back as HTTP 200,
so the status code alone never decides success.
"""
from __future__ import annotations

from pydantic import BaseModel

from .extract import visible_text

# Pages that stand between the visitor and the content. This build reports them and stops.
WALLS = {"challenge", "login_wall", "rate_limited"}

_CHALLENGE = (
    "verify you are human", "are you a robot", "checking your browser", "captcha",
    "unusual traffic from your", "access denied", "access temporarily blocked",
    "we paused your visit", "access to this site has been limited",
)
_LOGIN = (
    "sign in to continue", "log in to continue", "please sign in", "please log in",
    "login required", "authentication required", "members only",
)
_RATE = ("too many requests", "rate limit exceeded", "slow down")
_JS = ("enable javascript", "requires javascript", "javascript is disabled", "turn on javascript")

# Long, content-rich pages that merely mention one of the phrases above are real pages.
_CONTENT_RICH_CHARS = 1500


class Block(BaseModel):
    label: str = "ok"
    reason: str = "looks like the real page"

    @property
    def is_wall(self) -> bool:
        return self.label in WALLS


def classify(html: str, status: int | None, *, min_text_chars: int = 200) -> Block:
    raw = (html or "").lower()
    text = visible_text(html or "")
    hay = text.lower()
    rich = len(text) >= _CONTENT_RICH_CHARS and (status is None or status < 400)

    if status == 429 or (not rich and any(p in hay for p in _RATE)):
        return Block(label="rate_limited", reason="the site says too many requests")
    if not rich and any(p in hay for p in _CHALLENGE):
        return Block(label="challenge", reason="a challenge page stands in front of the content")
    if not rich and (any(p in hay for p in _LOGIN) or 'type="password"' in raw):
        return Block(label="login_wall", reason="the content sits behind a login")
    if status in {401, 403}:
        return Block(label="challenge", reason=f"the site refused the request with {status}")
    if status == 404 or (status == 200 and "page not found" in hay and len(text) < 400):
        return Block(label="not_found", reason="the page wasn't found")
    if len(text) < min_text_chars and (any(p in hay for p in _JS) or "<script" in raw):
        return Block(label="js_shell", reason="the page builds its content with JavaScript")
    if len(text) < min_text_chars:
        return Block(label="thin", reason=f"only {len(text)} characters of visible text")
    return Block()
