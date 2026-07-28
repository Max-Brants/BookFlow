"""Conservative, provider-independent matching for canonical library Books."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

_ISBN_SEPARATOR_PATTERN = re.compile(r"[\s-]+")
_PUNCTUATION_PATTERN = re.compile(r"[^\w\s]")
_WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(frozen=True)
class NormalizedISBN:
    """Validated ISBN variants, with ISBN-10 converted where possible."""

    isbn10: str | None
    isbn13: str | None


@dataclass(frozen=True)
class BookMatchInput:
    """Minimal metadata required for conservative canonical Book matching."""

    title: str
    author: str | None = None
    language: str | None = None
    publish_year: int | None = None
    provider: str | None = None
    provider_book_id: str | None = None
    isbn: str | None = None


@dataclass(frozen=True)
class BookMatchCandidate:
    """Canonical Book data made available to the pure matching algorithm."""

    book_id: int
    title: str
    author: str | None = None
    language: str | None = None
    publish_year: int | None = None
    provider_identifiers: frozenset[tuple[str, str]] = field(default_factory=frozenset)
    isbn10: frozenset[str] = field(default_factory=frozenset)
    isbn13: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class BookMatch:
    """One unambiguous canonical match plus its reproducible method."""

    book_id: int
    method: str
    confidence: float


def normalize_text(value: str | None) -> str | None:
    """Normalize user/provider text without transliterating its semantic content."""
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = _PUNCTUATION_PATTERN.sub(" ", normalized)
    normalized = _WHITESPACE_PATTERN.sub(" ", normalized).strip()
    return normalized or None


def normalize_author(value: str | None) -> str | None:
    """Normalize author display names conservatively for exact-name comparison."""
    return normalize_text(value)


def _isbn13_check_digit(first_twelve_digits: str) -> str:
    total = sum(
        int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(first_twelve_digits)
    )
    return str((10 - total % 10) % 10)


def is_valid_isbn13(value: str) -> bool:
    """Return whether *value* is the normalized, checksummed ISBN-13 form."""
    return len(value) == 13 and value.isdecimal() and value[-1] == _isbn13_check_digit(value[:12])


def is_valid_isbn10(value: str) -> bool:
    """Return whether *value* is the normalized, checksummed ISBN-10 form."""
    if len(value) != 10 or not all(character.isdecimal() for character in value[:9]):
        return False
    check_character = value[-1]
    if not (check_character.isdecimal() or check_character == "X"):
        return False
    total = sum((10 - index) * int(digit) for index, digit in enumerate(value[:9]))
    total += 10 if check_character == "X" else int(check_character)
    return total % 11 == 0


def isbn10_to_isbn13(value: str) -> str | None:
    """Convert one valid normalized ISBN-10 to its ISBN-13 equivalent."""
    if not is_valid_isbn10(value):
        return None
    prefix = f"978{value[:9]}"
    return f"{prefix}{_isbn13_check_digit(prefix)}"


def normalize_isbn(value: str | None) -> NormalizedISBN | None:
    """Strip presentation characters and return only checksum-valid ISBNs."""
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", value).upper()
    normalized = _ISBN_SEPARATOR_PATTERN.sub("", normalized)
    if is_valid_isbn13(normalized):
        return NormalizedISBN(isbn10=None, isbn13=normalized)
    if is_valid_isbn10(normalized):
        return NormalizedISBN(isbn10=normalized, isbn13=isbn10_to_isbn13(normalized))
    return None


class BookMatcher:
    """Match only high-confidence canonical Book candidates.

    The matcher intentionally returns ``None`` for a tie.  Ambiguity is a
    review condition, never a reason to merge records automatically.
    """

    def match(
        self,
        incoming: BookMatchInput,
        candidates: Iterable[BookMatchCandidate],
    ) -> BookMatch | None:
        """Return one unique match following the planned matching precedence."""
        all_candidates = tuple(candidates)
        normalized_isbn = normalize_isbn(incoming.isbn)
        if normalized_isbn and normalized_isbn.isbn10 is None and normalized_isbn.isbn13:
            match = self._only_match(
                candidate
                for candidate in all_candidates
                if normalized_isbn.isbn13 in candidate.isbn13
            )
            if match is not None:
                return BookMatch(match.book_id, "isbn13", 1.0)

        if normalized_isbn and normalized_isbn.isbn10:
            match = self._only_match(
                candidate
                for candidate in all_candidates
                if normalized_isbn.isbn10 in candidate.isbn10
                or (
                    normalized_isbn.isbn13 is not None
                    and normalized_isbn.isbn13 in candidate.isbn13
                )
            )
            if match is not None:
                return BookMatch(match.book_id, "isbn10_to_isbn13", 0.99)

        if incoming.provider and incoming.provider_book_id:
            provider_key = (incoming.provider.strip().casefold(), incoming.provider_book_id.strip())
            match = self._only_match(
                candidate
                for candidate in all_candidates
                if provider_key in candidate.provider_identifiers
            )
            if match is not None:
                return BookMatch(match.book_id, "provider_identifier", 0.98)

        normalized_title = normalize_text(incoming.title)
        normalized_author = normalize_author(incoming.author)
        if normalized_title is None or normalized_author is None:
            return None

        metadata_matches = [
            candidate
            for candidate in all_candidates
            if normalize_text(candidate.title) == normalized_title
            and normalize_author(candidate.author) == normalized_author
            and self._same_optional_language(incoming.language, candidate.language)
            and self._same_optional_year(incoming.publish_year, candidate.publish_year)
        ]
        match = self._only_match(metadata_matches)
        return BookMatch(match.book_id, "metadata", 0.9) if match is not None else None

    @staticmethod
    def _only_match(candidates: Iterable[BookMatchCandidate]) -> BookMatchCandidate | None:
        unique = {candidate.book_id: candidate for candidate in candidates}
        return next(iter(unique.values())) if len(unique) == 1 else None

    @staticmethod
    def _same_optional_language(left: str | None, right: str | None) -> bool:
        normalized_left = normalize_text(left)
        normalized_right = normalize_text(right)
        return (
            normalized_left is None
            or normalized_right is None
            or normalized_left == normalized_right
        )

    @staticmethod
    def _same_optional_year(left: int | None, right: int | None) -> bool:
        return left is None or right is None or left == right
