"""Shared client for the KB Linked Open Data metadata providers."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, ClassVar

import requests

if TYPE_CHECKING:
    from collections.abc import Iterable

from bookflow.core.cache import cacheable
from bookflow.core.logger import setup_logger
from bookflow.download.network import get_proxies, get_ssl_verify
from bookflow.metadata_providers import (
    BookMetadata,
    MetadataProvider,
    MetadataProviderRateLimitError,
    MetadataProviderTransientError,
    MetadataSearchOptions,
    SearchField,
    SearchResult,
    SearchType,
    SortOrder,
    TextSearchField,
)

logger = setup_logger(__name__)

KB_SPARQL_ENDPOINT = (
    "https://api.bibliotheken.nl/datasets/KB/Production/services/Production-VTS/sparql"
)
_SCHEMA = "http://schema.org/"
_DCTERMS = "http://purl.org/dc/terms#"
_YEAR_PATTERN = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")
_ISBN_10_PATTERN = re.compile(r"^[0-9]{9}[0-9X]$")
_ISBN_13_PATTERN = re.compile(r"^[0-9]{13}$")
_PROVIDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9._~-]+$")


def _sparql_literal(value: str) -> str:
    """Return a safely escaped SPARQL string literal."""
    return json.dumps(value, ensure_ascii=False)


def _binding_value(binding: dict[str, Any], key: str) -> str:
    value = binding.get(key)
    if not isinstance(value, dict):
        return ""
    raw = value.get("value")
    return str(raw).strip() if raw is not None else ""


def _literal_or_name(binding: dict[str, Any], value_key: str, name_key: str) -> str:
    name = _binding_value(binding, name_key)
    if name:
        return name
    value = binding.get(value_key)
    if not isinstance(value, dict) or value.get("type") == "uri":
        return ""
    return _binding_value(binding, value_key)


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _raise_for_retryable_status(response: requests.Response) -> None:
    if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
        retry_after_raw = response.headers.get("Retry-After")
        try:
            retry_after = float(retry_after_raw) if retry_after_raw else None
        except ValueError:
            retry_after = None
        raise MetadataProviderRateLimitError(
            "KB Linked Data rate limit exceeded",
            retry_after=retry_after,
        )
    if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
        raise MetadataProviderTransientError(
            f"KB Linked Data service returned HTTP {response.status_code}"
        )


class KbLinkedDataProvider(MetadataProvider):
    """Base provider for a single public graph in the KB SPARQL service."""

    graph_uri: ClassVar[str]
    author_graph_uri: ClassVar[str]
    resource_prefix: ClassVar[str]
    website_url: ClassVar[str]
    supports_isbn: ClassVar[bool] = False
    default_language: ClassVar[str | None] = None
    search_fields: ClassVar[tuple[SearchField, ...]] = (
        TextSearchField(
            key="author",
            label="Author",
            description="Search by author name",
        ),
        TextSearchField(
            key="title",
            label="Title",
            description="Search by book title",
        ),
    )
    supported_sorts: ClassVar[tuple[SortOrder, ...]] = (SortOrder.RELEVANCE,)

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/sparql-results+json",
                "User-Agent": "BookFlow metadata provider",
            }
        )

    def is_available(self) -> bool:
        """The public KB service does not require credentials."""
        return True

    def search(self, options: MetadataSearchOptions) -> list[BookMetadata]:
        """Search this provider's KB graph."""
        if options.search_type == SearchType.ISBN:
            result = self.search_by_isbn(options.query)
            return [result] if result else []
        return self.search_paginated(options).books

    def search_paginated(self, options: MetadataSearchOptions) -> SearchResult:
        """Search with deterministic page/limit handling."""
        requested_limit = max(1, min(int(options.limit), 100))
        query_options = replace(options, limit=requested_limit + 1)
        query = self._build_search_query(query_options)
        cache_key = (
            f"{options.query}:{options.search_type.value}:{options.language}:"
            f"{requested_limit}:{options.page}:{sorted(options.fields.items())}"
        )
        try:
            books = self._search_cached(cache_key, query)
        except (MetadataProviderTransientError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("%s search failed: %s", self.display_name, exc)
            books = []

        has_more = len(books) > requested_limit
        visible_books = books[:requested_limit]
        return SearchResult(
            books=visible_books,
            page=max(1, int(options.page)),
            total_found=0,
            has_more=has_more,
        )

    @cacheable(ttl_key="METADATA_CACHE_SEARCH_TTL", ttl_default=300, key_prefix="kb-lod:search")
    def _search_cached(self, cache_key: str, query: str) -> list[BookMetadata]:
        """Run and parse a cacheable search query."""
        del cache_key
        search_bindings = self._execute_query(query)
        resource_uris = _unique(_binding_value(row, "book") for row in search_bindings)
        if not resource_uris:
            return []
        details = self._execute_query(self._build_details_for_resources(resource_uris))
        parsed = self._parse_bindings(details)
        order = {resource_uri: index for index, resource_uri in enumerate(resource_uris)}
        return sorted(
            parsed,
            key=lambda book: order.get(f"{self.resource_prefix}{book.provider_id}", len(order)),
        )

    def get_book(self, book_id: str) -> BookMetadata | None:
        """Fetch one record by its provider-local identifier."""
        normalized_id = self._normalize_provider_id(book_id)
        if not normalized_id:
            return None
        query = self._build_record_query(f"{self.resource_prefix}{normalized_id}")
        try:
            books = self._get_book_cached(normalized_id, query)
        except (MetadataProviderTransientError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("%s record lookup failed: %s", self.display_name, exc)
            return None
        return books[0] if books else None

    @cacheable(ttl_key="METADATA_CACHE_BOOK_TTL", ttl_default=600, key_prefix="kb-lod:book")
    def _get_book_cached(self, book_id: str, query: str) -> list[BookMetadata]:
        del book_id
        return self._parse_bindings(self._execute_query(query))

    def search_by_isbn(self, isbn: str) -> BookMetadata | None:
        """Look up an ISBN when the underlying graph provides ISBN values."""
        try:
            return self.search_by_isbn_for_enrichment(isbn)
        except (MetadataProviderTransientError, RuntimeError, TypeError, ValueError) as exc:
            logger.warning("%s ISBN lookup failed: %s", self.display_name, exc)
            return None

    def search_by_isbn_for_enrichment(self, isbn: str) -> BookMetadata | None:
        """Strict ISBN lookup that surfaces temporary failures to background workers."""
        if not self.supports_isbn:
            return None
        normalized_isbn = re.sub(r"[^0-9Xx]", "", isbn).upper()
        if not (
            _ISBN_10_PATTERN.fullmatch(normalized_isbn)
            or _ISBN_13_PATTERN.fullmatch(normalized_isbn)
        ):
            return None
        query = self._build_isbn_query(normalized_isbn)
        books = self._parse_bindings(self._execute_query(query))
        return books[0] if books else None

    def _execute_query(self, query: str) -> list[dict[str, Any]]:
        try:
            response = self.session.get(
                KB_SPARQL_ENDPOINT,
                params={"query": query},
                timeout=20,
                proxies=get_proxies(KB_SPARQL_ENDPOINT),
                verify=get_ssl_verify(KB_SPARQL_ENDPOINT),
            )
            _raise_for_retryable_status(response)
            response.raise_for_status()
            payload = response.json()
        except MetadataProviderTransientError:
            raise
        except requests.Timeout as exc:
            raise MetadataProviderTransientError("KB Linked Data request timed out") from exc
        except requests.RequestException as exc:
            raise MetadataProviderTransientError("KB Linked Data request failed") from exc
        except (TypeError, ValueError) as exc:
            raise MetadataProviderTransientError("KB Linked Data returned invalid JSON") from exc

        results = payload.get("results", {}) if isinstance(payload, dict) else {}
        bindings = results.get("bindings", []) if isinstance(results, dict) else []
        if not isinstance(bindings, list):
            raise MetadataProviderTransientError("KB Linked Data returned an invalid result set")
        return [item for item in bindings if isinstance(item, dict)]

    def _build_search_query(self, options: MetadataSearchOptions) -> str:
        query_text = options.query.strip()
        author = str(options.fields.get("author", "")).strip()
        title = str(options.fields.get("title", "")).strip()

        filters: list[str] = []
        author_required = False
        if author:
            filters.append(self._contains_expression("?authorNameSearch", "?author", author))
            author_required = True
        if title:
            filters.append(self._contains_expression("?title", None, title))
        if not filters and query_text:
            if options.search_type == SearchType.AUTHOR:
                filters.append(
                    self._contains_expression("?authorNameSearch", "?author", query_text)
                )
                author_required = True
            elif options.search_type == SearchType.TITLE:
                filters.append(self._contains_expression("?title", None, query_text))
            else:
                filters.append(self._contains_expression("?title", None, query_text))

        language = (options.language or "").strip()
        language_pattern = ""
        if language:
            language_pattern = (
                "    ?book schema:inLanguage ?languageSearch .\n"
                f"    FILTER(LCASE(STR(?languageSearch)) = LCASE({_sparql_literal(language)}))\n"
            )

        author_pattern = "    ?book schema:author ?author .\n" if author_required else ""
        author_search_join = (
            f"""
      OPTIONAL {{
        GRAPH <{self.author_graph_uri}> {{ ?author schema:name ?authorNameSearch . }}
      }}
"""
            if author_required
            else ""
        )
        filter_clause = f"  FILTER({' && '.join(filters)})\n" if filters else ""
        limit = max(1, min(int(options.limit), 101))
        offset = (max(1, int(options.page)) - 1) * max(1, limit - 1)

        query = f"""
PREFIX schema: <{_SCHEMA}>
SELECT DISTINCT ?book ?title
FROM <{self.graph_uri}>
{"FROM NAMED <" + self.author_graph_uri + ">" if author_required else ""}
WHERE {{
  ?book schema:name ?title .
{author_pattern}{language_pattern}
{author_search_join}
{filter_clause}}}
LIMIT {limit}
OFFSET {offset}
"""  # noqa: S608 - values and literals are validated/escaped above
        return query  # noqa: RET504 - separate assignment carries the S608 justification

    def _build_record_query(self, resource_uri: str) -> str:
        selection = f"""
  {{
    BIND(<{resource_uri}> AS ?book)
    GRAPH <{self.graph_uri}> {{ ?book schema:name ?title . }}
  }}
"""
        return self._details_query(selection)

    def _build_details_for_resources(self, resource_uris: list[str]) -> str:
        safe_resources = [
            resource_uri
            for resource_uri in resource_uris
            if resource_uri.startswith(self.resource_prefix)
            and self._normalize_provider_id(resource_uri)
        ]
        values = " ".join(f"<{resource_uri}>" for resource_uri in safe_resources)
        selection = f"""
  VALUES ?book {{ {values} }}
  GRAPH <{self.graph_uri}> {{ ?book schema:name ?title . }}
"""
        return self._details_query(selection)

    def _build_isbn_query(self, isbn: str) -> str:
        selection = f"""
  {{
    SELECT DISTINCT ?book ?title WHERE {{
      GRAPH <{self.graph_uri}> {{
        ?book schema:name ?title ;
              schema:isbn ?isbnSearch .
        FILTER(REPLACE(UCASE(STR(?isbnSearch)), "[^0-9X]", "") = {_sparql_literal(isbn)})
      }}
    }}
    LIMIT 5
  }}
"""
        return self._details_query(selection)

    def _details_query(self, selection: str) -> str:
        return f"""
PREFIX schema: <{_SCHEMA}>
PREFIX dcterms: <{_DCTERMS}>
SELECT ?book ?title ?author ?authorName ?isbn ?language ?description
       ?genre ?series ?date ?publisherName ?url
WHERE {{
{selection}
  GRAPH <{self.graph_uri}> {{
    OPTIONAL {{ ?book schema:author ?author . }}
    OPTIONAL {{ ?book schema:isbn ?isbn . }}
    OPTIONAL {{ ?book schema:inLanguage ?language . }}
    OPTIONAL {{ ?book schema:description ?description . }}
    OPTIONAL {{ ?book schema:genre ?genre . }}
    OPTIONAL {{ ?book schema:isPartOf ?series . }}
    OPTIONAL {{ ?book dcterms:issued ?date . }}
    OPTIONAL {{ ?book schema:datePublished ?date . }}
    OPTIONAL {{ ?book schema:dateCreated ?date . }}
    OPTIONAL {{ ?book schema:url ?url . }}
    OPTIONAL {{
      ?book schema:publication ?publication .
      OPTIONAL {{ ?publication schema:startDate ?date . }}
      OPTIONAL {{
        ?publication schema:publishedBy ?publisher .
        OPTIONAL {{ ?publisher schema:name ?publisherName . }}
      }}
    }}
  }}
  OPTIONAL {{
    GRAPH <{self.author_graph_uri}> {{ ?author schema:name ?authorName . }}
  }}
}}
"""

    @staticmethod
    def _contains_expression(primary: str, fallback: str | None, value: str) -> str:
        literal = _sparql_literal(value)
        if fallback:
            candidate = f'COALESCE(STR({primary}), STR({fallback}), "")'
        else:
            candidate = f"STR({primary})"
        return f"CONTAINS(LCASE({candidate}), LCASE({literal}))"

    def _parse_bindings(self, bindings: list[dict[str, Any]]) -> list[BookMetadata]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for binding in bindings:
            resource_uri = _binding_value(binding, "book")
            title = _binding_value(binding, "title")
            if resource_uri and title:
                grouped.setdefault(resource_uri, []).append(binding)

        books: list[BookMetadata] = []
        for resource_uri, rows in grouped.items():
            book = self._parse_record(resource_uri, rows)
            if book:
                books.append(book)
        return books

    def _parse_record(
        self,
        resource_uri: str,
        rows: list[dict[str, Any]],
    ) -> BookMetadata | None:
        title = _binding_value(rows[0], "title")
        provider_id = self._normalize_provider_id(resource_uri)
        if not title or not provider_id:
            return None

        authors = _unique(_literal_or_name(row, "author", "authorName") for row in rows)
        isbns = _unique(_binding_value(row, "isbn").replace("-", "").upper() for row in rows)
        languages = _unique(_binding_value(row, "language") for row in rows)
        descriptions = _unique(_binding_value(row, "description") for row in rows)
        publishers = _unique(_binding_value(row, "publisherName") for row in rows)
        genres = _unique(_literal_or_name(row, "genre", "genreName") for row in rows)
        series_values = _unique(_literal_or_name(row, "series", "seriesName") for row in rows)
        dates = _unique(_binding_value(row, "date") for row in rows)
        urls = _unique(_binding_value(row, "url") for row in rows)

        isbn_10 = next((value for value in isbns if _ISBN_10_PATTERN.fullmatch(value)), None)
        isbn_13 = next((value for value in isbns if _ISBN_13_PATTERN.fullmatch(value)), None)
        publish_year = None
        for date in dates:
            match = _YEAR_PATTERN.search(date)
            if match:
                publish_year = int(match.group(1))
                break

        return BookMetadata(
            provider=self.name,
            provider_id=provider_id,
            title=title,
            provider_display_name=self.display_name,
            authors=authors,
            isbn_10=isbn_10,
            isbn_13=isbn_13,
            description=descriptions[0] if descriptions else None,
            publisher=publishers[0] if publishers else None,
            publish_year=publish_year,
            language=languages[0] if languages else self.default_language,
            genres=genres[:5],
            source_url=urls[0] if urls else resource_uri,
            search_title=title,
            search_author=authors[0] if authors else None,
            series_name=series_values[0] if series_values else None,
        )

    def _normalize_provider_id(self, value: str) -> str:
        normalized = str(value).strip()
        if normalized.startswith(self.resource_prefix):
            normalized = normalized.removeprefix(self.resource_prefix)
        elif "/" in normalized or "\\" in normalized:
            return ""
        normalized = normalized.rstrip("/")
        return normalized if _PROVIDER_ID_PATTERN.fullmatch(normalized) else ""


def test_kb_connection(provider: KbLinkedDataProvider) -> dict[str, Any]:
    """Run a cheap public-endpoint connectivity check for settings UI actions."""
    query = f"""
PREFIX schema: <{_SCHEMA}>
SELECT ?book WHERE {{
  GRAPH <{provider.graph_uri}> {{ ?book schema:name ?title . }}
}}
LIMIT 1
"""
    try:
        provider._execute_query(query)
    except (MetadataProviderTransientError, RuntimeError, TypeError, ValueError) as exc:
        return {"success": False, "message": f"Connection failed: {exc!s}"}
    return {
        "success": True,
        "message": f"Successfully connected to {provider.display_name}",
    }
