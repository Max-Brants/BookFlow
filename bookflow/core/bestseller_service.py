"""Low-traffic Dutch Bestseller 60 ingestion and suggestion queries.

This module deliberately has no Flask or runtime ownership.  A host registers
``sync_if_due`` as a durable-job callback and exposes ``dashboard`` / ``list_suggestions``
through its own authenticated API layer.  Keeping scraping, persistence and
queries here makes the once-a-day network behaviour easy to test.
"""

from __future__ import annotations

import html
import json
import re
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from bookflow.core.book_matcher import normalize_isbn
from bookflow.core.metadata_governance import record_provider_observation
from bookflow.download.network import get_proxies
from bookflow.metadata_providers import MetadataProviderTransientError

DEFAULT_BASE_URL = "https://www.debestseller60.nl"
DEFAULT_CHECK_INTERVAL = timedelta(hours=24)
DEFAULT_LEASE_DURATION = timedelta(minutes=10)
DEFAULT_MAX_HTML_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT: tuple[float, float] = (5.0, 20.0)
USER_AGENT = "BookFlow/0.1 (+https://github.com/bookflow/bookflow; Bestseller60 sync)"
DEFAULT_ENRICHMENT_BATCH_SIZE = 20
DEFAULT_PROVIDER_MIN_INTERVALS = {
    "hardcover": 1.1,  # Official limit: 60 requests/minute; keep a safety margin.
    "googlebooks": 0.2,  # Conservative 5 QPS; the exact project quota is console-managed.
    "openlibrary": 0.25,
}


@dataclass(frozen=True, slots=True)
class BestsellerListDefinition:
    key: str
    label: str
    path: str


LIST_DEFINITIONS: tuple[BestsellerListDefinition, ...] = (
    BestsellerListDefinition("overall", "Bestseller 60", "/"),
    BestsellerListDefinition("fiction", "Fictie", "/fictie"),
    BestsellerListDefinition("non_fiction", "Non-fictie", "/non-fictie"),
    BestsellerListDefinition("thriller", "Spanning", "/spannend"),
    BestsellerListDefinition("youth", "Jeugd", "/jeugd"),
    BestsellerListDefinition("cooking", "Culinair", "/koken"),
)
LIST_BY_KEY = {definition.key: definition for definition in LIST_DEFINITIONS}


class BestsellerSyncError(RuntimeError):
    """Raised after a failed sync has safely retained the previous snapshot."""


@dataclass(frozen=True, slots=True)
class BestsellerEntry:
    list_key: str
    rank: int
    isbn_13: str
    title: str
    author: str | None


@dataclass(frozen=True, slots=True)
class BestsellerSyncResult:
    outcome: str
    source_year: int | None = None
    source_week: int | None = None
    snapshot_id: int | None = None
    pages_fetched: int = 0


class _MetadataProvider(Protocol):
    name: str

    def is_available(self) -> bool: ...

    def search_by_isbn(self, isbn: str) -> Any | None: ...


CoverFetcher = Callable[[str, str], object]

