"""Tests for HTTP trust-boundary helpers."""

import json

import pytest
from werkzeug.test import Client
from werkzeug.wrappers import Response

from bookflow.core.http_security import (
    TrustedProxyMiddleware,
    is_trusted_proxy_address,
    mutation_request_is_same_origin,
    normalize_origin,
    parse_trusted_proxy_cidrs,
)


def test_parse_trusted_proxy_cidrs_and_match_addresses():
    networks = parse_trusted_proxy_cidrs("127.0.0.1, 10.20.0.0/16, 2001:db8::/32")

    assert is_trusted_proxy_address("127.0.0.1", networks)
    assert is_trusted_proxy_address("10.20.4.8", networks)
    assert is_trusted_proxy_address("2001:db8::5", networks)
    assert not is_trusted_proxy_address("10.21.0.1", networks)
    assert not is_trusted_proxy_address("not-an-ip", networks)


def test_parse_trusted_proxy_cidrs_rejects_invalid_values():
    with pytest.raises(ValueError, match="Invalid trusted proxy CIDR"):
        parse_trusted_proxy_cidrs("127.0.0.1, definitely-invalid")


def test_trusted_proxy_middleware_rejects_spoofed_forwarding_headers():
    app = TrustedProxyMiddleware(
        lambda environ, start_response: Response("ok")(environ, start_response),
        parse_trusted_proxy_cidrs("10.0.0.0/8"),
    )
    response = Client(app, Response).get(
        "/",
        headers={"X-Forwarded-For": "203.0.113.2"},
        environ_overrides={"REMOTE_ADDR": "192.0.2.10"},
    )

    assert response.status_code == 400
    assert json.loads(response.data)["code"] == "untrusted_proxy_headers"


def test_trusted_proxy_middleware_allows_configured_peer():
    app = TrustedProxyMiddleware(
        lambda environ, start_response: Response("ok")(environ, start_response),
        parse_trusted_proxy_cidrs("10.0.0.0/8"),
    )
    response = Client(app, Response).get(
        "/",
        headers={"X-Forwarded-For": "203.0.113.2"},
        environ_overrides={"REMOTE_ADDR": "10.2.3.4"},
    )

    assert response.status_code == 200


@pytest.mark.parametrize(
    ("origin", "fetch_site", "csrf_header", "expected"),
    [
        ("https://books.example", "", "", True),
        ("https://evil.example", "same-origin", "1", False),
        ("", "same-origin", "", True),
        ("", "cross-site", "1", False),
        ("", "", "1", True),
        ("", "", "", False),
    ],
)
def test_mutation_request_provenance(origin, fetch_site, csrf_header, expected):
    assert (
        mutation_request_is_same_origin(
            origin=origin,
            request_origin="https://books.example",
            sec_fetch_site=fetch_site,
            csrf_header=csrf_header,
        )
        is expected
    )


def test_normalize_origin_rejects_credentials_and_paths():
    assert normalize_origin("HTTPS://Books.Example/") == "https://books.example"
    assert normalize_origin("https://user:pass@books.example") is None
    assert normalize_origin("https://books.example/path") is None
