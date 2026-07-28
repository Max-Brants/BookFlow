import requests

from bookflow.metadata_providers import (
    MetadataProviderTransientError,
    MetadataSearchOptions,
)
from bookflow.metadata_providers.applebooks import AppleBooksProvider


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Session:
    def __init__(self, payload):
        self.payload = payload
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.payload)


def _apple_payload():
    return {
        "resultCount": 1,
        "results": [
            {
                "trackId": 123456,
                "trackName": "De Cock en een dodelijk akkoord",
                "artistName": "A.C. Baantjer",
                "artworkUrl100": (
                    "https://is1-ssl.mzstatic.com/image/thumb/Publication/v4/example/100x100bb.jpg"
                ),
                "description": "Een rechercheur onderzoekt een zaak.",
                "genres": ["Detectives", "Boeken"],
                "releaseDate": "2021-04-15T07:00:00Z",
                "trackViewUrl": "https://books.apple.com/nl/book/id123456",
            }
        ],
    }


def test_applebooks_uses_dutch_store_and_400px_cover_without_product_link():
    provider = AppleBooksProvider()
    provider.session = _Session(_apple_payload())

    result = provider.search_paginated(MetadataSearchOptions(query="Baantjer", limit=20))

    assert len(result.books) == 1
    book = result.books[0]
    assert book.provider == "applebooks"
    assert book.provider_id == "123456"
    assert book.title == "De Cock en een dodelijk akkoord"
    assert book.authors == ["A.C. Baantjer"]
    assert book.cover_url is not None
    assert book.cover_url.endswith("/400x400bb.jpg")
    assert book.source_url is None
    assert book.publish_year == 2021

    params = provider.session.calls[0][1]["params"]
    assert params["country"] == "NL"
    assert params["media"] == "ebook"
    assert "trackViewUrl" not in params


def test_applebooks_combines_title_and_author_fields():
    provider = AppleBooksProvider()
    provider.session = _Session({"resultCount": 0, "results": []})

    provider.search(
        MetadataSearchOptions(
            query="ignored",
            fields={"title": "De Cock", "author": "Baantjer"},
        )
    )

    assert provider.session.calls[0][1]["params"]["term"] == "De Cock Baantjer"


def test_applebooks_isbn_lookup_normalizes_hyphens():
    provider = AppleBooksProvider()
    provider.session = _Session(_apple_payload())

    result = provider.search_by_isbn("978-90-1234-567-8")

    assert result is not None
    params = provider.session.calls[0][1]["params"]
    assert params["isbn"] == "9789012345678"
    assert provider.session.calls[0][0].endswith("/lookup")


def test_applebooks_rejects_invalid_id_without_request():
    provider = AppleBooksProvider()
    provider.session = _Session(_apple_payload())

    assert provider.get_book("../123") is None
    assert provider.session.calls == []


def test_applebooks_transient_failure_is_exposed_to_enrichment():
    class TimeoutSession:
        headers = {}

        def get(self, *_args, **_kwargs):
            raise requests.Timeout

    provider = AppleBooksProvider()
    provider.session = TimeoutSession()

    try:
        provider.search_by_isbn_for_enrichment("9789012345678")
    except MetadataProviderTransientError:
        pass
    else:
        raise AssertionError("Expected transient Apple Books failure")
