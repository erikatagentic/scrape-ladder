"""A generic check that a folder is safe to publish.

It flags phone numbers, private IPv4 addresses, internal host names, chat webhook URLs,
key-shaped names that carry a value, and any email address outside the example domains.
It knows no names of people or companies, so it can ship in public.

    python scripts/check_public.py [folder]

Exit 0 when clean, 1 when anything is flagged.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", "build", "dist", "node_modules"}
ALLOWED_EMAILS = {"erik@erikhernal.com"}
SAFE_DOMAIN_SUFFIXES = ("example.com", "example.org", "example.net")
SAFE_TLDS = ("test", "example")

CHECKS: list[tuple[str, re.Pattern[str]]] = [
    ("phone number", re.compile(r"(?<![\w+.])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b(?![.:]?\d)")),
    ("private IP", re.compile(
        r"\b(?:10\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3})\.\d{1,3}\b(?!\.\d)"
    )),
    ("internal host", re.compile(r"\b[\w-]+\.(?:onrender\.com|fly\.dev)\b", re.I)),
    ("internal host", re.compile(r"\b(?:[\w-]+\.)*[\w-]*n8n[\w-]*\.[a-z][\w-]*(?:\.[a-z][\w-]*)*\b", re.I)),
    ("chat webhook", re.compile(r"hooks\.slack\.com", re.I)),
    ("key with a value", re.compile(
        r"\b[A-Za-z][A-Za-z0-9_]*_(?:KEY|TOKEN|SECRET|PASSWORD)\b\s*[:=]\s*['\"]?[^\s'\"#,)]{4,}",
        re.I,
    )),
]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")


def email_allowed(address: str, domain: str) -> bool:
    domain = domain.lower()
    if address.lower() in ALLOWED_EMAILS:
        return True
    if any(domain == s or domain.endswith("." + s) for s in SAFE_DOMAIN_SUFFIXES):
        return True
    return domain.rsplit(".", 1)[-1] in SAFE_TLDS


def scan_text(text: str) -> list[tuple[int, str, str]]:
    hits = []
    for number, line in enumerate(text.splitlines(), 1):
        for label, pattern in CHECKS:
            for match in pattern.finditer(line):
                shown = "[value hidden]" if label == "key with a value" else match.group(0)
                hits.append((number, label, shown))
        for match in EMAIL.finditer(line):
            if not email_allowed(match.group(0), match.group(1)):
                hits.append((number, "email", match.group(0)))
    return hits


def files_under(root: Path):
    for path in sorted(root.rglob("*")):
        if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            yield path


def scan_folder(root: Path) -> list[str]:
    found = []
    for path in files_under(root):
        data = path.read_bytes()
        if b"\0" in data[:8000]:
            continue  # binary
        rel = path.relative_to(root).as_posix()
        for number, label, shown in scan_text(data.decode("utf-8", errors="replace")):
            found.append(f"{rel}:{number}: {label}: {shown}")
    return found


def main(argv: list[str]) -> int:
    root = Path(argv[1] if len(argv) > 1 else Path(__file__).resolve().parent.parent)
    found = scan_folder(root)
    for line in found:
        print(line)
    print(f"check_public: {len(found)} finding(s) in {root.name}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
