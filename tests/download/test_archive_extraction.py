from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from bookflow.download import archive as archive_mod


class _FakeZipInfo:
    filename = "book.epub"
    flag_bits = 0

    def is_dir(self) -> bool:
        return False


class _ChunkOnlyStream:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self._offset = 0
        self.whole_read_called = False

    def __enter__(self) -> _ChunkOnlyStream:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            self.whole_read_called = True
            msg = "archive member was read into memory"
            raise AssertionError(msg)

        chunk = self._content[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


class _FakeZipFile:
    stream: _ChunkOnlyStream

    def __init__(self, _path: Path, _mode: str) -> None:
        self.stream = _ChunkOnlyStream(b"streamed archive content")

    def __enter__(self) -> _FakeZipFile:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def infolist(self) -> list[_FakeZipInfo]:
        return [_FakeZipInfo()]

    def testzip(self) -> None:
        return None

    def open(self, _info: _FakeZipInfo) -> _ChunkOnlyStream:
        return self.stream


def test_extract_archive_raw_streams_members_without_whole_read(
    tmp_path: Path, monkeypatch
) -> None:
    fake_archives: list[_FakeZipFile] = []

    def fake_zip_file(path: Path, mode: str) -> _FakeZipFile:
        archive = _FakeZipFile(path, mode)
        fake_archives.append(archive)
        return archive

    monkeypatch.setattr(archive_mod.zipfile, "ZipFile", fake_zip_file)

    extracted_files, warnings = archive_mod.extract_archive_raw(tmp_path / "book.zip", tmp_path)

    assert warnings == []
    assert [path.name for path in extracted_files] == ["book.epub"]
    assert extracted_files[0].read_bytes() == b"streamed archive content"
    assert fake_archives[0].stream.whole_read_called is False


def test_archive_rejects_executable_payload_before_extracting(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("book.epub", b"book")
        archive.writestr("setup.exe", b"malware")

    with pytest.raises(archive_mod.ArchiveExtractionError, match="executable"):
        archive_mod.extract_archive_raw(archive_path, tmp_path / "output")


def test_archive_rejects_entry_count_limit(tmp_path: Path, monkeypatch) -> None:
    archive_path = tmp_path / "many.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("one.epub", b"one")
        archive.writestr("two.epub", b"two")
    (tmp_path / "output").mkdir()
    monkeypatch.setattr(archive_mod, "MAX_ARCHIVE_ENTRIES", 1)

    with pytest.raises(archive_mod.ArchiveLimitError, match="too many"):
        archive_mod.extract_archive_raw(archive_path, tmp_path / "output")


def test_archive_rejects_compression_ratio_limit(tmp_path: Path, monkeypatch) -> None:
    archive_path = tmp_path / "compressed.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("book.epub", b"x" * 100_000)
    (tmp_path / "output").mkdir()
    monkeypatch.setattr(archive_mod, "MAX_ARCHIVE_COMPRESSION_RATIO", 2)

    with pytest.raises(archive_mod.ArchiveLimitError, match="compression ratio"):
        archive_mod.extract_archive_raw(archive_path, tmp_path / "output")
