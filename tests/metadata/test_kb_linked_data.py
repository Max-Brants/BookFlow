import pytest
import requests

from bookflow.metadata_providers import MetadataProviderTransientError, MetadataSearchOptions
from bookflow.metadata_providers.dbnl import DbnlProvider
from bookflow.metadata_providers.kb_nbt import KbNbtProvider


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, bindings):
        self._bindings = bindings

    def raise_for_status(self):
        return None

    def json(self):
        return {"results": {"bindings": self._bindings}}


class _Session:
    def __init__(self, bindings):
        self.bindings = bindings
        self.headers = {}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response(self.bindings)


def _value(value, value_type="literal"):
    return {"type": value_type, "value": value}


def test_kb_nbt_parses_and_deduplicates_linked_data_rows():
    provider = KbNbtProvider()
    provider.session = _Session(
        [
            {
                "book": _value("http://data.bibliotheken.nl/id/nbt/p436820889", "uri"),
                "title": _value("De droomfabriek : roman"),
                "author": _value("http://data.bibliotheken.nl/id/thes/p304382582", "uri"),
                "authorName": _value("Gerwin van der Werf"),
                "isbn": _value("9789025472429"),
                "language": _value("nl"),
                "genreName": _value("Romans"),
                "date": _value("2022"),
            },
            {
                "book": _value("http://data.bibliotheken.nl/id/nbt/p436820889", "uri"),
                "title": _value("De droomfabriek : roman"),
                "author": _value("http://data.bibliotheken.nl/id/thes/p304382582", "uri"),
                "authorName": _value("Gerwin van der Werf"),
                "isbn": _value("9789025472429"),
                "language": _value("nl"),
                "genreName": _value("Romans"),
                "date": _value("2022"),
            },
        ]
    )

    result = provider.search_paginated(MetadataSearchOptions(query="droomfabriek", limit=20))

    assert len(result.books) == 1
    book = result.books[0]
    assert book.provider == "kb_nbt"
    assert book.provider_id == "p436820889"
    assert book.title == "De droomfabriek : roman"
    assert book.authors == ["Gerwin van der Werf"]
    assert book.isbn_13 == "9789025472429"
    assert book.language == "nl"
    assert book.publish_year == 2022
    assert book.genres == ["Romans"]


def test_dbnl_uses_public_author_graph_and_source_url():
    provider = DbnlProvider()
    provider.session = _Session(
        [
            {
                "book": _value("http://data.bibliotheken.nl/id/dbnlt/mult001maxh15", "uri"),
                "title": _value("Max Havelaar. Deel 1. Tekst"),
                "author": _value("http://data.bibliotheken.nl/id/dbnla/mult001", "uri"),
                "authorName": _value("Multatuli"),
                "url": _value(
                    "https://www.dbnl.org/titels/titel.php?id=mult001maxh15",
                    "uri",
                ),
            }
        ]
    )

    result = provider.search(MetadataSearchOptions(query="Max Havelaar"))

    assert len(result) == 1
    assert result[0].provider == "dbnl"
    assert result[0].authors == ["Multatuli"]
    assert result[0].language == "nl"
    assert result[0].source_url == ("https://www.dbnl.org/titels/titel.php?id=mult001maxh15")


def test_kb_nbt_isbn_lookup_normalizes_hyphens():
    provider = KbNbtProvider()
    session = _Session(
        [
            {
                "book": _value("http://data.bibliotheken.nl/id/nbt/p436820889", "uri"),
                "title": _value("De droomfabriek : roman"),
                "isbn": _value("9789025472429"),
            }
        ]
    )
    provider.session = session

    result = provider.search_by_isbn("978-90-254-7242-9")

    assert result is not None
    assert result.isbn_13 == "9789025472429"
    sent_query = session.calls[0][1]["params"]["query"]
    assert '"9789025472429"' in sent_query


def test_dbnl_does_not_claim_isbn_support():
    provider = DbnlProvider()
    provider.session = _Session([])

    assert provider.search_by_isbn("9789025472429") is None
    assert provider.session.calls == []


def test_invalid_provider_id_is_rejected_without_request():
    provider = KbNbtProvider()
    provider.session = _Session([])

    assert provider.get_book("../other-graph") is None
    assert provider.session.calls == []


def test_temporary_endpoint_failure_is_exposed_to_enrichment():
    class TimeoutSession:
        headers = {}

        def get(self, *_args, **_kwargs):
            raise requests.Timeout

    provider = KbNbtProvider()
    provider.session = TimeoutSession()

    with pytest.raises(MetadataProviderTransientError):
        provider.search_by_isbn_for_enrichment("9789025472429")
