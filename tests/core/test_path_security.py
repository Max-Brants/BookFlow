"""Tests for canonical library-serving and client-cleanup path guards."""

from __future__ import annotations

from pathlib import Path

import pytest

from bookflow.core import path_security
from bookflow.core.path_security import (
    PathSecurityError,
    resolve_client_job_cleanup_leaf,
    resolve_library_file,
)


def _symlink_or_skip(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"Symlink creation is unavailable in this test environment: {exc}")


def test_resolve_library_file_returns_canonical_existing_regular_file(tmp_path: Path) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    book_file = library_root / "books" / "example.epub"
    book_file.parent.mkdir()
    book_file.write_bytes(b"ebook")

    assert resolve_library_file(book_file, allowed_roots=(library_root,)) == book_file.resolve()


@pytest.mark.parametrize("candidate_kind", ["missing", "directory", "traversal"])
def test_resolve_library_file_rejects_non_file_or_traversal(
    tmp_path: Path, candidate_kind: str
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    outside_file = tmp_path / "outside.epub"
    outside_file.write_bytes(b"outside")

    if candidate_kind == "missing":
        candidate = library_root / "missing.epub"
    elif candidate_kind == "directory":
        candidate = library_root / "nested"
        candidate.mkdir()
    else:
        candidate = library_root / ".." / outside_file.name

    with pytest.raises(PathSecurityError):
        resolve_library_file(candidate, allowed_roots=(library_root,))


def test_resolve_library_file_rejects_root_and_outside_file(tmp_path: Path) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    outside_file = tmp_path / "outside.epub"
    outside_file.write_bytes(b"outside")

    with pytest.raises(PathSecurityError):
        resolve_library_file(library_root, allowed_roots=(library_root,))
    with pytest.raises(PathSecurityError):
        resolve_library_file(outside_file, allowed_roots=(library_root,))


def test_resolve_library_file_rejects_symlink_file_and_intermediate_directory(
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "book.epub"
    outside_file.write_bytes(b"outside")

    linked_file = library_root / "linked.epub"
    _symlink_or_skip(linked_file, outside_file)
    with pytest.raises(PathSecurityError):
        resolve_library_file(linked_file, allowed_roots=(library_root,))

    linked_directory = library_root / "linked-directory"
    _symlink_or_skip(linked_directory, outside, directory=True)
    with pytest.raises(PathSecurityError):
        resolve_library_file(linked_directory / outside_file.name, allowed_roots=(library_root,))


def test_resolve_library_file_rejects_external_symlink_spelling_into_library(
    tmp_path: Path,
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    book_file = library_root / "book.epub"
    book_file.write_bytes(b"ebook")
    external_link = tmp_path / "library-link"
    _symlink_or_skip(external_link, library_root, directory=True)

    with pytest.raises(PathSecurityError):
        resolve_library_file(external_link / book_file.name, allowed_roots=(library_root,))


def test_resolve_library_file_rejects_detected_reparse_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    book_file = library_root / "book.epub"
    book_file.write_bytes(b"ebook")
    original = path_security._is_reparse_point

    def detected_reparse(path: Path) -> bool:
        return path == book_file or original(path)

    monkeypatch.setattr(path_security, "_is_reparse_point", detected_reparse)

    with pytest.raises(PathSecurityError, match="reparse point"):
        resolve_library_file(book_file, allowed_roots=(library_root,))


def test_resolve_client_job_cleanup_leaf_accepts_only_exact_descendant(tmp_path: Path) -> None:
    client_root = tmp_path / "client-downloads"
    client_root.mkdir()
    job_leaf = client_root / "category" / "job-123"
    job_leaf.mkdir(parents=True)
    job_file = job_leaf / "part1.rar"
    job_file.write_bytes(b"part")

    assert resolve_client_job_cleanup_leaf(job_leaf, client_root=client_root) == job_leaf.resolve()
    assert resolve_client_job_cleanup_leaf(job_file, client_root=client_root) == job_file.resolve()

    with pytest.raises(PathSecurityError):
        resolve_client_job_cleanup_leaf(client_root, client_root=client_root)
    with pytest.raises(PathSecurityError):
        resolve_client_job_cleanup_leaf(client_root / "missing", client_root=client_root)
    with pytest.raises(PathSecurityError):
        resolve_client_job_cleanup_leaf(client_root / "..", client_root=client_root)


def test_resolve_client_job_cleanup_leaf_rejects_reparse_path(tmp_path: Path) -> None:
    client_root = tmp_path / "client-downloads"
    client_root.mkdir()
    outside = tmp_path / "outside-job"
    outside.mkdir()
    linked_job = client_root / "job-123"
    _symlink_or_skip(linked_job, outside, directory=True)

    with pytest.raises(PathSecurityError):
        resolve_client_job_cleanup_leaf(linked_job, client_root=client_root)
