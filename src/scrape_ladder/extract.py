"""The three no-network extraction rungs: page metadata, selectors and main text."""
from __future__ import annotations

import re
from html import unescape
from typing import Any


def page_metadata(html: str, base_url: str) -> dict[str, Any]:
    """JSON-LD, OpenGraph and microdata, read with extruct."""
    import extruct

    try:
        data = extruct.extract(html, base_url=base_url, syntaxes=["json-ld", "opengraph", "microdata"],
                               uniform=True, errors="ignore")
    except Exception:  # noqa: BLE001 - broken markup means no metadata, never a crash
        return {"json-ld": [], "opengraph": [], "microdata": []}
    return {key: data.get(key, []) for key in ("json-ld", "opengraph", "microdata")}


def typed_items(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    """JSON-LD and microdata items that name a type (Product, Article and so on)."""
    items = []
    for key in ("json-ld", "microdata"):
        for item in metadata.get(key, []):
            if isinstance(item, dict) and item.get("@type"):
                items.append(item)
    return items


def select_fields(html: str, selectors: dict[str, str]) -> dict[str, str | None]:
    """CSS selectors with an optional `::attr(name)` suffix, read with selectolax."""
    from selectolax.lexbor import LexborHTMLParser

    tree = LexborHTMLParser(html)
    out: dict[str, str | None] = {}
    for name, selector in selectors.items():
        css, attr = selector, None
        match = re.match(r"(.+)::attr\(([^)]+)\)$", selector.strip())
        if match:
            css, attr = match.group(1), match.group(2)
        try:
            node = tree.css_first(css)
        except Exception:  # noqa: BLE001 - a bad selector is a miss, not a crash
            node = None
        if node is None:
            out[name] = None
        elif attr:
            out[name] = node.attributes.get(attr)
        else:
            out[name] = node.text(strip=True) or None
    return out


def main_text(html: str, base_url: str | None = None) -> str:
    """The page's main text, read with trafilatura."""
    import trafilatura

    text = trafilatura.extract(html, url=base_url, output_format="txt", include_links=False,
                               include_comments=False)
    return (text or "").strip()


def visible_text(html: str) -> str:
    """A rough read of the words a person would see. Used by the block check."""
    value = re.sub(r"<(script|style|noscript|template)[\s\S]*?</\1>", " ", html, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", unescape(value)).strip()
