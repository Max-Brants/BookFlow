"""Safe, content-addressed publication of central library files."""

from __future__ import annotations

import hashlib
import mimetypes
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfileobj

from bookflow.core.path_security import (
    PathInput,
    PathSecurityError,
    resolve_allowed_directory,
    resolve_library_file,
)

_COPY_BUFFER_SIZE = 1024 * 1024
_KEPUB_MIME_TYPE = "application/epub+zip"


class FileStoreError(RuntimeError):
    """Raised when a central-file import cannot be completed safely."""


@dataclass(frozen=True)
class PublishedFile:
    """An atomically published physical file, addressed by its SHA-256 bytes."""

    path: Path
    sha256: str
    size_bytes: int
    file_format: str
    mime_type: str | None
    deduplicated: bool


class FileStore:
    """Publish validated source files into a content-addressed storage root."""

    def __init__(self, storage_root: PathInput) -> None:
        root = Path(storage_root)
        if not root.is_absolute():
            raise FileStoreError("storage_root must be absolute")
        try:
            self._storage_root = self._validate_directory(root)
        except PathSecurityError as exc:
            raise FileStoreError(str(exc)) from exc

    @property
    def storage_root(self) -> Path:
        """Return the canonical central storage root."""
        return self._storage_root

    @staticmethod
    def _validate_directory(path: Path) -> Path:
        """Validate the configured storage root as a non-reparse directory."""
        return resolve_allowed_directory(path)

    @staticmethod
    def _sha256(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size_bytes = 0
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(_COPY_BUFFER_SIZE), b""):
                digest.update(chunk)
                size_bytes += len(chunk)
        return digest.hexdigest(), size_bytes

    @staticmethod
    def _normalize_format(source_path: Path, file_format: str | None) -> str:
        candidate = (file_format or source_path.suffix.removeprefix(".")).strip().lower()
        if not candidate or not candidate.isalnum() or len(candidate) > 16:
            raise FileStoreError("file_format must be a short alphanumeric extension")
        return candidate

    def _destination_for(self, *, sha256: str, file_format: str) -> Path:
        return self._storage_root / sha256[:2] / f"{sha256}.{file_format}"

    def _validate_destination_parent(self, path: Path) -> Path:
        """Require the content-address directory to resolve directly below root."""
        try:
            resolved = path.resolve(strict=True)
            resolved.relative_to(self._storage_root)
        except (OSError, ValueError) as exc:
            raise FileStoreError(f"Unsafe storage destination directory: {path}") from exc
        if resolved == self._storage_root or path.is_symlink():
            raise FileStoreError(f"Unsafe storage destination directory: {path}")
        return resolved

    def publish(
        self,
        source_path: PathInput,
        *,
        source_roots: tuple[PathInput, ...],
        file_format: str | None = None,
    ) -> PublishedFile:
        """Hash and atomically publish one existing regular source file.

        The final path is derived solely from the hash and format.  A duplicate
        checks its already-published bytes before reuse; a hash/path mismatch is
        treated as corruption rather than overwritten.
        """
        try:
            source = resolve_library_file(source_path, allowed_roots=source_roots)
        except PathSecurityError as exc:
            raise FileStoreError(str(exc)) from exc
        normalized_format = self._normalize_format(source, file_format)
        sha256, size_bytes = self._sha256(source)
        destination = self._destination_for(sha256=sha256, file_format=normalized_format)
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination_parent = self._validate_destination_parent(destination.parent)
        destination = destination_parent / destination.name
        mime_type = (
            _KEPUB_MIME_TYPE
            if normalized_format == "kepub"
            else mimetypes.guess_type(destination.name)[0]
        )

        if destination.exists():
            return self._reuse_existing(
                destination, sha256, size_bytes, normalized_format, mime_type
            )

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="xb", dir=destination_parent, prefix=".import-", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                with source.open("rb") as source_file:
                    copyfileobj(source_file, temporary, length=_COPY_BUFFER_SIZE)
                temporary.flush()
                os.fsync(temporary.fileno())

            try:
                os.link(temporary_path, destination)
            except FileExistsError:
                return self._reuse_existing(
                    destination, sha256, size_bytes, normalized_format, mime_type
                )
            finally:
                if temporary_path.exists():
                    temporary_path.unlink(missing_ok=True)

            return PublishedFile(
                path=destination,
                sha256=sha256,
                size_bytes=size_bytes,
                file_format=normalized_format,
                mime_type=mime_type,
                deduplicated=False,
            )
        except OSError as exc:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink(missing_ok=True)
            raise FileStoreError(f"Unable to publish file: {source}") from exc

    def _reuse_existing(
        self,
        destination: Path,
        expected_sha256: str,
        expected_size_bytes: int,
        file_format: str,
        mime_type: str | None,
    ) -> PublishedFile:
        try:
            existing = resolve_library_file(destination, allowed_roots=(self._storage_root,))
        except PathSecurityError as exc:
            raise FileStoreError(f"Unsafe existing storage file: {destination}") from exc
        actual_sha256, actual_size_bytes = self._sha256(existing)
        if actual_sha256 != expected_sha256 or actual_size_bytes != expected_size_bytes:
            raise FileStoreError(f"Content-address collision or corrupt file: {destination}")
        return PublishedFile(
            path=existing,
            sha256=expected_sha256,
            size_bytes=expected_size_bytes,
            file_format=file_format,
            mime_type=mime_type,
            deduplicated=True,
        )
