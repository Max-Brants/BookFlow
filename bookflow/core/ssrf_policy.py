"""Central URL and DNS policy for outbound provider requests."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlsplit


class SSRFPolicyError(ValueError):
    """Raised when an outbound URL violates the configured trust policy."""


@dataclass(frozen=True, slots=True)
class ValidatedOutboundURL:
    """URL plus its validated, pinned public address set."""

    url: str
    hostname: str
    addresses: tuple[str, ...]


Resolver = Callable[[str, int], Iterable[Any]]


def _is_public_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(address.is_global)


def validate_outbound_url(
    url: str,
    *,
    allowed_hosts: Iterable[str],
    resolver: Resolver = socket.getaddrinfo,
) -> ValidatedOutboundURL:
    """Validate scheme, authority, host allowlist, and every DNS answer."""
    parsed = urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise SSRFPolicyError("Only HTTP(S) URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise SSRFPolicyError("URL credentials are not allowed")
    if not parsed.hostname:
        raise SSRFPolicyError("URL hostname is required")

    hostname = parsed.hostname.rstrip(".").casefold()
    normalized_hosts = {str(host).rstrip(".").casefold() for host in allowed_hosts}
    if hostname not in normalized_hosts:
        raise SSRFPolicyError("URL hostname is not allowlisted")

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None:
        addresses = (literal,)
    else:
        try:
            answers = resolver(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        except OSError as exc:
            raise SSRFPolicyError("URL hostname could not be resolved") from exc
        resolved: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
        for answer in answers:
            try:
                sockaddr = answer[4]
                resolved.add(ipaddress.ip_address(str(sockaddr[0])))
            except (IndexError, TypeError, ValueError) as exc:
                raise SSRFPolicyError("Resolver returned an invalid address") from exc
        addresses = tuple(sorted(resolved, key=lambda value: (value.version, int(value))))

    if not addresses:
        raise SSRFPolicyError("URL hostname returned no addresses")
    if any(not _is_public_address(address) for address in addresses):
        raise SSRFPolicyError("URL hostname resolved to a non-public address")

    return ValidatedOutboundURL(
        url=url,
        hostname=hostname,
        addresses=tuple(str(address) for address in addresses),
    )


def validate_redirect(
    previous: ValidatedOutboundURL,
    location: str,
    *,
    allowed_hosts: Iterable[str],
    resolver: Resolver = socket.getaddrinfo,
) -> ValidatedOutboundURL:
    """Resolve and fully revalidate a redirect target."""
    return validate_outbound_url(
        urljoin(previous.url, location),
        allowed_hosts=allowed_hosts,
        resolver=resolver,
    )
