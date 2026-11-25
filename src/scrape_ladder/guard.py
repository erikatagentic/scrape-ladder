"""The internal-address guard.

Every URL the ladder touches goes through `Guard.check` first: the page, every redirect
hop, robots.txt, the export URL and every request the headless browser makes. The check
refuses anything that isn't a public address, after DNS resolution, and hands back the
addresses it checked so the caller connects to exactly those (no second lookup that a
DNS answer could change in between).
"""
from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

Resolver = Callable[[str], list[str]]

_ALLOWED_SCHEMES = {"http", "https"}
_BLOCKED_NAMES = {"localhost", "localhost.localdomain"}
# Backslashes and control characters in the authority read differently across URL parsers.
_AMBIGUOUS = re.compile(r"[\\\x00-\x1f\x7f]")
# Cloud metadata services answer on this link-local address.
_METADATA_IPS = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}


class UnsafeURL(ValueError):
    """The URL points somewhere this service never fetches."""


def system_resolver(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        return []
    return sorted({info[4][0] for info in infos})


def ip_problem(address: str) -> str | None:
    """Why this address is refused, or None when it is a public address."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return "not an IP address"
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    if ip in _METADATA_IPS:
        return "a cloud metadata address"
    if ip.is_loopback:
        return "a loopback address"
    if ip.is_link_local:
        return "a link-local address"
    if ip.is_unspecified:
        return "an unspecified address"
    if ip.is_multicast:
        return "a multicast address"
    if ip.is_private:
        return "a private address"
    if ip.is_reserved or not ip.is_global:
        return "not a public address"
    return None


@dataclass(frozen=True)
class Target:
    url: str
    scheme: str
    host: str
    port: int
    addresses: tuple[str, ...]

    @property
    def host_header(self) -> str:
        default = 443 if self.scheme == "https" else 80
        return self.host if self.port == default else f"{self.host}:{self.port}"

    def pinned_url(self, address: str) -> str:
        """The same URL with the host swapped for an address the guard already checked."""
        parts = urlsplit(self.url)
        ip = ipaddress.ip_address(address.split("%", 1)[0])
        netloc = f"[{ip}]:{self.port}" if ip.version == 6 else f"{ip}:{self.port}"
        path = parts.path or "/"
        query = f"?{parts.query}" if parts.query else ""
        return f"{self.scheme}://{netloc}{path}{query}"


class Guard:
    def __init__(self, resolver: Resolver = system_resolver, trusted_hosts: frozenset[str] = frozenset()):
        self.resolver = resolver
        self.trusted_hosts = trusted_hosts

    def check(self, url: str) -> Target:
        raw = (url or "").strip()
        authority = re.match(r"^[A-Za-z][A-Za-z0-9+.-]*://([^/?#]*)", raw)
        if authority and _AMBIGUOUS.search(authority.group(1)):
            raise UnsafeURL("the address has a backslash or control character in it")
        try:
            parts = urlsplit(raw)
            port = parts.port
        except ValueError as exc:
            raise UnsafeURL("the URL can't be parsed") from exc
        scheme = parts.scheme.lower()
        if scheme not in _ALLOWED_SCHEMES:
            raise UnsafeURL(f"scheme {scheme or '(none)'} isn't http or https")
        if parts.username or parts.password:
            raise UnsafeURL("the URL carries a user name or password")
        host = (parts.hostname or "").lower().rstrip(".")
        if not host:
            raise UnsafeURL("the URL has no host")
        if not host.isascii():
            try:
                host = host.encode("idna").decode("ascii")
            except UnicodeError as exc:
                raise UnsafeURL("the host name isn't valid") from exc
        if port is None:
            port = 443 if scheme == "https" else 80
        trusted = host in self.trusted_hosts
        if not trusted and (host in _BLOCKED_NAMES or host.endswith(".localhost")):
            raise UnsafeURL(f"{host} is a local name")

        literal = _as_ip(host)
        if literal is not None:
            problem = None if trusted else ip_problem(literal)
            if problem:
                raise UnsafeURL(f"{host} is {problem}")
            return Target(raw, scheme, host, port, (literal,))

        addresses = self.resolver(host)
        if not addresses:
            raise UnsafeURL(f"{host} doesn't resolve")
        if not trusted:
            for address in addresses:
                problem = ip_problem(address)
                if problem:
                    raise UnsafeURL(f"{host} resolves to {problem}")
        return Target(raw, scheme, host, port, tuple(addresses))


def _as_ip(host: str) -> str | None:
    try:
        return str(ipaddress.ip_address(host.strip("[]")))
    except ValueError:
        return None
