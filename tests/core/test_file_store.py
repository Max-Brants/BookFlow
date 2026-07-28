"""Tests for content-addressed, safe central file publication."""

from pathlib import Path

import pytest

from bookflow.core.file_store import FileStore, FileStoreError


def test_publish_is_content_addressed_atomic_and_deduplicates(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "storage"
    source_root.mkdir()
    storage_root.mkdir()
    first_source = source_root / "first.epub"
    second_source = source_root / "second.epub"
    first_source.write_bytes(b"same ebook bytes")
    second_source.write_bytes(b"same ebook bytes")
    store = FileStore(storage_root)

    first = store.publish(first_source, source_roots=(source_root,))
    second = store.publish(second_source, source_roots=(source_root,))

    assert first.path.exists()
    assert first.path.read_bytes() == b"same ebook bytes"
    assert first.path.parent.parent == storage_root.resolve()
    assert first.deduplicated is False
    assert second.path == first.path
    assert second.sha256 == first.sha256
    assert second.deduplicated is True


def test_publish_rejects_sources_outside_explicit_root_and_bad_format(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    storage_root = tmp_path / "storage"
    source_root.mkdir()
    storage_root.mkdir()
    outside = tmp_path / "outside.epub"
    outside.write_bytes(b"outside")
    valid_source = source_root / "valid.epub"
    valid_source.write_bytes(b"inside")
    store = FileStore(storage_root)

    with pytest.raises(FileStoreError):
        store.publish(outside, source_roots=(source_root,))
    with pytest.raises(FileStoreError):
        store.publish(valid_source, source_roots=(source_root,), file_format="../epub")
