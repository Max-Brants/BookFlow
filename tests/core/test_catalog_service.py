"""Transactional catalog, central-file and entitlement tests."""

from pathlib import Path

from bookflow.core.book_matcher import BookMatchInput
from bookflow.core.catalog_service import CatalogService
from bookflow.core.file_store import FileStore
from bookflow.core.user_db import UserDB


def test_catalog_reuses_one_book_for_isbn_and_attaches_second_provider(tmp_path: Path) -> None:
    db_path = tmp_path / "users.db"
    UserDB(str(db_path)).initialize()
    catalog = CatalogService(str(db_path))

    first = catalog.get_or_create_book(
        BookMatchInput(
            title="Canonical Book",
            author="Ada Lovelace",
            provider="hardcover",
            provider_book_id="one",
            isbn="978-0-306-40615-7",
        )
    )
    second = catalog.get_or_create_book(
        BookMatchInput(
            title="Different provider display name",
            provider="openlibrary",
            provider_book_id="two",
            isbn="0-306-40615-2",
        )
    )

    assert first.created is True
    assert second.created is False
    assert second.book_id == first.book_id
    assert second.match_method == "isbn10_to_isbn13"
    conn = UserDB(str(db_path))._connect()
    try:
        provider_count = conn.execute(
            "SELECT COUNT(*) FROM book_provider_identifiers WHERE book_id = ?", (first.book_id,)
        ).fetchone()[0]
        audit_methods = [
            row[0]
            for row in conn.execute(
                "SELECT method FROM book_match_audit WHERE matched_book_id = ? ORDER BY id",
                (first.book_id,),
            )
        ]
    finally:
        conn.close()
    assert provider_count == 2
    assert audit_methods == ["created", "isbn10_to_isbn13"]


def test_catalog_file_record_and_entitlement_are_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "users.db"
    user_db = UserDB(str(db_path))
    user_db.initialize()
    user = user_db.create_user(username="reader")
    catalog = CatalogService(str(db_path))
    book = catalog.get_or_create_book(
        BookMatchInput(title="A Book", provider="test", provider_book_id="1")
    )
    source_root = tmp_path / "source"
    storage_root = tmp_path / "storage"
    source_root.mkdir()
    storage_root.mkdir()
    source_file = source_root / "book.epub"
    source_file.write_bytes(b"canonical bytes")
    published = FileStore(storage_root).publish(source_file, source_roots=(source_root,))

    first_file = catalog.register_imported_file(book_id=book.book_id, published_file=published)
    second_file = catalog.register_imported_file(book_id=book.book_id, published_file=published)

    assert first_file["id"] == second_file["id"]
    assert catalog.grant_file_entitlement(user_id=user["id"], file_id=first_file["id"]) is True
    assert catalog.grant_file_entitlement(user_id=user["id"], file_id=first_file["id"]) is False
