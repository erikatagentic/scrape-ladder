"""Where a paid fetch would go. In this build it is a stub that is always off.

There is no setting, request field or environment variable that turns it on.
"""
from __future__ import annotations

DISABLED = "disabled: paid fetches are off in this build"


def paid_fetch(url: str) -> str:
    """Always returns the same disabled notice and never makes a request."""
    del url
    return DISABLED
