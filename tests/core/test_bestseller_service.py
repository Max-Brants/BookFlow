"""Contract tests for low-transfer Bestseller 60 suggestions."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from bookflow.core.bestseller_service import (
    BestsellerSuggestionService,
    parse_bestseller_list,
    parse_bestseller_metadata,
)
from bookflow.core.user_db import UserDB
from bookflow.metadata_providers import MetadataProviderTransientError


def _isbn(number: int) -> str:
    """Return a deterministic, checksum-valid ISBN-13 for a fixture number."""
    first_twelve = f"978000{number:06d}"[-12:]
    total = sum(
        int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(first_twelve)
    )
    return f"{first_twelve}{(10 - total % 10) % 10}"


def _page(*, week: int, year: int, records: list[tuple[int, str, str, str]]) -> bytes:
    cards = "".join(
        f"""<article y-use="Edition" data-url="/history/{position}">
              <span class="card__position">{position}</span>
              <h2 class="card__title">{title}</h2>
              <p class="card__author">{author}</p>
              <p>ISBN: {isbn}</p>
            </article>"""
        for position, isbn, title, author in records
    )
    return f"<html><body><p>Week {week} - {year}</p>{cards}</body></html>".encode()


def _metadata_page(*, isbn: str) -> bytes:
    return f"""<html><body><p>Week 30 - 2026</p>
      <article class="card" y-use="Edition">
        <span class="card__position">1</span>
        <div class="card__cover">
          <img class="card__cover__img" src="https://covers.example/{isbn}.jpg">
        </div>
        <div class="card__author"><a>Bron auteur</a></div>
        <div class="card__title">Bron titel</div>
        <div class="card__summary">Korte bronbeschrijving.</div>
        <div class="card__tags">
          <div class="card__tags__tag">Testuitgever</div>
          <div class="card__tags__tag">€ 19,99</div>
          <div class="card__tags__tag">ISBN {isbn}</div>
          <div class="card__tags__tag">01-07-2026</div>
        </div>
      </article>
    </body></html>""".encode()


class _Response:
    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = iter(chunks)
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, *, chunk_size: int) -> Any:
        del chunk_size
        return self._chunks

    def close(self) -> None:
        self.closed = True


class _SingleIteratorResponse(_Response):
    """Model a streamed response whose unread tail belongs to its first iterator."""

    def __init__(self, chunks: list[bytes]) -> None:
        super().__init__(chunks)
        self.iter_content_calls = 0

    def iter_content(self, *, chunk_size: int) -> Any:
        del chunk_size
        self.iter_content_calls += 1
        if self.iter_content_calls > 1:
            return iter(())
        return self._chunks


class _Session:
    def __init__(self, pages: dict[str, list[list[bytes]]]) -> None:
        self._pages = {path: list(responses) for path, responses in pages.items()}
        self.calls: list[str] = []
        self.responses: list[_Response] = []

    def get(self, url: str, **_kwargs: object) -> _Response:
        path = url.removeprefix("https://example.test") or "/"
        self.calls.append(path)
        chunks = self._pages[path].pop(0)
        response = _Response(chunks)
        self.responses.append(response)
        return response


class _Provider:
    name = "googlebooks"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def is_available(self) -> bool:
        return True

    def search_by_isbn(self, isbn: str) -> dict[str, object]:
        self.calls.append(isbn)
        return {
            "provider": self.name,
            "provider_id": f"volume-{isbn}",
            "title": "Provider title",
            "authors": ["Provider author"],
            "isbn_13": isbn,
            "cover_url": f"https://covers.example/{isbn}.jpg",
        }


class _NoMatchProvider(_Provider):
    def search_by_isbn(self, isbn: str) -> None:
        self.calls.append(isbn)
        return None


class _NoCoverProvider(_Provider):
    name = "openlibrary"

    def search_by_isbn(self, isbn: str) -> dict[str, object]:
        metadata = super().search_by_isbn(isbn)
        metadata["title"] = "Titel van provider"
        metadata["cover_url"] = None
        return metadata


class _BatchProvider(_Provider):
    name = "hardcover"

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[list[str]] = []

    def search_by_isbns_for_enrichment(self, isbns: list[str]) -> dict[str, dict[str, object]]:
        self.batches.append(list(isbns))
        return {isbn: self.search_by_isbn(isbn) for isbn in isbns}


class _TransientProvider(_Provider):
    name = "googlebooks"

    def search_by_isbn_for_enrichment(self, isbn: str) -> None:
        self.calls.append(isbn)
        raise MetadataProviderTransientError("temporary quota failure")


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "users.db"
    UserDB(str(path)).initialize()
    return path


def _pages(*, week: int, isbn: str) -> dict[str, list[list[bytes]]]:
    record = [(1, isbn, "Bron titel", "Bron auteur")]
    return {
        "/": [[_page(week=week, year=2026, records=record)]],
        "/fictie": [[_page(week=week, year=2026, records=record)]],
        "/non-fictie": [[_page(week=week, year=2026, records=record)]],
        "/spannend": [[_page(week=week, year=2026, records=record)]],
        "/jeugd": [[_page(week=week, year=2026, records=record)]],
        "/koken": [[_page(week=week, year=2026, records=record)]],
    }


def _pages_for_records(
    *, week: int, records: list[tuple[int, str, str, str]]
) -> dict[str, list[list[bytes]]]:
    return {
        path: [[_page(week=week, year=2026, records=records)]]
        for path in ("/", "/fictie", "/non-fictie", "/spannend", "/jeugd", "/koken")
    }


def test_parser_uses_current_card_selectors_and_discards_invalid_isbns() -> None:
    valid = _isbn(41)
    parsed = parse_bestseller_list(
        _page(
            week=30,
            year=2026,
            records=[(4, valid, "Een titel", "Een auteur"), (5, "9780000000000", "Fout", "X")],
        ).decode(),
        "overall",
    )

    assert parsed == [
        parsed[0].__class__(
            list_key="overall", rank=4, isbn_13=valid, title="Een titel", author="Een auteur"
        )
    ]


def test_source_metadata_parser_extracts_cover_and_edition_fields() -> None:
    isbn = _isbn(40)

    parsed = parse_bestseller_metadata(
        _metadata_page(isbn=isbn).decode(),
        source_url="https://www.debestseller60.nl/",
    )[isbn]

    assert parsed["provider"] == "bestseller60"
    assert parsed["title"] == "Bron titel"
    assert parsed["authors"] == ["Bron auteur"]
    assert parsed["cover_url"] == f"https://covers.example/{isbn}.jpg"
    assert parsed["description"] == "Korte bronbeschrijving."
    assert parsed["publisher"] == "Testuitgever"
    assert parsed["publish_year"] == 2026


def test_new_week_fetches_six_pages_once_and_next_probe_closes_early(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    isbn = _isbn(42)
    initial = _Session(_pages(week=30, isbn=isbn))
    provider = _Provider()
    service = BestsellerSuggestionService(
        str(db_path), providers=[provider], http_session=initial, base_url="https://example.test"
    )
    start = datetime(2026, 7, 20, tzinfo=UTC)

    updated = service.sync_if_due(worker_id="worker-a", now=start)

    assert updated.outcome == "updated"
    assert updated.pages_fetched == 6
    assert initial.calls == ["/", "/fictie", "/non-fictie", "/spannend", "/jeugd", "/koken"]
    assert provider.calls == [isbn]
    assert all(response.closed for response in initial.responses)

    # The current week marker arrives in the first chunk; no genre request is
    # made and the response is immediately closed without reading its tail.
    unchanged = _Session({"/": [[b"<p>Week 30 - 2026</p>", b"unread tail"]]})
    service._session = unchanged
    result = service.sync_if_due(worker_id="worker-b", now=start + timedelta(hours=25))

    assert result.outcome == "unchanged"
    assert unchanged.calls == ["/"]
    assert unchanged.responses[0].closed is True


def test_homepage_probe_continues_the_original_stream_after_week_marker(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    isbn = _isbn(45)
    response = _SingleIteratorResponse(
        [
            b"<html><body><p>Week 30 - 2026</p>",
            _page(
                week=30,
                year=2026,
                records=[(1, isbn, "Titel na de eerste chunk", "Auteur")],
            ),
        ]
    )

    class _SingleResponseSession:
        def get(self, _url: str, **_kwargs: object) -> _SingleIteratorResponse:
            return response

    service = BestsellerSuggestionService(
        str(db_path),
        http_session=_SingleResponseSession(),
        base_url="https://example.test",
    )

    homepage, year, week, early_complete = service._read_homepage_probe()

    assert (year, week, early_complete) == (2026, 30, False)
    assert homepage is not None
    assert [entry.isbn_13 for entry in parse_bestseller_list(homepage, "overall")] == [isbn]
    assert response.iter_content_calls == 1
    assert response.closed is True


def test_deferred_worker_batches_provider_lookups_after_snapshot_activation(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    first_isbn = _isbn(46)
    second_isbn = _isbn(47)
    provider = _BatchProvider()
    service = BestsellerSuggestionService(
        str(db_path),
        providers=[provider],
        http_session=_Session(
            _pages_for_records(
                week=30,
                records=[
                    (1, first_isbn, "Eerste titel", "Eerste auteur"),
                    (2, second_isbn, "Tweede titel", "Tweede auteur"),
                ],
            )
        ),
        base_url="https://example.test",
        defer_enrichment=True,
        provider_min_intervals={},
    )

    service.sync_if_due(worker_id="worker", now=datetime(2026, 7, 20, tzinfo=UTC))

    assert provider.calls == []
    [(due_isbns, _due_key)] = service.due_enrichment_batches(
        now=datetime(2030, 7, 20, 0, 1, tzinfo=UTC)
    )
    assert due_isbns == [first_isbn, second_isbn]
    assert service.enrich_isbns(due_isbns) == 2
    assert provider.batches == [[first_isbn, second_isbn]]
    with sqlite3.connect(db_path) as connection:
        states = connection.execute(
            "SELECT metadata_state FROM bestseller_metadata_enrichment ORDER BY isbn_13"
        ).fetchall()
    assert states == [("complete",), ("complete",)]


def test_source_fallback_is_trending_only_and_attempted_once_per_isbn(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    isbn = _isbn(50)
    pages = _pages(week=30, isbn=isbn)
    pages["/"].append([_metadata_page(isbn=isbn)])
    session = _Session(pages)
    provider = _NoMatchProvider()
    service = BestsellerSuggestionService(
        str(db_path),
        providers=[provider],
        http_session=session,
        cover_fetcher=lambda _cache_id, _url: True,
        base_url="https://example.test",
        defer_enrichment=True,
        source_metadata_fallback=True,
        provider_min_intervals={},
    )
    service.sync_if_due(worker_id="worker", now=datetime(2026, 7, 20, tzinfo=UTC))

    assert service.enrich_isbns([isbn]) == 1
    with sqlite3.connect(db_path) as connection:
        attempt = connection.execute(
            """SELECT outcome, source_path FROM bestseller_source_metadata_attempts
               WHERE isbn_13 = ?""",
            (isbn,),
        ).fetchone()
        book = connection.execute(
            "SELECT cover_url, metadata_json FROM books WHERE isbn_13 = ?", (isbn,)
        ).fetchone()
        connection.execute(
            """UPDATE bestseller_metadata_enrichment
               SET metadata_state = 'missing', next_retry_at = CURRENT_TIMESTAMP
               WHERE isbn_13 = ?""",
            (isbn,),
        )

    assert attempt == ("found", "/")
    assert book[0] is not None
    assert json.loads(book[1])["publisher"] == "Testuitgever"
    assert session.calls.count("/") == 2

    assert service.enrich_isbns([isbn]) == 1
    assert session.calls.count("/") == 2
    with sqlite3.connect(db_path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM bestseller_source_metadata_attempts WHERE isbn_13 = ?",
                (isbn,),
            ).fetchone()[0]
            == 1
        )


def test_source_fallback_fills_missing_cover_without_replacing_provider_title(
    tmp_path: Path,
) -> None:
    db_path = _database(tmp_path)
    isbn = _isbn(51)
    pages = _pages(week=30, isbn=isbn)
    pages["/"].append([_metadata_page(isbn=isbn)])
    service = BestsellerSuggestionService(
        str(db_path),
        providers=[_NoCoverProvider()],
        http_session=_Session(pages),
        cover_fetcher=lambda _cache_id, _url: True,
        base_url="https://example.test",
        defer_enrichment=True,
        source_metadata_fallback=True,
        provider_min_intervals={},
    )
    service.sync_if_due(worker_id="worker", now=datetime(2026, 7, 20, tzinfo=UTC))

    assert service.enrich_isbns([isbn]) == 1

    with sqlite3.connect(db_path) as connection:
        book = connection.execute(
            "SELECT title, cover_url, metadata_json FROM books WHERE isbn_13 = ?", (isbn,)
        ).fetchone()
        attempt = connection.execute(
            "SELECT outcome FROM bestseller_source_metadata_attempts WHERE isbn_13 = ?",
            (isbn,),
        ).fetchone()
    assert book[0] == "Bron titel"
    assert book[1] is not None
    assert json.loads(book[2])["title"] == "Titel van provider"
    assert attempt == ("found",)


def test_deferred_worker_persists_transient_failure_for_later_retry(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    first_isbn = _isbn(48)
    second_isbn = _isbn(49)
    provider = _TransientProvider()
    service = BestsellerSuggestionService(
        str(db_path),
        providers=[provider],
        http_session=_Session(
            _pages_for_records(
                week=30,
                records=[
                    (1, first_isbn, "Eerste titel", "Eerste auteur"),
                    (2, second_isbn, "Tweede titel", "Tweede auteur"),
                ],
            )
        ),
        base_url="https://example.test",
        defer_enrichment=True,
        provider_min_intervals={},
    )
    service.sync_if_due(worker_id="worker", now=datetime(2026, 7, 20, tzinfo=UTC))

    with pytest.raises(RuntimeError, match="Temporary metadata failure"):
        service.enrich_isbns([first_isbn, second_isbn])

    with sqlite3.connect(db_path) as connection:
        states = connection.execute(
            """SELECT metadata_state, next_retry_at, last_error
               FROM bestseller_metadata_enrichment ORDER BY isbn_13"""
        ).fetchall()
    assert provider.calls == [first_isbn]
    assert all(state[0] == "transient_error" for state in states)
    assert all(state[1] is not None for state in states)
    assert all(state[2] == "Temporary provider failure" for state in states)


def test_provider_limiter_spaces_calls_without_initial_delay(tmp_path: Path) -> None:
    clock = [0.0]
    delays: list[float] = []

    def sleep(delay: float) -> None:
        delays.append(delay)
        clock[0] += delay

    service = BestsellerSuggestionService(
        str(_database(tmp_path)),
        provider_min_intervals={"hardcover": 1.1},
        sleep=sleep,
        monotonic=lambda: clock[0],
    )

    service._wait_for_provider("hardcover")
    service._wait_for_provider("hardcover")
    service._wait_for_provider("hardcover")

    assert delays == pytest.approx([1.1, 1.1])


def test_missing_metadata_is_persisted_and_not_requeried_before_retry(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    isbn = _isbn(43)
    provider = _NoMatchProvider()
    first = _Session(_pages(week=30, isbn=isbn))
    service = BestsellerSuggestionService(
        str(db_path), providers=[provider], http_session=first, base_url="https://example.test"
    )
    start = datetime(2026, 7, 20, tzinfo=UTC)
    service.sync_if_due(worker_id="worker-a", now=start)

    second = _Session(_pages(week=31, isbn=isbn))
    service._session = second
    service.sync_if_due(worker_id="worker-b", now=start + timedelta(days=2))

    assert provider.calls == [isbn]
    with sqlite3.connect(db_path) as connection:
        enrichment = connection.execute(
            "SELECT metadata_state, book_id, next_retry_at FROM bestseller_metadata_enrichment"
        ).fetchone()
        book = connection.execute("SELECT catalog_visible FROM books").fetchone()
    assert enrichment[0] == "missing"
    assert enrichment[1] is not None
    assert enrichment[2] is not None
    assert book[0] == 0


def test_dashboard_keeps_sections_and_hides_internal_rank(tmp_path: Path) -> None:
    db_path = _database(tmp_path)
    isbn = _isbn(44)
    service = BestsellerSuggestionService(
        str(db_path),
        providers=[_Provider()],
        http_session=_Session(_pages(week=30, isbn=isbn)),
        base_url="https://example.test",
    )
    service.sync_if_due(worker_id="worker-a", now=datetime(2026, 7, 20, tzinfo=UTC))

    dashboard = service.dashboard(user_id=None)
    complete_list = service.list_suggestions(list_key="overall", user_id=None, offset=0, limit=60)

    assert [section["key"] for section in dashboard["lists"]] == [
        "overall",
        "fiction",
        "non_fiction",
        "thriller",
        "youth",
        "cooking",
    ]
    assert all(section["total"] == 1 for section in dashboard["lists"])
    assert complete_list["label"] == "Bestseller 60"
    assert "list_rank" not in complete_list["items"][0]
