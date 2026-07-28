"""Unit coverage for conservative canonical Book matching."""

from bookflow.core.book_matcher import (
    BookMatchCandidate,
    BookMatcher,
    BookMatchInput,
    isbn10_to_isbn13,
    normalize_isbn,
)


def test_normalize_isbn_validates_checksums_and_converts_isbn10() -> None:
    isbn = normalize_isbn("0-306-40615-2")

    assert isbn is not None
    assert isbn.isbn10 == "0306406152"
    assert isbn.isbn13 == "9780306406157"
    assert isbn10_to_isbn13("0306406152") == "9780306406157"
    assert normalize_isbn("9780306406158") is None
    assert normalize_isbn("not-an-isbn") is None


def test_matcher_prefers_unique_isbn_then_provider_identifier() -> None:
    matcher = BookMatcher()
    isbn_candidate = BookMatchCandidate(
        book_id=1,
        title="Different display title",
        isbn13=frozenset({"9780306406157"}),
    )
    provider_candidate = BookMatchCandidate(
        book_id=2,
        title="Provider book",
        provider_identifiers=frozenset({("hardcover", "provider-2")}),
    )

    isbn_match = matcher.match(
        BookMatchInput(title="Anything", isbn="0-306-40615-2"),
        (isbn_candidate, provider_candidate),
    )
    provider_match = matcher.match(
        BookMatchInput(title="Anything", provider="Hardcover", provider_book_id="provider-2"),
        (isbn_candidate, provider_candidate),
    )

    assert isbn_match is not None
    assert (isbn_match.book_id, isbn_match.method) == (1, "isbn10_to_isbn13")
    assert provider_match is not None
    assert (provider_match.book_id, provider_match.method) == (2, "provider_identifier")


def test_matcher_accepts_only_one_strong_metadata_match_and_never_breaks_ties() -> None:
    matcher = BookMatcher()
    candidate = BookMatchCandidate(
        book_id=1,
        title="The Canonical: A Novel",
        author="Ada Lovelace",
        language="en",
        publish_year=2020,
    )
    incoming = BookMatchInput(
        title="  the canonical a novel ",
        author="ADA LOVELACE",
        language="EN",
        publish_year=2020,
    )

    match = matcher.match(incoming, (candidate,))
    ambiguous = matcher.match(
        incoming, (candidate, BookMatchCandidate(**{**candidate.__dict__, "book_id": 2}))
    )

    assert match is not None
    assert (match.book_id, match.method, match.confidence) == (1, "metadata", 0.9)
    assert ambiguous is None
