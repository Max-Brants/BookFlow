from __future__ import annotations

import pytest

from bookflow.core.ssrf_policy import SSRFPolicyError, validate_outbound_url, validate_redirect


def _resolver(*addresses: str):
    return lambda _host, _port: [(2, 1, 6, "", (address, 443)) for address in addresses]


def test_allows_allowlisted_host_when_every_dns_answer_is_public():
    result = validate_outbound_url(
        "https://books.example/releases",
        allowed_hosts={"books.example"},
        resolver=_resolver("93.184.216.34"),
    )

    assert result.hostname == "books.example"
    assert result.addresses == ("93.184.216.34",)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://user:password@books.example/",
        "https://other.example/",
    ],
)
def test_rejects_invalid_scheme_credentials_and_unlisted_hosts(url):
    with pytest.raises(SSRFPolicyError):
        validate_outbound_url(
            url,
            allowed_hosts={"books.example"},
            resolver=_resolver("93.184.216.34"),
        )


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"])
def test_rejects_any_private_or_special_dns_answer(address):
    with pytest.raises(SSRFPolicyError, match="non-public"):
        validate_outbound_url(
            "https://books.example/",
            allowed_hosts={"books.example"},
            resolver=_resolver("93.184.216.34", address),
        )


def test_redirect_is_resolved_and_revalidated():
    previous = validate_outbound_url(
        "https://books.example/start",
        allowed_hosts={"books.example"},
        resolver=_resolver("93.184.216.34"),
    )

    with pytest.raises(SSRFPolicyError, match="not allowlisted"):
        validate_redirect(
            previous,
            "https://internal.example/admin",
            allowed_hosts={"books.example"},
            resolver=_resolver("93.184.216.34"),
        )
