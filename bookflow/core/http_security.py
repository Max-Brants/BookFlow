"""HTTP trust-boundary helpers for reverse proxies and browser mutations."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable

type IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network

_FORWARDED_ENV_KEYS = (
    "HTTP_FORWARDED",
    "HTTP_X_FORWARDED_FOR",
    "HTTP_X_FORWARDED_HOST",
    "HTTP_X_FORWARDED_PORT",
    "HTTP_X_FORWARDED_PREFIX",
    "HTTP_X_FORWARDED_PROTO",
)


def parse_trusted_proxy_cidrs(value: object) -> tuple[IPNetwork, ...]:
    """Parse a comma-separated proxy allowlist, rejecting malformed entries."""
    if value is None:
        return ()
    if isinstance(value, str):
        raw_values = value.split(",")
    elif isinstance(value, Iterable):
        raw_values = list(value)
    else:
        raise TypeError("TRUSTED_PROXY_CIDRS must be a comma-separated string")

    networks: list[IPNetwork] = []
    for raw_value in raw_values:
        token = str(raw_value).strip()
        if not token:
            continue
        try:
            networks.append(ipaddress.ip_network(token, strict=False))
        except ValueError as exc:
            raise ValueError(f"Invalid trusted proxy CIDR: {token}") from exc
    return tuple(networks)


def is_trusted_proxy_address(remote_address: object, networks: Iterable[IPNetwork]) -> bool:
    """Return whether a peer address belongs to one configured proxy network."""
    try:
        address = ipaddress.ip_address(str(remote_address or "").strip())
    except ValueError:
        return False
    return any(address.version == network.version and address in network for network in networks)


def normalize_origin(value: object) -> str | None:
    """Normalize an HTTP(S) origin to scheme and authority only."""
    raw_value = str(value or "").strip()
    if not raw_value or raw_value == "null":
        return None
    parsed = urlsplit(raw_value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        return None
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"


def mutation_request_is_same_origin(
    *,
    origin: object,
    request_origin: object,
    sec_fetch_site: object,
    csrf_header: object,
    additional_origins: Iterable[str] = (),
) -> bool:
    """Validate browser provenance for an unsafe HTTP request."""
    normalized_request_origin = normalize_origin(request_origin)
    normalized_origin = normalize_origin(origin)
    allowed_origins = {
        candidate
        for candidate in (
            normalized_request_origin,
            *(normalize_origin(value) for value in additional_origins),
        )
        if candidate is not None
    }
    if normalized_origin is not None:
        return normalized_origin in allowed_origins

    fetch_site = str(sec_fetch_site or "").strip().lower()
    if fetch_site:
        return fetch_site in {"same-origin", "none"}

    # A non-simple custom header forces browsers to pass a CORS preflight.
    return str(csrf_header or "").strip() == "1"


class TrustedProxyMiddleware:
    """Reject spoofed forwarding headers before Werkzeug's ProxyFix sees them."""

    def __init__(self, app: Callable[..., Any], networks: Iterable[IPNetwork]) -> None:
        self._app = app
        self._networks = tuple(networks)

    def __call__(self, environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        forwarded_present = any(environ.get(key) for key in _FORWARDED_ENV_KEYS)
        trusted_peer = is_trusted_proxy_address(environ.get("REMOTE_ADDR"), self._networks)
        environ["bookflow.trusted_proxy_peer"] = trusted_peer
        if forwarded_present and not trusted_peer:
            payload = json.dumps(
                {
                    "error": "Untrusted proxy headers",
                    "code": "untrusted_proxy_headers",
                }
            ).encode()
            start_response(
                "400 Bad Request",
                [
                    ("Content-Type", "application/json"),
                    ("Content-Length", str(len(payload))),
                ],
            )
            return [payload]
        return self._app(environ, start_response)
