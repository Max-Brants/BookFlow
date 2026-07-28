"""Apple Books metadata provider using Apple's public Search API."""

from __future__ import annotations

import re
from contextlib import suppress
from http import HTTPStatus
from typing import Any, ClassVar

import requests

from bookflow.core.cache import cacheable
from bookflow.core.logger import setup_logger
from bookflow.core.settings_registry import (
    ActionButton,
    CheckboxField,
    HeadingField,
    SettingsField,
    register_settings,
)
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
    register_provider,
)

logger = setup_logger(__name__)

APPLE_SEARCH_BASE_URL = "https://itunes.apple.com"
_ARTWORK_SIZE_PATTERN = re.compile(r"/\d+x\d+bb(?=[.-])", re.IGNORECASE)
_ISBN_PATTERN = re.compile(r"^(?:[0-9]{9}[0-9X]|[0-9]{13})$")


@register_provider("applebooks")
class AppleBooksProvider(MetadataProvider):
    """Search the Dutch Apple Books storefront without credentials."""

    name = "applebooks"
    display_name = "Apple Books"
    requires_auth = False
    supported_sorts: ClassVar[tuple[SortOrder, ...]] = (SortOrder.RELEVANCE,)
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

    def __init__(self, country: str = "NL") -> None:
        self.country = str(country).strip().upper() or "NL"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": "BookFlow metadata provider",
            }
        )

    def is_available(self) -> bool:
        """Apple's public search endpoint does not require credentials."""
        return True

    def search(self, options: MetadataSearchOptions) -> list[BookMetadata]:
        """Search the configured Apple Books media type."""
        if options.search_type == SearchType.ISBN:
            result = self.search_by_isbn(options.query)
            return [result] if result else []
        return self.search_paginated(options).books

    def search_paginated(self, options: MetadataSearchOptions) -> SearchResult:
        """Search results, using Apple's maximum result window for local paging."""
        page = max(1, int(options.page))
        page_size = max(1, min(int(options.limit), 200))
        requested_count = min(page * page_size + 1, 200)
        query = self._build_query(options)
        cache_key = (
            f"{query}:{self.country}:ebook:{page_size}:{page}:{sorted(options.fields.items())}"
        )

        try:
            payload = self._search_cached(cache_key, query, requested_count)
        except MetadataProviderTransientError as exc:
            logger.warning("Apple Books search failed: %s", exc)
            return SearchResult(books=[], page=page)

        parsed = self._parse_results(payload)
        offset = (page - 1) * page_size
        visible = parsed[offset : offset + page_size]
        total_found = self._result_count(payload)
        return SearchResult(
            books=visible,
            page=page,
            total_found=total_found,
            has_more=offset + len(visible) < total_found and offset + len(visible) < 200,
        )

    @cacheable(
        ttl_key="METADATA_CACHE_SEARCH_TTL",
        ttl_default=300,
        key_prefix="applebooks:search",
    )
    def _search_cached(
        self,
        cache_key: str,
        query: str,
        requested_count: int,
    ) -> dict[str, Any]:
        del cache_key
        return self._make_request(
            "/search",
            {
                "term": query,
                "country": self.country,
                "media": "ebook",
                "entity": "ebook",
                "limit": requested_count,
            },
        )

    @cacheable(
        ttl_key="METADATA_CACHE_BOOK_TTL",
        ttl_default=600,
        key_prefix="applebooks:book",
    )
    def get_book(self, book_id: str) -> BookMetadata | None:
        """Look up one Apple Store item ID."""
        normalized_id = str(book_id).strip()
        if not normalized_id.isdigit():
            return None
        try:
            payload = self._make_request(
                "/lookup",
                {
                    "id": normalized_id,
                    "country": self.country,
                    "entity": "ebook",
                },
            )
        except MetadataProviderTransientError as exc:
            logger.warning("Apple Books lookup failed: %s", exc)
            return None
        books = self._parse_results(payload)
        return books[0] if books else None

    @cacheable(
        ttl_key="METADATA_CACHE_BOOK_TTL",
        ttl_default=600,
        key_prefix="applebooks:isbn",
    )
    def search_by_isbn(self, isbn: str) -> BookMetadata | None:
        """Look up an ebook by ISBN through Apple's public lookup endpoint."""
        try:
            return self.search_by_isbn_for_enrichment(isbn)
        except MetadataProviderTransientError as exc:
            logger.warning("Apple Books ISBN lookup failed: %s", exc)
            return None

    def search_by_isbn_for_enrichment(self, isbn: str) -> BookMetadata | None:
        """ISBN lookup that keeps transient failures visible to background jobs."""
        normalized_isbn = re.sub(r"[^0-9Xx]", "", isbn).upper()
        if not _ISBN_PATTERN.fullmatch(normalized_isbn):
            return None
        payload = self._make_request(
            "/lookup",
            {
                "isbn": normalized_isbn,
                "country": self.country,
                "entity": "ebook",
            },
        )
        books = self._parse_results(payload)
        return books[0] if books else None

    def _make_request(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{APPLE_SEARCH_BASE_URL}{endpoint}"
        try:
            response = self.session.get(
                url,
                params=params,
                timeout=15,
                proxies=get_proxies(url),
                verify=get_ssl_verify(url),
            )
            self._raise_for_status(response)
            response.raise_for_status()
            payload = response.json()
        except MetadataProviderRateLimitError, MetadataProviderTransientError:
            raise
        except requests.Timeout as exc:
            raise MetadataProviderTransientError("Apple Books request timed out") from exc
        except requests.RequestException as exc:
            raise MetadataProviderTransientError("Apple Books request failed") from exc
        except (TypeError, ValueError) as exc:
            raise MetadataProviderTransientError("Apple Books returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise MetadataProviderTransientError("Apple Books returned an invalid response")
        return payload

    @staticmethod
    def _raise_for_status(response: requests.Response) -> None:
        if response.status_code == HTTPStatus.TOO_MANY_REQUESTS:
            retry_after_raw = response.headers.get("Retry-After")
            retry_after = None
            if retry_after_raw is not None:
                with suppress(ValueError):
                    retry_after = float(retry_after_raw)
            raise MetadataProviderRateLimitError(
                "Apple Books rate limit exceeded",
                retry_after=retry_after,
            )
        if response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
            raise MetadataProviderTransientError(
                f"Apple Books service returned HTTP {response.status_code}"
            )

    @staticmethod
    def _build_query(options: MetadataSearchOptions) -> str:
        title = str(options.fields.get("title", "")).strip()
        author = str(options.fields.get("author", "")).strip()
        parts = [part for part in (title, author) if part]
        return " ".join(parts) if parts else options.query.strip()

    def _parse_results(self, payload: dict[str, Any]) -> list[BookMetadata]:
        results = payload.get("results", [])
        if not isinstance(results, list):
            return []
        books: list[BookMetadata] = []
        for item in results:
            if isinstance(item, dict):
                parsed = self._parse_item(item)
                if parsed:
                    books.append(parsed)
        return books

    def _parse_item(self, item: dict[str, Any]) -> BookMetadata | None:
        provider_id = item.get("trackId") or item.get("collectionId")
        title = item.get("trackName") or item.get("collectionName")
        if provider_id is None or not title:
            return None

        artwork = item.get("artworkUrl100") or item.get("artworkUrl60")
        cover_url = self._cover_url(str(artwork)) if artwork else None
        author = str(item.get("artistName", "")).strip()
        publish_year = None
        release_date = str(item.get("releaseDate", ""))
        if len(release_date) >= 4:
            with suppress(ValueError):
                publish_year = int(release_date[:4])

        genres = item.get("genres", [])
        if not isinstance(genres, list):
            genres = []

        return BookMetadata(
            provider=self.name,
            provider_id=str(provider_id),
            title=str(title),
            provider_display_name=self.display_name,
            authors=[author] if author else [],
            cover_url=cover_url,
            cover_aspect="square",
            description=item.get("description"),
            publish_year=publish_year,
            genres=[str(genre) for genre in genres[:5] if genre],
            source_url=None,
            search_title=str(title),
            search_author=author or None,
        )

    @staticmethod
    def _cover_url(url: str, size: int = 400) -> str:
        """Upgrade Apple's standard artwork URL to a square local-test cover."""
        return _ARTWORK_SIZE_PATTERN.sub(f"/{size}x{size}bb", url)

    @staticmethod
    def _result_count(payload: dict[str, Any]) -> int:
        value = payload.get("resultCount", 0)
        try:
            return max(0, int(value))
        except TypeError, ValueError:
            return 0


def _test_applebooks_connection(
    _current_values: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = AppleBooksProvider()
    try:
        payload = provider._make_request(
            "/search",
            {
                "term": "Baantjer",
                "country": "NL",
                "media": "ebook",
                "entity": "ebook",
                "limit": 1,
            },
        )
    except MetadataProviderTransientError as exc:
        return {"success": False, "message": f"Connection failed: {exc!s}"}
    if provider._result_count(payload) < 1:
        return {
            "success": True,
            "message": "Connected to Apple Books; the test search returned no results",
        }
    return {"success": True, "message": "Successfully connected to Apple Books"}


@register_settings(
    "applebooks",
    "Apple Books",
    icon="book",
    order=56,
    group="metadata_providers",
)
def applebooks_settings() -> list[SettingsField]:
    """Apple Books metadata provider settings."""
    return [
        HeadingField(
            key="applebooks_heading",
            title="Apple Books",
            description=(
                "Search e-books in the Dutch Apple Books storefront. No API key is required. "
                "For this local provider, Apple product links are not stored."
            ),
        ),
        CheckboxField(
            key="APPLEBOOKS_ENABLED",
            label="Enable Apple Books",
            description="Use Apple Books as a metadata provider",
            default=False,
        ),
        ActionButton(
            key="test_connection",
            label="Test Connection",
            description="Verify the public Apple Books search service is accessible",
            style="primary",
            callback=_test_applebooks_connection,
        ),
    ]