_WEEK_PATTERN = re.compile(
    r"\bweek\s*(?P<week>\d{1,2})\s*[-–—]\s*(?P<year>20\d{2})\b",
    re.IGNORECASE,
)
_ISBN_CANDIDATE_PATTERN = re.compile(
    r"(?<!\d)(?:\d[\s-]?){9,12}[\dX](?!\d)",
    re.IGNORECASE,
)
_RANK_PATTERN = re.compile(r"^\s*(\d{1,3})\s*[.)]\s*")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_PUBLICATION_DATE_PATTERN = re.compile(r"\b\d{1,2}-\d{1,2}-(?P<year>20\d{2})\b")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _encode_time(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds")


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = _WHITESPACE_PATTERN.sub(" ", value).strip()
    return normalized or None


def _metadata_value(metadata: object, field: str, default: object = None) -> object:
    if isinstance(metadata, Mapping):
        return metadata.get(field, default)
    return getattr(metadata, field, default)


def _metadata_payload(metadata: object) -> dict[str, Any]:
    """Create a JSON-safe, provider-neutral metadata snapshot."""
    if hasattr(metadata, "__dataclass_fields__"):
        raw = asdict(cast(Any, metadata))
    elif isinstance(metadata, Mapping):
        raw = dict(metadata)
    else:
        raw = {
            field: _metadata_value(metadata, field)
            for field in (
                "provider",
                "provider_id",
                "title",
                "authors",
                "isbn_10",
                "isbn_13",
                "cover_url",
                "description",
                "publisher",
                "publish_year",
                "language",
                "genres",
                "source_url",
                "subtitle",
                "series_name",
                "series_position",
            )
        }
    # json.dumps is intentionally used as the final gate: an unusual provider
    # object must not make the weekly snapshot fail after its page was parsed.
    return json.loads(json.dumps(raw, ensure_ascii=False, default=str))


def _metadata_isbn_matches(metadata: object, isbn_13: str) -> bool:
    for field in ("isbn_13", "isbn13", "isbn_10", "isbn10"):
        normalized = normalize_isbn(_clean_text(_metadata_value(metadata, field)))
        if normalized is not None and normalized.isbn13 == isbn_13:
            return True
    return False


def _node_attribute_text(node: Tag, names: Iterable[str]) -> str | None:
    for name in names:
        value = node.attrs.get(name)
        if isinstance(value, list):
            value = " ".join(str(part) for part in value)
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return None


def _node_selector_text(node: Tag, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        selected = node.select_one(selector)
        if selected is not None:
            value = _clean_text(selected.get_text(" ", strip=True))
            if value:
                return value
    return None


def _extract_isbn(node: Tag) -> str | None:
    direct = _node_attribute_text(node, ("data-isbn", "data-isbn13", "isbn"))
    candidates = [direct] if direct else []
    candidates.extend(
        match.group(0) for match in _ISBN_CANDIDATE_PATTERN.finditer(node.get_text(" "))
    )
    for candidate in candidates:
        normalized = normalize_isbn(candidate)
        if normalized is not None and normalized.isbn13 is not None:
            return normalized.isbn13
    return None


def _extract_rank(node: Tag, fallback: int) -> int:
    for attribute in ("data-rank", "data-position", "data-place", "data-number"):
        value = _clean_text(node.attrs.get(attribute))
        if value and value.isdecimal() and int(value) > 0:
            return int(value)
    rank_node = node.select_one(".card__position, .rank, .position, .place, .number, [data-rank]")
    text = (
        rank_node.get_text(" ", strip=True)
        if rank_node is not None
        else node.get_text(" ", strip=True)
    )
    if text.isdecimal() and int(text) > 0:
        return int(text)
    match = _RANK_PATTERN.match(text)
    return int(match.group(1)) if match else fallback


def parse_bestseller_list(html_text: str, list_key: str) -> list[BestsellerEntry]:
    """Parse a rendered Bestseller60 list without requesting its history API.

    The source is server-rendered but has changed its CSS classes over time.
    The parser intentionally relies first on the Edition/history data attributes
    and only then on presentational selectors, while invalid ISBNs never enter
    persistence.
    """
    if list_key not in LIST_BY_KEY:
        raise ValueError(f"Unknown Bestseller list key: {list_key}")
    soup = BeautifulSoup(html_text, "html.parser")
    candidates = soup.select(
        "[y-use='Edition'], [data-url*='/history/'], [data-isbn], [data-isbn13], [class*='edition']"
    )
    entries: list[BestsellerEntry] = []
    seen_isbns: set[str] = set()
    seen_nodes: set[int] = set()
    for fallback_rank, node in enumerate(candidates, start=1):
        if id(node) in seen_nodes:
            continue
        seen_nodes.add(id(node))
        isbn_13 = _extract_isbn(node)
        if isbn_13 is None or isbn_13 in seen_isbns:
            continue
        title = _node_attribute_text(node, ("data-title", "data-book-title", "title"))
        title = title or _node_selector_text(
            node,
            (
                "[itemprop='name']",
                ".card__title",
                ".title",
                ".book-title",
                ".edition-title",
                "h1",
                "h2",
                "h3",
                "h4",
            ),
        )
        if title is None:
            continue
        author = _node_attribute_text(node, ("data-author", "data-authors"))
        author = author or _node_selector_text(
            node,
            (
                "[itemprop='author']",
                ".card__author",
                ".author",
                ".authors",
                ".auteur",
                ".schrijver",
            ),
        )
        entries.append(
            BestsellerEntry(
                list_key=list_key,
                rank=_extract_rank(node, fallback_rank),
                isbn_13=isbn_13,
                title=title,
                author=author,
            )
        )
        seen_isbns.add(isbn_13)
    return sorted(entries, key=lambda entry: (entry.rank, entry.title.casefold(), entry.isbn_13))


def parse_bestseller_metadata(
    html_text: str,
    *,
    source_url: str = DEFAULT_BASE_URL,
) -> dict[str, dict[str, object]]:
    """Extract source-owned edition metadata from one public trending page."""
    soup = BeautifulSoup(html_text, "html.parser")
    candidates = soup.select(
        "[y-use='Edition'], [data-url*='/history/'], [data-isbn], [data-isbn13], [class*='edition']"
    )
    parsed: dict[str, dict[str, object]] = {}
    for node in candidates:
        isbn_13 = _extract_isbn(node)
        if isbn_13 is None or isbn_13 in parsed:
            continue
        title = _node_attribute_text(node, ("data-title", "data-book-title", "title"))
        title = title or _node_selector_text(
            node, ("[itemprop='name']", ".card__title", ".book-title", ".title", "h2", "h3")
        )
        if title is None:
            continue
        author = _node_selector_text(
            node, ("[itemprop='author']", ".card__author", ".book-author", ".author")
        )
        description = _node_selector_text(
            node, (".card__summary", ".card__description", "[itemprop='description']")
        )
        image = node.select_one(".card__cover__img, [itemprop='image'], img")
        raw_cover = (
            _node_attribute_text(image, ("src", "data-src", "data-lazy-src"))
            if isinstance(image, Tag)
            else None
        )
        cover_url = urljoin(source_url, raw_cover) if raw_cover else None
        if cover_url and urlparse(cover_url).scheme not in {"http", "https"}:
            cover_url = None
        tags = [
            value
            for tag in node.select(".card__tags__tag")
            if (value := _clean_text(tag.get_text(" ", strip=True))) is not None
        ]
        publication_year: int | None = None
        publisher: str | None = None
        for value in tags:
            date_match = _PUBLICATION_DATE_PATTERN.search(value)
            if date_match is not None:
                publication_year = int(date_match.group("year"))
                continue
            folded = value.casefold()
            if (
                "isbn" in folded
                or "€" in value
                or folded in {"nieuw", "snelste stijger", "hoogste binnenkomer"}
            ):
                continue
            publisher = publisher or value
        parsed[isbn_13] = {
            "provider": "bestseller60",
            "provider_id": isbn_13,
            "title": title,
            "authors": [author] if author else [],
            "isbn_13": isbn_13,
            "cover_url": cover_url,
            "description": description,
            "publisher": publisher,
            "publish_year": publication_year,
            "language": "nl",
            "source_url": source_url,
        }
    return parsed


class BestsellerSuggestionService:
    """Persisted weekly suggestions with a 24-hour, low-transfer probe."""

    def __init__(
        self,
        database_path: str,
        *,
        providers: Iterable[_MetadataProvider] | Mapping[str, _MetadataProvider] = (),
        http_session: requests.Session | Any | None = None,
        cover_fetcher: CoverFetcher | None = None,
        base_url: str = DEFAULT_BASE_URL,
        check_interval: timedelta = DEFAULT_CHECK_INTERVAL,
        lease_duration: timedelta = DEFAULT_LEASE_DURATION,
        max_html_bytes: int = DEFAULT_MAX_HTML_BYTES,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        defer_enrichment: bool = False,
        source_metadata_fallback: bool = False,
        provider_min_intervals: Mapping[str, float] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if check_interval <= timedelta():
            raise ValueError("check_interval must be positive")
        if lease_duration <= timedelta():
            raise ValueError("lease_duration must be positive")
        if max_html_bytes < 32 * 1024:
            raise ValueError("max_html_bytes must be at least 32 KiB")
        self.database_path = database_path
        self._session = http_session or requests.Session()
        self._cover_fetcher = cover_fetcher
        self._base_url = base_url.rstrip("/")
        self._check_interval = check_interval
        self._lease_duration = lease_duration
        self._max_html_bytes = max_html_bytes
        self._timeout = timeout
        self._defer_enrichment = defer_enrichment
        self._source_metadata_fallback = source_metadata_fallback
        raw_providers = providers.values() if isinstance(providers, Mapping) else providers
        # The runtime passes providers in its configured preference order.  Do
        # not reorder that choice here: callers that want the documented
        # Google/OpenLibrary/Hardcover fallback simply pass that sequence.
        self._providers = tuple(raw_providers)
        self._lock = threading.RLock()
        self._rate_lock = threading.Lock()
        self._provider_next_call: dict[str, float] = {}
        self._source_cache_lock = threading.Lock()
        self._source_metadata_cache: dict[str, tuple[float, dict[str, dict[str, object]]]] = {}
        self._provider_min_intervals = dict(
            DEFAULT_PROVIDER_MIN_INTERVALS
            if provider_min_intervals is None
            else provider_min_intervals
        )
        self._sleep = sleep
        self._monotonic = monotonic

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @staticmethod
    def _provider_name(provider: object) -> str:
        return (
            _clean_text(getattr(provider, "name", None)) or provider.__class__.__name__.casefold()
        )

    def is_check_due(self, now: datetime | None = None) -> bool:
        checked_at = _encode_time(now or _utc_now())
        with self._connect() as connection:
            row = connection.execute(
                "SELECT next_check_at FROM bestseller_sync_state WHERE id = 1"
            ).fetchone()
        return row is None or str(row["next_check_at"]) <= checked_at

    def set_check_interval(self, check_interval: timedelta) -> None:
        """Apply a validated runtime interval before the next check is scheduled."""
        if check_interval <= timedelta():
            raise ValueError("check_interval must be positive")
        self._check_interval = check_interval

    def status(self) -> dict[str, Any]:
        """Return durable sync state for the administrator status view.

        State is deliberately read from SQLite rather than process-local job
        state, so it remains accurate after a restart and across workers.
        """
        with self._connect() as connection:
            state = connection.execute(
                "SELECT * FROM bestseller_sync_state WHERE id = 1"
            ).fetchone()
            active = connection.execute(
                """SELECT source_year, source_week, fetched_at, completed_at
                   FROM bestseller_snapshots
                   WHERE is_active = 1 AND status = 'completed'"""
            ).fetchone()
            last_success = connection.execute(
                """SELECT source_year, source_week, fetched_at, completed_at
                   FROM bestseller_snapshots
                   WHERE id = (SELECT last_success_snapshot_id
                               FROM bestseller_sync_state WHERE id = 1)"""
            ).fetchone()

        def snapshot_payload(row: sqlite3.Row | None) -> dict[str, Any] | None:
            if row is None:
                return None
            return {
                "year": int(row["source_year"]),
                "week": int(row["source_week"]),
                "fetched_at": row["fetched_at"],
                "completed_at": row["completed_at"],
            }

        return {
            "last_checked_at": state["last_checked_at"] if state else None,
            "last_success": snapshot_payload(last_success),
            "last_error": state["last_error"] if state else None,
            "next_check_at": state["next_check_at"] if state else None,
            "lease_expires_at": state["lease_expires_at"] if state else None,
            "active_snapshot": snapshot_payload(active),
        }

    def sync_if_due(
        self, *, worker_id: str, now: datetime | None = None, force: bool = False
    ) -> BestsellerSyncResult:
        """Run the daily probe, or return ``skipped`` when another worker owns it.

        Failures update the durable state but are re-raised as
        :class:`BestsellerSyncError`; this is important because a durable-job
        runtime must be allowed to apply its normal retry policy.
        """
        if not worker_id.strip():
            raise ValueError("worker_id must not be empty")
        check_at = now or _utc_now()
        if not self._claim(worker_id=worker_id, now=check_at, force=force):
            return BestsellerSyncResult("skipped")
        try:
            return self._sync_claimed(worker_id=worker_id, now=check_at)
        except Exception as exc:
            self._finish_failure(worker_id=worker_id, now=check_at, error=str(exc))
            if isinstance(exc, BestsellerSyncError):
                raise
            raise BestsellerSyncError("Bestseller 60 sync failed") from exc

    def _claim(self, *, worker_id: str, now: datetime, force: bool) -> bool:
        encoded_now = _encode_time(now)
        lease_until = _encode_time(now + self._lease_duration)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM bestseller_sync_state WHERE id = 1").fetchone()
            if row is None:
                connection.execute(
                    "INSERT INTO bestseller_sync_state (id, next_check_at, updated_at) VALUES (1, ?, ?)",
                    (encoded_now, encoded_now),
                )
                row = connection.execute(
                    "SELECT * FROM bestseller_sync_state WHERE id = 1"
                ).fetchone()
            if row is None:  # pragma: no cover - guarded by INSERT above
                connection.rollback()
                return False
            lease_busy = (
                row["lease_expires_at"] is not None and str(row["lease_expires_at"]) > encoded_now
            )
            due = row["last_checked_at"] is None or str(row["next_check_at"]) <= encoded_now
            if lease_busy or (not force and not due):
                connection.rollback()
                return False
            connection.execute(
                """UPDATE bestseller_sync_state
                   SET lease_owner = ?, lease_expires_at = ?, updated_at = ? WHERE id = 1""",
                (worker_id, lease_until, encoded_now),
            )
            connection.commit()
        return True

    def _sync_claimed(self, *, worker_id: str, now: datetime) -> BestsellerSyncResult:
        homepage, source_year, source_week, early_complete = self._read_homepage_probe()
        if early_complete:
            self._finish_success(
                worker_id=worker_id,
                now=now,
                source_year=source_year,
                source_week=source_week,
                snapshot_id=self._snapshot_id(source_year, source_week),
            )
            return BestsellerSyncResult("unchanged", source_year, source_week, pages_fetched=1)
        if homepage is None:  # pragma: no cover - _read_homepage_probe guarantees content otherwise
            raise BestsellerSyncError("Homepage body was unavailable")
        lists: dict[str, list[BestsellerEntry]] = {
            "overall": parse_bestseller_list(homepage, "overall")
        }
        if not lists["overall"]:
            raise BestsellerSyncError("Bestseller homepage did not contain valid ISBN entries")
        pages_fetched = 1
        for definition in LIST_DEFINITIONS[1:]:
            body = self._get_full_page(definition.path)
            genre_week = self._find_week(body.encode())
            if genre_week is not None and genre_week != (source_year, source_week):
                raise BestsellerSyncError(
                    f"{definition.key} is for week {genre_week[1]}-{genre_week[0]}, "
                    f"not {source_week}-{source_year}"
                )
            entries = parse_bestseller_list(body, definition.key)
            # A page that suddenly yields no books is much more likely to be a
            # markup/error page than a legitimate empty genre list.  Do not
            # replace the last complete snapshot in that case.
            if not entries:
                raise BestsellerSyncError(f"{definition.key} did not contain valid ISBN entries")
            lists[definition.key] = entries
            pages_fetched += 1
        linked_entries = self._enrich_entries(lists)
        snapshot_id = self._activate_snapshot(
            source_year=source_year,
            source_week=source_week,
            entries=linked_entries,
            fetched_at=now,
        )
        self._finish_success(
            worker_id=worker_id,
            now=now,
            source_year=source_year,
            source_week=source_week,
            snapshot_id=snapshot_id,
        )
        return BestsellerSyncResult("updated", source_year, source_week, snapshot_id, pages_fetched)

    def _read_homepage_probe(self) -> tuple[str | None, int, int, bool]:
        response = self._request("/", stream=True)
        buffer = bytearray()
        found: tuple[int, int] | None = None
        chunks = response.iter_content(chunk_size=4096)
        try:
            for chunk in chunks:
                if not chunk:
                    continue
                chunk_data = chunk.encode() if isinstance(chunk, str) else chunk
                buffer.extend(chunk_data)
                self._enforce_max_size(buffer)
                found = self._find_week(bytes(buffer))
                if found is None:
                    continue
                if self._has_complete_snapshot(*found):
                    return None, found[0], found[1], True
                break
            if found is None:
                raise BestsellerSyncError("Could not find the Bestseller week and year")
            for chunk in chunks:
                if not chunk:
                    continue
                chunk_data = chunk.encode() if isinstance(chunk, str) else chunk
                buffer.extend(chunk_data)
                self._enforce_max_size(buffer)
            return bytes(buffer).decode("utf-8", errors="replace"), found[0], found[1], False
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def _get_full_page(self, path: str) -> str:
        response = self._request(path, stream=True)
        buffer = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=16384):
                if not chunk:
                    continue
                chunk_data = chunk.encode() if isinstance(chunk, str) else chunk
                buffer.extend(chunk_data)
                self._enforce_max_size(buffer)
            return bytes(buffer).decode("utf-8", errors="replace")
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()

    def _request(self, path: str, *, stream: bool) -> Any:
        url = f"{self._base_url}{path}"
        try:
            response = self._session.get(
                url,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"},
                timeout=self._timeout,
                stream=stream,
                proxies=get_proxies(url),
            )
            response.raise_for_status()
        except (OSError, RuntimeError, TypeError, ValueError, requests.RequestException) as exc:
            raise BestsellerSyncError(f"Request to {path} failed") from exc
        else:
            return response

    def _enforce_max_size(self, buffer: bytearray) -> None:
        if len(buffer) > self._max_html_bytes:
            raise BestsellerSyncError("Bestseller HTML response exceeded the configured limit")

    @staticmethod
    def _find_week(body: bytes) -> tuple[int, int] | None:
        rendered = html.unescape(body.decode("utf-8", errors="replace"))
        match = _WEEK_PATTERN.search(rendered)
        if match is None:
            return None
        week = int(match.group("week"))
        year = int(match.group("year"))
        if not 1 <= week <= 53:
            return None
        return year, week

    def _has_complete_snapshot(self, source_year: int, source_week: int) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM bestseller_snapshots
                   WHERE source_year = ? AND source_week = ? AND status = 'completed'""",
                (source_year, source_week),
            ).fetchone()
        return row is not None

    def _snapshot_id(self, source_year: int, source_week: int) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id FROM bestseller_snapshots
                   WHERE source_year = ? AND source_week = ? AND status = 'completed'""",
                (source_year, source_week),
            ).fetchone()
        return int(row["id"]) if row is not None else None

    def _enrich_entries(
        self, lists: Mapping[str, list[BestsellerEntry]]
    ) -> list[tuple[BestsellerEntry, int]]:
        unique: dict[str, BestsellerEntry] = {}
        for entries in lists.values():
            for entry in entries:
                unique.setdefault(entry.isbn_13, entry)
        resolver = self._prepare_book if self._defer_enrichment else self._resolve_book
        linked = {isbn: resolver(entry) for isbn, entry in unique.items()}
        return [(entry, linked[entry.isbn_13]) for entries in lists.values() for entry in entries]

    def _prepare_book(self, entry: BestsellerEntry) -> int:
        """Persist source metadata and leave provider enrichment to the durable worker."""
        cached = self._enrichment(entry.isbn_13)
        if cached is not None and cached["book_id"] is not None:
            return int(cached["book_id"])
        existing_book_id = self._find_book_by_isbn(entry.isbn_13)
        if existing_book_id is not None:
            self._upsert_enrichment(
                isbn_13=entry.isbn_13,
                book_id=existing_book_id,
                state="complete",
                provider=None,
                cover_state="unknown",
                next_retry_at=None,
                error=None,
            )
            return existing_book_id
        book_id = self._upsert_book(entry, metadata=None, provider_name="bestseller60")
        self._upsert_enrichment(
            isbn_13=entry.isbn_13,
            book_id=book_id,
            state="transient_error",
            provider=None,
            cover_state="unknown",
            next_retry_at=_utc_now(),
            error="Queued for metadata enrichment",
        )
        return book_id

    def retry_incomplete_enrichment(self, *, now: datetime | None = None) -> int:
        """Make incomplete entries in the active snapshot immediately schedulable."""
        due_at = _encode_time(now or _utc_now())
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE bestseller_metadata_enrichment
                   SET next_retry_at = ?, updated_at = ?
                   WHERE metadata_state != 'complete'
                     AND isbn_13 IN (
                         SELECT DISTINCT e.isbn_13
                         FROM bestseller_entries e
                         JOIN bestseller_snapshots s ON s.id = e.snapshot_id
                         WHERE s.is_active = 1
                     )""",
                (due_at, due_at),
            )
        return cursor.rowcount

    def due_enrichment_batches(
        self,
        *,
        now: datetime | None = None,
        batch_size: int = DEFAULT_ENRICHMENT_BATCH_SIZE,
        limit: int = 100,
    ) -> list[tuple[list[str], str]]:
        """Return deterministic batches of active-snapshot ISBNs due for enrichment."""
        if batch_size < 1 or batch_size > 25:
            raise ValueError("batch_size must be between 1 and 25")
        if limit < 1:
            raise ValueError("limit must be positive")
        encoded_now = _encode_time(now or _utc_now())
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT DISTINCT m.isbn_13, m.next_retry_at
                   FROM bestseller_metadata_enrichment m
                   JOIN bestseller_entries e ON e.isbn_13 = m.isbn_13
                   JOIN bestseller_snapshots s ON s.id = e.snapshot_id
                   WHERE s.is_active = 1
                     AND m.metadata_state != 'complete'
                     AND m.next_retry_at IS NOT NULL
                     AND m.next_retry_at <= ?
                   ORDER BY m.next_retry_at, m.isbn_13
                   LIMIT ?""",
                (encoded_now, limit),
            ).fetchall()
        batches: list[tuple[list[str], str]] = []
        for offset in range(0, len(rows), batch_size):
            group = rows[offset : offset + batch_size]
            batches.append(
                (
                    [str(row["isbn_13"]) for row in group],
                    max(str(row["next_retry_at"]) for row in group),
                )
            )
        return batches

    def enrich_isbns(self, isbns: Iterable[str]) -> int:
        """Enrich one durable batch, retrying transient provider failures via its job."""
        requested = list(dict.fromkeys(str(value).strip() for value in isbns if str(value).strip()))
        if not requested or len(requested) > 25:
            raise ValueError("enrichment jobs require between 1 and 25 ISBNs")
        entries = self._entries_for_isbns(requested)
        pending = {
            isbn: entry
            for isbn, entry in entries.items()
            if (cached := self._enrichment(isbn)) is None
            or str(cached["metadata_state"]) != "complete"
        }
        if not pending:
            return 0
        matches, transient = self._lookup_metadata_batch(list(pending))
        transient_failures: list[str] = []
        for isbn, entry in pending.items():
            match = matches.get(isbn)
            if match is None:
                book_id = self._find_book_by_isbn(isbn)
                if book_id is None:
                    book_id = self._upsert_book(entry, metadata=None, provider_name="bestseller60")
                is_transient = isbn in transient
                self._upsert_enrichment(
                    isbn_13=isbn,
                    book_id=book_id,
                    state="transient_error" if is_transient else "missing",
                    provider=None,
                    cover_state="unknown",
                    next_retry_at=_utc_now()
                    + (timedelta(hours=24) if is_transient else timedelta(days=30)),
                    error="Temporary provider failure"
                    if is_transient
                    else "No provider ISBN match",
                )
                if is_transient:
                    transient_failures.append(isbn)
                continue
            metadata, provider_name = match
            book_id = self._upsert_book(entry, metadata=metadata, provider_name=provider_name)
            cover_state = self._warm_cover(
                isbn, _clean_text(_metadata_value(metadata, "cover_url"))
            )
            state = "complete"
            retry_at: datetime | None = None
            if cover_state == "missing":
                state = "partial"
                retry_at = _utc_now() + timedelta(days=30)
            elif cover_state == "transient_error":
                state = "partial"
                retry_at = _utc_now() + timedelta(hours=24)
            self._upsert_enrichment(
                isbn_13=isbn,
                book_id=book_id,
                state=state,
                provider=provider_name,
                cover_state=cover_state,
                next_retry_at=retry_at,
                error=None,
            )
        if transient_failures:
            raise BestsellerSyncError(
                f"Temporary metadata failure for {len(transient_failures)} ISBN(s)"
            )
        return len(pending)

    def _entries_for_isbns(self, isbns: list[str]) -> dict[str, BestsellerEntry]:
        placeholders = ",".join("?" for _ in isbns)
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT e.* FROM bestseller_entries e
                    JOIN bestseller_snapshots s ON s.id = e.snapshot_id
                    WHERE s.is_active = 1 AND e.isbn_13 IN ({placeholders})
                    GROUP BY e.isbn_13
                    ORDER BY e.id""",  # noqa: S608 - placeholders are generated, values stay bound
                isbns,
            ).fetchall()
        return {
            str(row["isbn_13"]): BestsellerEntry(
                list_key=str(row["list_key"]),
                rank=int(row["list_rank"]),
                isbn_13=str(row["isbn_13"]),
                title=str(row["source_title"]),
                author=_clean_text(row["source_author"]),
            )
            for row in rows
        }

    def _lookup_metadata_batch(
        self, isbns: list[str]
    ) -> tuple[dict[str, tuple[object, str]], set[str]]:
        unresolved = set(isbns)
        matches: dict[str, tuple[object, str]] = {}
        transient: set[str] = set()
        for provider in self._providers:
            if not unresolved:
                break
            available = getattr(provider, "is_available", None)
            if callable(available) and not available():
                continue
            provider_name = self._provider_name(provider)
            batch_lookup = getattr(provider, "search_by_isbns_for_enrichment", None)
            if callable(batch_lookup):
                candidates = sorted(unresolved)
                self._wait_for_provider(provider_name)
                try:
                    batch_matches = batch_lookup(candidates)
                except MetadataProviderTransientError:
                    transient.update(candidates)
                    continue
                except OSError, RuntimeError, TypeError, ValueError, requests.RequestException:
                    continue
                if not isinstance(batch_matches, Mapping):
                    continue
                for isbn, metadata in batch_matches.items():
                    if isbn in unresolved and _metadata_isbn_matches(metadata, isbn):
                        matches[isbn] = (metadata, provider_name)
                        unresolved.remove(isbn)
                continue
            strict_lookup = getattr(provider, "search_by_isbn_for_enrichment", None)
            lookup = strict_lookup if callable(strict_lookup) else provider.search_by_isbn
            candidates = sorted(unresolved)
            for index, isbn in enumerate(candidates):
                self._wait_for_provider(provider_name)
                try:
                    metadata = lookup(isbn)
                except MetadataProviderTransientError:
                    # A timeout, quota response, or 5xx usually affects the
                    # provider rather than one ISBN. Stop this provider for
                    # the current job and let the durable retry handle all
                    # remaining ISBNs instead of amplifying an outage.
                    transient.update(candidates[index:])
                    break
                except OSError, RuntimeError, TypeError, ValueError, requests.RequestException:
                    continue
                if metadata is not None and _metadata_isbn_matches(metadata, isbn):
                    matches[isbn] = (metadata, provider_name)
            unresolved.difference_update(matches)
        if self._source_metadata_fallback:
            source_candidates = unresolved | {
                isbn
                for isbn, (metadata, _provider_name) in matches.items()
                if not _clean_text(_metadata_value(metadata, "cover_url"))
            }
            for isbn, source_metadata in self._lookup_source_metadata(
                sorted(source_candidates)
            ).items():
                if not _metadata_isbn_matches(source_metadata, isbn):
                    continue
                if isbn in unresolved:
                    matches[isbn] = (source_metadata, "bestseller60")
                    unresolved.remove(isbn)
                    continue
                existing_metadata, provider_name = matches[isbn]
                merged = _metadata_payload(existing_metadata)
                for field, value in source_metadata.items():
                    if field in {"provider", "provider_id"}:
                        continue
                    if value is not None and not merged.get(field):
                        merged[field] = value
                matches[isbn] = (merged, provider_name)
        return matches, transient

    def _lookup_source_metadata(self, isbns: list[str]) -> dict[str, dict[str, object]]:
        """Use the public trending page once per ISBN as the final fallback."""
        claimed = self._claim_source_metadata_attempts(isbns)
        if not claimed:
            return {}
        by_path: dict[str, list[str]] = {}
        for isbn, path in claimed.items():
            by_path.setdefault(path, []).append(isbn)
        matches: dict[str, dict[str, object]] = {}
        outcomes: dict[str, tuple[str, str | None]] = {}
        for path, path_isbns in by_path.items():
            try:
                page_metadata = self._source_page_metadata(path)
            except BestsellerSyncError as exc:
                for isbn in path_isbns:
                    outcomes[isbn] = ("error", type(exc).__name__)
                continue
            for isbn in path_isbns:
                metadata = page_metadata.get(isbn)
                if metadata is None:
                    outcomes[isbn] = ("missing", None)
                    continue
                matches[isbn] = metadata
                outcomes[isbn] = ("found", None)
        self._finish_source_metadata_attempts(outcomes)
        return matches

    def _claim_source_metadata_attempts(self, isbns: list[str]) -> dict[str, str]:
        """Atomically reserve the sole source scrape allowed for each active ISBN."""
        placeholders = ",".join("?" for _ in isbns)
        priority = {definition.key: index for index, definition in enumerate(LIST_DEFINITIONS)}
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                f"""SELECT DISTINCT e.isbn_13, e.list_key
                    FROM bestseller_entries e
                    JOIN bestseller_snapshots s ON s.id = e.snapshot_id
                    WHERE s.is_active = 1 AND e.isbn_13 IN ({placeholders})
                    ORDER BY e.isbn_13, e.id""",  # noqa: S608 - generated placeholders only
                isbns,
            ).fetchall()
            preferred: dict[str, str] = {}
            selected_priority: dict[str, int] = {}
            for row in rows:
                isbn = str(row["isbn_13"])
                list_key = str(row["list_key"])
                candidate_priority = priority.get(list_key, len(priority))
                if candidate_priority < selected_priority.get(isbn, len(priority) + 1):
                    preferred[isbn] = LIST_BY_KEY[list_key].path
                    selected_priority[isbn] = candidate_priority
            now = _encode_time(_utc_now())
            claimed: dict[str, str] = {}
            connection.execute("BEGIN IMMEDIATE")
            for isbn, path in preferred.items():
                cursor = connection.execute(
                    """INSERT OR IGNORE INTO bestseller_source_metadata_attempts (
                        isbn_13, attempted_at, outcome, source_path
                    ) VALUES (?, ?, 'claimed', ?)""",
                    (isbn, now, path),
                )
                if cursor.rowcount == 1:
                    claimed[isbn] = path
            connection.commit()
        return claimed

    def _source_page_metadata(self, path: str) -> dict[str, dict[str, object]]:
        now = self._monotonic()
        with self._source_cache_lock:
            cached = self._source_metadata_cache.get(path)
            if cached is not None and now - cached[0] <= 300:
                return cached[1]
        source_url = f"{self._base_url}{path}"
        metadata = parse_bestseller_metadata(
            self._get_full_page(path),
            source_url=source_url,
        )
        with self._source_cache_lock:
            self._source_metadata_cache[path] = (self._monotonic(), metadata)
        return metadata

    def _finish_source_metadata_attempts(
        self, outcomes: Mapping[str, tuple[str, str | None]]
    ) -> None:
        if not outcomes:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                """UPDATE bestseller_source_metadata_attempts
                   SET outcome = ?, last_error = ?
                   WHERE isbn_13 = ? AND outcome = 'claimed'""",
                [(outcome, error, isbn) for isbn, (outcome, error) in outcomes.items()],
            )

    def _wait_for_provider(self, provider_name: str) -> None:
        interval = max(0.0, float(self._provider_min_intervals.get(provider_name, 0.0)))
        if interval <= 0:
            return
        with self._rate_lock:
            now = self._monotonic()
            reserved = max(now, self._provider_next_call.get(provider_name, now))
            self._provider_next_call[provider_name] = reserved + interval
            delay = reserved - now
        if delay > 0:
            self._sleep(delay)

    def _resolve_book(self, entry: BestsellerEntry) -> int:
        cached = self._enrichment(entry.isbn_13)
        if cached is not None and cached["book_id"] is not None:
            retry_at = cached["next_retry_at"]
            if cached["metadata_state"] == "complete" or (
                retry_at is not None and str(retry_at) > _encode_time(_utc_now())
            ):
                return int(cached["book_id"])

        existing_book_id = self._find_book_by_isbn(entry.isbn_13)
        # A Book not created by this feature already has its own durable
        # metadata cache.  It needs no provider call.  A linked enrichment row
        # is deliberately handled above so source-only/missing records do get
        # their scheduled retry.
        if existing_book_id is not None and cached is None:
            self._upsert_enrichment(
                isbn_13=entry.isbn_13,
                book_id=existing_book_id,
                state="complete",
                provider=None,
                cover_state="unknown",
                next_retry_at=None,
                error=None,
            )
            return existing_book_id

        metadata, provider_name, transient_error = self._lookup_metadata(entry.isbn_13)
        if metadata is None:
            book_id = self._upsert_book(entry, metadata=None, provider_name="bestseller60")
            state = "transient_error" if transient_error else "missing"
            retry = _utc_now() + (timedelta(hours=24) if transient_error else timedelta(days=30))
            self._upsert_enrichment(
                isbn_13=entry.isbn_13,
                book_id=book_id,
                state=state,
                provider=None,
                cover_state="unknown",
                next_retry_at=retry,
                error="All metadata providers failed"
                if transient_error
                else "No provider ISBN match",
            )
            return book_id

        book_id = self._upsert_book(
            entry,
            metadata=metadata,
            provider_name=provider_name or "bestseller60",
        )
        cover_state = self._warm_cover(
            entry.isbn_13, _clean_text(_metadata_value(metadata, "cover_url"))
        )
        metadata_state = "complete"
        retry_at: datetime | None = None
        if cover_state == "missing":
            metadata_state = "partial"
            retry_at = _utc_now() + timedelta(days=30)
        elif cover_state == "transient_error":
            metadata_state = "partial"
            retry_at = _utc_now() + timedelta(hours=24)
        self._upsert_enrichment(
            isbn_13=entry.isbn_13,
            book_id=book_id,
            state=metadata_state,
            provider=provider_name,
            cover_state=cover_state,
            next_retry_at=retry_at,
            error=None,
        )
        return book_id

    def _lookup_metadata(self, isbn_13: str) -> tuple[object | None, str | None, bool]:
        had_error = False
        for provider in self._providers:
            available = getattr(provider, "is_available", None)
            try:
                if callable(available) and not available():
                    continue
                metadata = provider.search_by_isbn(isbn_13)
            except OSError, RuntimeError, TypeError, ValueError, requests.RequestException:
                had_error = True
                continue
            if metadata is not None and _metadata_isbn_matches(metadata, isbn_13):
                return metadata, self._provider_name(provider), had_error
        return None, None, had_error

    def _find_book_by_isbn(self, isbn_13: str) -> int | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT book_id FROM book_identifiers
                   WHERE identifier_type = 'isbn13' AND identifier = ?
                   ORDER BY id LIMIT 1""",
                (isbn_13,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT id FROM books WHERE isbn_13 = ? ORDER BY id LIMIT 1", (isbn_13,)
                ).fetchone()
        return int(row[0]) if row is not None else None

    def _enrichment(self, isbn_13: str) -> sqlite3.Row | None:
        with self._connect() as connection:
            return connection.execute(
                "SELECT * FROM bestseller_metadata_enrichment WHERE isbn_13 = ?", (isbn_13,)
            ).fetchone()

    def _upsert_book(
        self, entry: BestsellerEntry, *, metadata: object | None, provider_name: str
    ) -> int:
        """Create one hidden canonical Book or only fill blanks on an existing one."""
        provider_id = _clean_text(_metadata_value(metadata, "provider_id")) if metadata else None
        provider_id = provider_id or entry.isbn_13
        provider_name = _clean_text(provider_name) or "bestseller60"
        candidate_title = _clean_text(_metadata_value(metadata, "title")) if metadata else None
        title = candidate_title or entry.title
        raw_authors = _metadata_value(metadata, "authors", []) if metadata else []
        authors = raw_authors if isinstance(raw_authors, (list, tuple)) else []
        author = (
            ", ".join(str(item).strip() for item in authors if str(item).strip()) or entry.author
        )
        metadata_json = _metadata_payload(metadata) if metadata is not None else {}
        metadata_json.setdefault("bestseller60", {"isbn_13": entry.isbn_13})
        raw_cover_url = _clean_text(_metadata_value(metadata, "cover_url")) if metadata else None
        # Store the same local proxy form used by catalog detail responses.
        # The cover warmer below still receives the provider's raw URL.
        from bookflow.core.utils import transform_cover_url

        stored_cover_url = transform_cover_url(raw_cover_url, f"bestseller60-{entry.isbn_13}")
        fields = {
            "author": _clean_text(author),
            "subtitle": _clean_text(_metadata_value(metadata, "subtitle")) if metadata else None,
            "publish_year": _metadata_value(metadata, "publish_year") if metadata else None,
            "cover_url": stored_cover_url,
            "series_name": _clean_text(_metadata_value(metadata, "series_name"))
            if metadata
            else None,
            "series_position": _metadata_value(metadata, "series_position") if metadata else None,
            "language": _clean_text(_metadata_value(metadata, "language")) if metadata else None,
        }
        now = _encode_time(_utc_now())
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """SELECT b.* FROM book_identifiers i JOIN books b ON b.id = i.book_id
                   WHERE i.identifier_type = 'isbn13' AND i.identifier = ? ORDER BY i.id LIMIT 1""",
                (entry.isbn_13,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    "SELECT * FROM books WHERE isbn_13 = ? ORDER BY id LIMIT 1", (entry.isbn_13,)
                ).fetchone()
            if row is None and metadata is not None:
                linked = connection.execute(
                    """SELECT b.* FROM book_provider_identifiers i JOIN books b ON b.id = i.book_id
                       WHERE i.provider = ? AND i.provider_book_id = ?""",
                    (provider_name.casefold(), provider_id),
                ).fetchone()
                row = linked
            if row is None:
                cursor = connection.execute(
                    """INSERT INTO books (
                        metadata_provider, provider_book_id, title, author, subtitle, publish_year,
                        isbn_13, cover_url, series_name, series_position, language, metadata_json,
                        catalog_visible, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
                    (
                        provider_name,
                        provider_id,
                        title,
                        fields["author"],
                        fields["subtitle"],
                        fields["publish_year"],
                        entry.isbn_13,
                        fields["cover_url"],
                        fields["series_name"],
                        fields["series_position"],
                        fields["language"],
                        json.dumps(metadata_json, ensure_ascii=False, sort_keys=True),
                        now,
                        now,
                    ),
                )
                if cursor.lastrowid is None:  # pragma: no cover - SQLite INSERT invariant
                    raise BestsellerSyncError("Could not create suggestion Book")
                book_id = int(cursor.lastrowid)
            else:
                book_id = int(row["id"])
                existing_json = self._decode_metadata_json(row["metadata_json"])
                for key, value in metadata_json.items():
                    existing_json.setdefault(key, value)
                updates: dict[str, object] = {
                    field: value
                    for field, value in fields.items()
                    if value is not None and (row[field] is None or str(row[field]).strip() == "")
                }
                if existing_json != self._decode_metadata_json(row["metadata_json"]):
                    updates["metadata_json"] = json.dumps(
                        existing_json, ensure_ascii=False, sort_keys=True
                    )
                if updates:
                    assignments = ", ".join(f"{field} = ?" for field in updates)
                    connection.execute(
                        f"UPDATE books SET {assignments}, updated_at = ? WHERE id = ?",  # noqa: S608
                        [*updates.values(), now, book_id],
                    )
            connection.execute(
                """INSERT OR IGNORE INTO book_identifiers (
                    book_id, identifier_type, identifier, source, confidence
                ) VALUES (?, 'isbn13', ?, 'bestseller60', 1.0)""",
                (book_id, entry.isbn_13),
            )
            if metadata is not None:
                connection.execute(
                    """INSERT OR IGNORE INTO book_provider_identifiers (
                        book_id, provider, provider_book_id
                    ) VALUES (?, ?, ?)""",
                    (book_id, provider_name.casefold(), provider_id),
                )
                provider_snapshot = dict(metadata_json)
                provider_snapshot.setdefault("provider", provider_name)
                provider_snapshot.setdefault("provider_id", provider_id)
                provider_snapshot.setdefault("title", title)
                for field, value in fields.items():
                    provider_snapshot.setdefault(field, value)
                record_provider_observation(
                    connection,
                    book_id=book_id,
                    source=provider_name,
                    source_identifier=provider_id,
                    payload=provider_snapshot,
                )
            connection.commit()
        return book_id

    @staticmethod
    def _decode_metadata_json(raw: object) -> dict[str, Any]:
        if not isinstance(raw, str):
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}

    def _warm_cover(self, isbn_13: str, cover_url: str | None) -> str:
        if not cover_url:
            return "missing"
        if self._cover_fetcher is None:
            return "unknown"
        try:
            result = self._cover_fetcher(f"bestseller60-{isbn_13}", cover_url)
        except OSError, RuntimeError, TypeError, ValueError, requests.RequestException:
            return "transient_error"
        return "complete" if result is not None and result is not False else "missing"

    def _upsert_enrichment(
        self,
        *,
        isbn_13: str,
        book_id: int,
        state: str,
        provider: str | None,
        cover_state: str,
        next_retry_at: datetime | None,
        error: str | None,
    ) -> None:
        now = _encode_time(_utc_now())
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO bestseller_metadata_enrichment (
                    isbn_13, book_id, metadata_state, metadata_provider, cover_state,
                    last_attempt_at, next_retry_at, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(isbn_13) DO UPDATE SET
                    book_id = excluded.book_id,
                    metadata_state = excluded.metadata_state,
                    metadata_provider = COALESCE(excluded.metadata_provider,
                        bestseller_metadata_enrichment.metadata_provider),
                    cover_state = excluded.cover_state,
                    last_attempt_at = excluded.last_attempt_at,
                    next_retry_at = excluded.next_retry_at,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at""",
                (
                    isbn_13,
                    book_id,
                    state,
                    provider,
                    cover_state,
                    now,
                    _encode_time(next_retry_at) if next_retry_at else None,
                    _clean_text(error),
                    now,
                ),
            )

    def _activate_snapshot(
        self,
        *,
        source_year: int,
        source_week: int,
        entries: list[tuple[BestsellerEntry, int]],
        fetched_at: datetime,
    ) -> int:
        if not entries:
            raise BestsellerSyncError("Cannot activate an empty snapshot")
        now = _encode_time(fetched_at)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT id, status FROM bestseller_snapshots WHERE source_year = ? AND source_week = ?",
                (source_year, source_week),
            ).fetchone()
            if existing is not None and str(existing["status"]) == "completed":
                connection.rollback()
                return int(existing["id"])
            if existing is not None:
                connection.execute(
                    "DELETE FROM bestseller_snapshots WHERE id = ?", (existing["id"],)
                )
            cursor = connection.execute(
                """INSERT INTO bestseller_snapshots (
                    source_year, source_week, status, is_active, fetched_at, completed_at
                ) VALUES (?, ?, 'completed', 0, ?, ?)""",
                (source_year, source_week, now, now),
            )
            if cursor.lastrowid is None:  # pragma: no cover - SQLite INSERT invariant
                raise BestsellerSyncError("Could not create suggestion snapshot")
            snapshot_id = int(cursor.lastrowid)
            for entry, book_id in entries:
                connection.execute(
                    """INSERT INTO bestseller_entries (
                        snapshot_id, list_key, list_rank, isbn_13, book_id, source_title, source_author
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot_id,
                        entry.list_key,
                        entry.rank,
                        entry.isbn_13,
                        book_id,
                        entry.title,
                        entry.author,
                    ),
                )
            connection.execute("UPDATE bestseller_snapshots SET is_active = 0 WHERE is_active = 1")
            connection.execute(
                "UPDATE bestseller_snapshots SET is_active = 1 WHERE id = ?", (snapshot_id,)
            )
            connection.commit()
        return snapshot_id

    def _finish_success(
        self,
        *,
        worker_id: str,
        now: datetime,
        source_year: int,
        source_week: int,
        snapshot_id: int | None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE bestseller_sync_state
                   SET last_checked_at = ?, next_check_at = ?, last_seen_year = ?, last_seen_week = ?,
                       last_success_snapshot_id = ?, last_error = NULL, lease_owner = NULL,
                       lease_expires_at = NULL, updated_at = ?
                   WHERE id = 1 AND lease_owner = ?""",
                (
                    _encode_time(now),
                    _encode_time(now + self._check_interval),
                    source_year,
                    source_week,
                    snapshot_id,
                    _encode_time(now),
                    worker_id,
                ),
            )

    def _finish_failure(self, *, worker_id: str, now: datetime, error: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """UPDATE bestseller_sync_state
                   SET last_checked_at = ?, next_check_at = ?, last_error = ?, lease_owner = NULL,
                       lease_expires_at = NULL, updated_at = ?
                   WHERE id = 1 AND lease_owner = ?""",
                (
                    _encode_time(now),
                    _encode_time(now + self._check_interval),
                    _clean_text(error) or "Bestseller sync failed",
                    _encode_time(now),
                    worker_id,
                ),
            )

    def dashboard(self, *, user_id: int | None, per_list_limit: int = 10) -> dict[str, Any]:
        limit = max(1, min(50, int(per_list_limit)))
        with self._connect() as connection:
            snapshot = connection.execute(
                "SELECT * FROM bestseller_snapshots WHERE is_active = 1 AND status = 'completed'"
            ).fetchone()
        if snapshot is None:
            return {"snapshot": None, "lists": []}
        lists = []
        for definition in LIST_DEFINITIONS:
            list_result = self._list_items(
                snapshot_id=int(snapshot["id"]),
                list_key=definition.key,
                user_id=user_id,
                offset=0,
                limit=limit,
            )
            lists.append(
                {
                    "key": definition.key,
                    "label": definition.label,
                    "items": list_result["items"],
                    "total": list_result["total"],
                }
            )
        return {
            "snapshot": {
                "year": int(snapshot["source_year"]),
                "week": int(snapshot["source_week"]),
                "fetched_at": snapshot["fetched_at"],
            },
            "lists": lists,
        }

    def list_suggestions(
        self, *, list_key: str, user_id: int | None, offset: int = 0, limit: int = 60
    ) -> dict[str, Any]:
        if list_key not in LIST_BY_KEY:
            raise ValueError("Unknown suggestion list")
        normalized_offset = max(0, int(offset))
        normalized_limit = max(1, min(100, int(limit)))
        with self._connect() as connection:
            snapshot = connection.execute(
                "SELECT * FROM bestseller_snapshots WHERE is_active = 1 AND status = 'completed'"
            ).fetchone()
        if snapshot is None:
            return {
                "list_key": list_key,
                "label": LIST_BY_KEY[list_key].label,
                "items": [],
                "total": 0,
                "offset": normalized_offset,
                "limit": normalized_limit,
                "snapshot": None,
            }
        result = self._list_items(
            snapshot_id=int(snapshot["id"]),
            list_key=list_key,
            user_id=user_id,
            offset=normalized_offset,
            limit=normalized_limit,
        )
        result.update(
            {
                "list_key": list_key,
                "label": LIST_BY_KEY[list_key].label,
                "snapshot": {
                    "year": int(snapshot["source_year"]),
                    "week": int(snapshot["source_week"]),
                    "fetched_at": snapshot["fetched_at"],
                },
            }
        )
        return result

    def _list_items(
        self, *, snapshot_id: int, list_key: str, user_id: int | None, offset: int, limit: int
    ) -> dict[str, Any]:
        with self._connect() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM bestseller_entries WHERE snapshot_id = ? AND list_key = ?",
                    (snapshot_id, list_key),
                ).fetchone()[0]
            )
            if user_id is None:
                rows = connection.execute(
                    """SELECT b.*, e.isbn_13 AS _suggestion_isbn,
                         0 AS in_library,
                         NULL AS request_status
                       FROM bestseller_entries e JOIN books b ON b.id = e.book_id
                       WHERE e.snapshot_id = ? AND e.list_key = ?
                       ORDER BY e.list_rank, e.id LIMIT ? OFFSET ?""",
                    (snapshot_id, list_key, limit, offset),
                ).fetchall()
            else:
                rows = connection.execute(
                    """SELECT b.*, e.isbn_13 AS _suggestion_isbn,
                         EXISTS(SELECT 1 FROM user_library ul
                                WHERE ul.book_id = b.id AND ul.user_id = ?) AS in_library,
                         (SELECT r.status FROM requests r WHERE r.book_id = b.id AND r.user_id = ?
                          ORDER BY r.created_at DESC, r.id DESC LIMIT 1) AS request_status
                       FROM bestseller_entries e JOIN books b ON b.id = e.book_id
                       WHERE e.snapshot_id = ? AND e.list_key = ?
                       ORDER BY e.list_rank, e.id LIMIT ? OFFSET ?""",
                    (user_id, user_id, snapshot_id, list_key, limit, offset),
                ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["metadata_json"] = self._decode_metadata_json(item.get("metadata_json"))
            item["in_library"] = bool(item["in_library"])
            if item.get("cover_url"):
                from bookflow.core.utils import transform_cover_url

                item["cover_url"] = transform_cover_url(
                    item["cover_url"], f"bestseller60-{item['_suggestion_isbn']}"
                )
            item.pop("_suggestion_isbn", None)
            # The rank deliberately stays internal: it orders a list but is
            # not part of the card contract or the response body.
            items.append(item)
        return {"items": items, "total": total, "offset": offset, "limit": limit}

    def mark_book_catalog_visible(self, book_id: int) -> bool:
        """Promote a suggestion-only Book when the normal request flow uses it."""
        if book_id < 1:
            raise ValueError("book_id must be positive")
        with self._connect() as connection:
            changed = connection.execute(
                "UPDATE books SET catalog_visible = 1, updated_at = ? WHERE id = ? AND catalog_visible = 0",
                (_encode_time(_utc_now()), book_id),
            ).rowcount
        return changed > 0
