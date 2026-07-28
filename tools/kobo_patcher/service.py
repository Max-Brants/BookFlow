"""Filesystem-safe patch and restore operations for an already-detected Kobo."""

from __future__ import annotations

import hashlib
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .conf import OFFICIAL_KOBO_ENDPOINT, ConfError, KoboConf

if TYPE_CHECKING:
    from .device import KoboDevice

ORIGINAL_BACKUP_SUFFIX = ".bookflow-original.backup"
TIMESTAMP_BACKUP_MARKER = ".bookflow-"


class PatchError(RuntimeError):
    """A config write could not be completed safely."""


@dataclass(frozen=True)
class PatchResult:
    config_path: Path
    backup_path: Path
    endpoint: str


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


class KoboPatcher:
    def __init__(self, device: KoboDevice) -> None:
        self.device = device
        self.path = device.config_path

    @property
    def original_backup_path(self) -> Path:
        return self.path.with_name(self.path.name + ORIGINAL_BACKUP_SUFFIX)

    def available_backups(self) -> list[Path]:
        if not self.path.parent.is_dir():
            return []
        try:
            backups = [
                candidate
                for candidate in self.path.parent.iterdir()
                if not candidate.is_symlink()
                and candidate.is_file()
                and (
                    candidate.name == self.original_backup_path.name
                    or (
                        candidate.name.startswith(self.path.name + TIMESTAMP_BACKUP_MARKER)
                        and candidate.name.endswith(".backup")
                    )
                )
            ]
        except OSError:
            return []
        return sorted(
            backups, key=lambda item: (item != self.original_backup_path, item.name), reverse=False
        )

    def _read_current(self) -> bytes:
        try:
            raw = self.path.read_bytes()
        except OSError as exc:
            raise PatchError("Could not read Kobo eReader.conf") from exc
        try:
            KoboConf.from_bytes(raw)
        except ConfError as exc:
            raise PatchError(str(exc)) from exc
        return raw

    def current_endpoint(self) -> str | None:
        """Read the current endpoint for confirmation; never persist or log it."""
        return KoboConf.from_bytes(self._read_current()).endpoint()

    def _timestamp_backup(self, raw: bytes, purpose: str) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        base = self.path.with_name(
            f"{self.path.name}{TIMESTAMP_BACKUP_MARKER}{stamp}-{purpose}.backup"
        )
        destination = base
        counter = 1
        while destination.exists():
            destination = base.with_name(f"{base.stem}-{counter}{base.suffix}")
            counter += 1
        self._write_new_file(destination, raw)
        return destination

    @staticmethod
    def _write_new_file(path: Path, data: bytes) -> None:
        try:
            with path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise PatchError(f"Could not create safety backup {path.name}") from exc

    def _ensure_original_backup(self, raw: bytes) -> None:
        if not self.original_backup_path.exists():
            self._write_new_file(self.original_backup_path, raw)

    def _restore_rollback(self, rollback: bytes) -> None:
        rollback_path = self.path.with_name(self.path.name + ".bookflow-rollback.tmp")
        with rollback_path.open("wb") as stream:
            stream.write(rollback)
            stream.flush()
            os.fsync(stream.fileno())
        rollback_path.replace(self.path)
        if self.path.read_bytes() != rollback:
            raise OSError("rollback verification did not match the original file")

    def _atomic_replace(self, data: bytes, rollback: bytes) -> None:
        directory = self.path.parent
        try:
            fd, temp_name = tempfile.mkstemp(prefix=".bookflow-", suffix=".tmp", dir=directory)
        except OSError as exc:
            raise PatchError("Could not create a temporary Kobo configuration file") from exc
        temp_path = Path(temp_name)
        replaced = False
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temp_path.replace(self.path)
            replaced = True
            self._verify_written(data)
        except Exception as exc:
            rollback_failure: OSError | None = None
            if replaced:
                try:
                    self._restore_rollback(rollback)
                except OSError as rollback_error:
                    rollback_failure = rollback_error
            if rollback_failure is not None:
                raise PatchError(
                    "Kobo eReader.conf write failed and automatic rollback also failed. "
                    "Do not eject the Kobo; restore a BookFlow backup before retrying."
                ) from rollback_failure
            if isinstance(exc, PatchError):
                raise
            raise PatchError("Could not safely write Kobo eReader.conf") from exc
        finally:
            with suppress(OSError):
                temp_path.unlink(missing_ok=True)

    def _verify_written(self, expected: bytes) -> None:
        if self.path.read_bytes() != expected:
            raise PatchError("Kobo eReader.conf verification failed after writing")

    def _update_endpoint(self, endpoint: str, *, create_section: bool) -> tuple[bytes, bytes]:
        old = self._read_current()
        document = KoboConf.from_bytes(old)
        try:
            document.set_endpoint(endpoint, create_section=create_section)
            updated = document.to_bytes()
            verified = KoboConf.from_bytes(updated).endpoint()
        except ConfError as exc:
            raise PatchError(str(exc)) from exc
        if verified != endpoint:
            raise PatchError("Endpoint verification failed")
        return old, updated

    def patch(self, endpoint: str) -> PatchResult:
        if not endpoint.startswith(("https://", "http://")):
            raise PatchError("BookFlow endpoint must be an HTTP(S) URL")
        old, updated = self._update_endpoint(endpoint, create_section=False)
        self._ensure_original_backup(old)
        backup = self._timestamp_backup(old, "pre-patch")
        self._atomic_replace(updated, old)
        return PatchResult(self.path, backup, endpoint)

    def restore_backup(self, backup: Path | None = None) -> PatchResult:
        choices = self.available_backups()
        selected = backup or (
            self.original_backup_path
            if self.original_backup_path in choices
            else (choices[0] if choices else None)
        )
        if selected is None or selected not in choices:
            raise PatchError("No valid BookFlow backup was selected")
        try:
            restored = selected.read_bytes()
            backup_document = KoboConf.from_bytes(restored)
        except (OSError, ConfError) as exc:
            raise PatchError("Selected backup is not a readable Kobo config") from exc
        if not backup_document.has_usable_structure():
            raise PatchError("Selected backup is not a usable Kobo config")
        current = self._read_current()
        safety = self._timestamp_backup(current, "pre-restore")
        self._atomic_replace(restored, current)
        if _sha256(self.path.read_bytes()) != _sha256(restored):
            raise PatchError("Backup checksum verification failed")
        return PatchResult(
            self.path, safety, backup_document.endpoint() or "restored configuration"
        )

    def restore_official_sync(self) -> PatchResult:
        current, updated = self._update_endpoint(OFFICIAL_KOBO_ENDPOINT, create_section=True)
        safety = self._timestamp_backup(current, "pre-official-restore")
        self._atomic_replace(updated, current)
        return PatchResult(self.path, safety, OFFICIAL_KOBO_ENDPOINT)
