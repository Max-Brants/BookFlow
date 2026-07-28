"""Consistent, verifiable BookFlow configuration backups and staged restores."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import sqlite3
import tempfile
import time
import zipfile
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

_MAGIC = b"SMBK1"
_EXCLUDED_NAMES = frozenset({"backups", "patcher-cache", "logs", "cache", "tmp"})
_EBOOK_SUFFIXES = frozenset({".epub", ".kepub", ".mobi", ".azw3", ".pdf"})
_RESTORE_INTERNAL_PREFIXES = (".restore-staging", ".restore-rollback-")
_RESTORE_MARKER = ".restore-pending.json"


@dataclass(frozen=True, slots=True)
class BackupInfo:
    id: str
    filename: str
    sha256: str
    size_bytes: int
    encrypted: bool
    created_at: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_config_files(config_dir: Path, backup_dir: Path) -> list[Path]:
    files: list[Path] = []
    for path in config_dir.rglob("*"):
        if not path.is_file() or backup_dir in path.parents:
            continue
        # Do not follow an in-config symlink to unrelated host data.  A backup
        # archive is often downloadable by an administrator, so silently
        # including an arbitrary linked file would widen its trust boundary.
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            continue
        if (
            resolved != config_dir and config_dir not in resolved.parents
        ) or backup_dir in resolved.parents:
            continue
        relative = path.relative_to(config_dir)
        if any(part.lower() in _EXCLUDED_NAMES for part in relative.parts):
            continue
        if any(part.startswith(_RESTORE_INTERNAL_PREFIXES) for part in relative.parts):
            continue
        if relative.name == _RESTORE_MARKER or relative.name.startswith("users.db.pre-restore-"):
            continue
        if path.suffix.lower() in _EBOOK_SUFFIXES or path.name.endswith(("-wal", "-shm")):
            continue
        if path.name == "users.db":
            continue
        files.append(path)
    return files


def _fsync_file(path: Path) -> None:
    """Durably flush one completed temporary file before an atomic replacement."""
    # Windows requires a writable file descriptor for ``fsync``.
    with path.open("r+b") as handle:
        os.fsync(handle.fileno())


def _atomic_copy(source: Path, destination: Path) -> None:
    """Copy ``source`` beside ``destination`` and replace it without an unlink window."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as temporary:
        temporary_path = Path(temporary.name)
        try:
            with source.open("rb") as input_file:
                shutil.copyfileobj(input_file, temporary)
            temporary.flush()
            os.fsync(temporary.fileno())
        except Exception:
            with suppress(OSError):
                temporary_path.unlink()
            raise
    with suppress(OSError):
        shutil.copystat(source, temporary_path)
    for attempt in range(6):
        try:
            temporary_path.replace(destination)
            break
        except PermissionError:
            if attempt == 5:
                with suppress(OSError):
                    temporary_path.unlink()
                raise
            # Windows can keep a just-replaced SQLite file open for a short
            # moment.  Retrying preserves the atomic-replace invariant.
            time.sleep(0.05 * (attempt + 1))
        except Exception:
            with suppress(OSError):
                temporary_path.unlink()
            raise


def _consistent_database_copy(source: Path, destination: Path) -> None:
    """Create a SQLite-consistent copy, including transactions still in WAL."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_connection = sqlite3.connect(source)
    destination_connection = sqlite3.connect(destination)
    try:
        source_connection.backup(destination_connection)
    finally:
        destination_connection.close()
        source_connection.close()
    _fsync_file(destination)


def _safe_restore_target(config_dir: Path, relative: Path) -> Path:
    """Return a non-symlinked config target or reject an escape before writing."""
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise RuntimeError("Unsafe staged restore target")
    if relative.name in {_RESTORE_MARKER, "users.db"} or relative.parts[0] == "backups":
        raise RuntimeError("Unsafe staged restore target")
    target = config_dir.joinpath(relative)
    current = target.parent
    while current != config_dir:
        if current.is_symlink():
            raise RuntimeError("Unsafe staged restore target")
        current = current.parent
    if target.is_symlink():
        raise RuntimeError("Unsafe staged restore target")
    resolved_parent = target.parent.resolve(strict=False)
    if resolved_parent != config_dir and config_dir not in resolved_parent.parents:
        raise RuntimeError("Unsafe staged restore target")
    return target


def _staged_config_entries(config_dir: Path, staging: Path) -> list[tuple[Path, Path, Path]]:
    """Validate every staged config member before mutating the live config tree."""
    config_payload = staging / "config"
    if not config_payload.exists():
        return []
    if config_payload.is_symlink() or not config_payload.is_dir():
        raise RuntimeError("Invalid restore staging configuration")
    entries: list[tuple[Path, Path, Path]] = []
    for source in sorted(config_payload.rglob("*")):
        if source.is_dir():
            continue
        if source.is_symlink() or not source.is_file():
            raise RuntimeError("Unsafe staged restore source")
        try:
            resolved_source = source.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError("Unsafe staged restore source") from exc
        if config_payload not in resolved_source.parents:
            raise RuntimeError("Unsafe staged restore source")
        relative = source.relative_to(config_payload)
        entries.append((relative, source, _safe_restore_target(config_dir, relative)))
    return entries


def _create_restore_safety_archive(config_dir: Path, current_db: Path) -> Path:
    """Archive the complete live recoverable state before a startup restore."""
    safety_dir = config_dir / "backups"
    if safety_dir.exists() and safety_dir.is_symlink():
        raise RuntimeError("Unsafe restore safety-backup directory")
    safety_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    resolved_safety_dir = safety_dir.resolve(strict=True)
    if config_dir not in resolved_safety_dir.parents:
        raise RuntimeError("Unsafe restore safety-backup directory")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = resolved_safety_dir / f"restore-safety-{stamp}-{secrets.token_hex(4)}.zip"
    temporary = resolved_safety_dir / f".{destination.name}.tmp"
    manifest: dict[str, Any] = {
        "format": 1,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "reason": "pre-startup-restore",
        "files": {},
    }
    try:
        with tempfile.TemporaryDirectory(dir=resolved_safety_dir) as temporary_dir:
            database_copy = Path(temporary_dir) / "users.db"
            if current_db.is_file():
                _consistent_database_copy(current_db, database_copy)
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as output:
                if current_db.is_file():
                    output.write(database_copy, "database/users.db")
                    manifest["files"]["database/users.db"] = _sha256(database_copy)
                for path in _safe_config_files(config_dir, resolved_safety_dir):
                    archive_name = (Path("config") / path.relative_to(config_dir)).as_posix()
                    output.write(path, archive_name)
                    manifest["files"][archive_name] = _sha256(path)
                output.writestr(
                    "manifest.json", json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
                )
        _fsync_file(temporary)
        temporary.replace(destination)
        with suppress(OSError):
            destination.chmod(0o600)
    except Exception:
        with suppress(OSError):
            temporary.unlink()
        raise
    return destination


def _snapshot_for_rollback(config_dir: Path, current_db: Path) -> tuple[Path, bool]:
    """Create a private working copy used only to roll back this restore attempt."""
    rollback_root = Path(tempfile.mkdtemp(prefix=".restore-rollback-", dir=config_dir))
    database_existed = current_db.is_file()
    try:
        if database_existed:
            _consistent_database_copy(current_db, rollback_root / "database" / "users.db")
        rollback_config = rollback_root / "config"
        for path in _safe_config_files(config_dir, config_dir / "backups"):
            _atomic_copy(path, rollback_config / path.relative_to(config_dir))
    except Exception:
        shutil.rmtree(rollback_root, ignore_errors=True)
        raise
    return rollback_root, database_existed


def _rollback_restore(
    *,
    config_dir: Path,
    current_db: Path,
    rollback_root: Path,
    database_existed: bool,
    database_changed: bool,
    changed_config: list[tuple[Path, Path, Path]],
) -> None:
    """Restore every already-mutated file from the private rollback snapshot."""
    rollback_db = rollback_root / "database" / "users.db"
    if database_changed and database_existed:
        _atomic_copy(rollback_db, current_db)
    elif database_changed and current_db.exists():
        current_db.unlink()
    rollback_config = rollback_root / "config"
    for relative, _source, target in reversed(changed_config):
        prior = rollback_config / relative
        if prior.is_file():
            _atomic_copy(prior, target)
        elif target.exists():
            # This file was created by the failed restore.  The target was
            # fully validated before mutation, so this narrow unlink is safe.
            target.unlink()


class BackupService:
    def __init__(
        self,
        *,
        database_path: Path,
        config_dir: Path,
        backup_dir: Path,
        encryption_key: str | None = None,
    ) -> None:
        self.database_path = database_path.resolve()
        self.config_dir = config_dir.resolve()
        self.backup_dir = backup_dir.resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self._encryption_key = encryption_key

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.database_path)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _encrypt(self, source: Path, destination: Path) -> None:
        if self._encryption_key is None:
            shutil.copyfile(source, destination)
            return
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:
            raise RuntimeError("Encrypted backups require cryptography") from exc
        key = hashlib.sha256(self._encryption_key.encode()).digest()
        nonce = secrets.token_bytes(12)
        ciphertext = AESGCM(key).encrypt(nonce, source.read_bytes(), _MAGIC)
        destination.write_bytes(_MAGIC + nonce + ciphertext)

    def _decrypt(self, source: Path, destination: Path) -> None:
        raw = source.read_bytes()
        if not raw.startswith(_MAGIC):
            destination.write_bytes(raw)
            return
        if self._encryption_key is None:
            raise RuntimeError("BACKUP_ENCRYPTION_KEY is required")
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = hashlib.sha256(self._encryption_key.encode()).digest()
        destination.write_bytes(AESGCM(key).decrypt(raw[5:17], raw[17:], _MAGIC))

    def create(self, *, created_by: int | None = None) -> BackupInfo:
        now = datetime.now(UTC)
        backup_id = f"{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}"
        suffix = ".smbak" if self._encryption_key else ".zip"
        destination = self.backup_dir / f"bookflow-{backup_id}{suffix}"
        with tempfile.TemporaryDirectory(dir=self.backup_dir) as temp_name:
            temp = Path(temp_name)
            database_copy = temp / "users.db"
            source_conn = sqlite3.connect(self.database_path)
            target_conn = sqlite3.connect(database_copy)
            try:
                source_conn.backup(target_conn)
            finally:
                target_conn.close()
                source_conn.close()
            archive = temp / "archive.zip"
            with self._connect() as schema_conn:
                schema_version = int(
                    schema_conn.execute(
                        "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                    ).fetchone()[0]
                )
            manifest: dict[str, Any] = {
                "format": 1,
                "schema_version": schema_version,
                "created_at": now.isoformat(timespec="seconds"),
                "created_by": created_by,
                "files": {},
            }
            with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
                output.write(database_copy, "database/users.db")
                manifest["files"]["database/users.db"] = _sha256(database_copy)
                for path in _safe_config_files(self.config_dir, self.backup_dir):
                    archive_name = (Path("config") / path.relative_to(self.config_dir)).as_posix()
                    output.write(path, archive_name)
                    manifest["files"][archive_name] = _sha256(path)
                output.writestr(
                    "manifest.json",
                    json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
                )
            self._encrypt(archive, destination)
        with suppress(OSError):
            destination.chmod(0o600)
        info = BackupInfo(
            id=backup_id,
            filename=destination.name,
            sha256=_sha256(destination),
            size_bytes=destination.stat().st_size,
            encrypted=bool(self._encryption_key),
            created_at=now.isoformat(timespec="seconds"),
        )
        self._record(info, created_by=created_by)
        self.apply_retention()
        return info

    def _record(self, info: BackupInfo, *, created_by: int | None) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO backup_records
                    (id, filename, sha256, size_bytes, encrypted, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    info.id,
                    info.filename,
                    info.sha256,
                    info.size_bytes,
                    int(info.encrypted),
                    created_by,
                    info.created_at,
                ),
            )

    def list(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """
                SELECT id, filename, sha256, size_bytes, encrypted, created_at, status, verified_at
                FROM backup_records WHERE status != 'deleted' ORDER BY created_at DESC
                """
            ).fetchall()
        return [dict(row) for row in rows if (self.backup_dir / str(row["filename"])).is_file()]

    def _path(self, backup_id: str) -> Path:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT filename FROM backup_records WHERE id = ? AND status != 'deleted'",
                (backup_id,),
            ).fetchone()
        if row is None:
            raise LookupError("Backup not found")
        path = (self.backup_dir / str(row[0])).resolve()
        if self.backup_dir not in path.parents or not path.is_file():
            raise LookupError("Backup not found")
        return path

    def verify(self, backup_id: str) -> dict[str, Any]:
        path = self._path(backup_id)
        with tempfile.TemporaryDirectory(dir=self.backup_dir) as temp_name:
            archive = Path(temp_name) / "archive.zip"
            self._decrypt(path, archive)
            with zipfile.ZipFile(archive) as source:
                bad = source.testzip()
                manifest = json.loads(source.read("manifest.json"))
                if bad is not None:
                    raise ValueError(f"Corrupt backup member: {bad}")
                for name, expected in manifest["files"].items():
                    if hashlib.sha256(source.read(name)).hexdigest() != expected:
                        raise ValueError(f"Checksum mismatch: {name}")
                with source.open("database/users.db") as db_source:
                    restored_db = Path(temp_name) / "verify.db"
                    restored_db.write_bytes(db_source.read())
                conn = sqlite3.connect(restored_db)
                try:
                    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise ValueError("SQLite integrity check failed")
                    backup_schema = int(
                        conn.execute(
                            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                        ).fetchone()[0]
                    )
                finally:
                    conn.close()
                if int(manifest.get("schema_version", -1)) != backup_schema:
                    raise ValueError("Backup schema manifest does not match its database")
                with self._connect() as current_conn:
                    current_schema = int(
                        current_conn.execute(
                            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
                        ).fetchone()[0]
                    )
                if backup_schema > current_schema:
                    raise ValueError("Backup uses an unsupported newer schema")
        verified_at = datetime.now(UTC).isoformat(timespec="seconds")
        with self._connect() as conn:
            conn.execute(
                "UPDATE backup_records SET verified_at = ?, status = 'available' WHERE id = ?",
                (verified_at, backup_id),
            )
        return {"id": backup_id, "valid": True, "verified_at": verified_at}

    def stage_restore(self, backup_id: str) -> dict[str, Any]:
        self.verify(backup_id)
        source_path = self._path(backup_id)
        staging = self.config_dir / ".restore-staging"
        if staging.exists() and staging.is_symlink():
            raise ValueError("Unsafe restore staging path")
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(mode=0o700)
        archive = staging / "archive.zip"
        self._decrypt(source_path, archive)
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                member_path = Path(member.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError("Unsafe backup path")
                if member.filename == "manifest.json" or member.is_dir():
                    continue
                target = staging / member_path
                resolved_target = target.resolve(strict=False)
                if staging not in resolved_target.parents:
                    raise ValueError("Unsafe backup path")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read(member))
        archive.unlink()
        marker = self.config_dir / ".restore-pending.json"
        if marker.exists() and marker.is_symlink():
            raise ValueError("Unsafe restore marker")
        marker.write_text(
            json.dumps({"backup_id": backup_id, "staging": str(staging)}, sort_keys=True),
            encoding="utf-8",
        )
        with self._connect() as conn:
            conn.execute("UPDATE backup_records SET status = 'staged' WHERE id = ?", (backup_id,))
        return {"id": backup_id, "staged": True, "restart_required": True}

    def delete(self, backup_id: str) -> bool:
        path = self._path(backup_id)
        path.unlink()
        with self._connect() as conn:
            conn.execute("UPDATE backup_records SET status = 'deleted' WHERE id = ?", (backup_id,))
        return True

    def download_path(self, backup_id: str) -> Path:
        return self._path(backup_id)

    def apply_retention(self) -> None:
        """Keep seven daily recovery points and four older weekly ones."""
        entries = sorted(
            self.backup_dir.glob("bookflow-*"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        keep: set[Path] = set()
        daily_dates: set[str] = set()
        timestamps = {path: datetime.fromtimestamp(path.stat().st_mtime, UTC) for path in entries}
        for path in entries:
            day = timestamps[path].strftime("%Y-%m-%d")
            if day not in daily_dates and len(daily_dates) < 7:
                daily_dates.add(day)
                keep.add(path)
        weeks: set[str] = set()
        for path in entries:
            if path in keep:
                continue
            week = timestamps[path].strftime("%G-%V")
            if week not in weeks and len(weeks) < 4:
                weeks.add(week)
                keep.add(path)
        for path in entries:
            if path not in keep:
                path.unlink(missing_ok=True)

    def daily_backup_due(self, now: datetime) -> bool:
        """Return whether today's deterministic jittered automatic backup is due."""
        current = now.astimezone(UTC)
        # Spread instance backups across the first hour after 03:00 UTC without
        # persisting another scheduler table; the durable job key is the date.
        jitter = int(hashlib.sha256(str(self.database_path).encode()).hexdigest()[:8], 16) % 3600
        target = current.replace(hour=3, minute=0, second=0, microsecond=0) + timedelta(
            seconds=jitter
        )
        if current < target:
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MAX(created_at) FROM backup_records WHERE status != 'deleted'"
            ).fetchone()
        if row is None or row[0] is None:
            return True
        latest = datetime.fromisoformat(str(row[0]))
        # SQLite's CURRENT_TIMESTAMP is timezone-naive; normalize it as UTC
        # rather than allowing the host locale to shift the daily cutoff.
        latest = latest.replace(tzinfo=UTC) if latest.tzinfo is None else latest.astimezone(UTC)
        return latest < target


def apply_staged_restore(config_dir: Path) -> bool:
    """Atomically apply a staged restore before any application database opens.

    A restore is deliberately a two-phase operation: all staged input is
    checked first, then the live DB/config are protected by both a durable
    safety archive and a private rollback copy.  The marker and staging tree
    survive any failed apply so an administrator can retry after fixing the
    host-level cause (for example, a full or read-only volume).
    """
    config_dir = config_dir.resolve()
    marker = config_dir / ".restore-pending.json"
    if not marker.is_file():
        return False
    if marker.is_symlink():
        raise RuntimeError("Invalid restore marker")
    payload = json.loads(marker.read_text(encoding="utf-8"))
    staging = Path(str(payload["staging"])).resolve()
    if config_dir not in staging.parents or staging.is_symlink() or not staging.is_dir():
        raise RuntimeError("Invalid restore staging path")
    staged_db = staging / "database" / "users.db"
    if staged_db.is_symlink() or not staged_db.is_file():
        raise RuntimeError("Staged restore has no database")
    try:
        resolved_staged_db = staged_db.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("Staged restore has no database") from exc
    if staging not in resolved_staged_db.parents:
        raise RuntimeError("Invalid staged restore database")
    current_db = config_dir / "users.db"
    if current_db.exists() and current_db.is_symlink():
        raise RuntimeError("Unsafe current database path")

    # Validate all target paths before creating a safety artifact or changing
    # one byte of the live instance.
    staged_entries = _staged_config_entries(config_dir, staging)
    _create_restore_safety_archive(config_dir, current_db)
    rollback_root, database_existed = _snapshot_for_rollback(config_dir, current_db)
    changed_config: list[tuple[Path, Path, Path]] = []
    database_changed = False
    try:
        for entry in staged_entries:
            _relative, source, target = entry
            _atomic_copy(source, target)
            changed_config.append(entry)
        # The database is the commit payload, so replace it last.  A config
        # copy failure then leaves the live database untouched.
        _atomic_copy(staged_db, current_db)
        database_changed = True
    except Exception as restore_error:
        try:
            _rollback_restore(
                config_dir=config_dir,
                current_db=current_db,
                rollback_root=rollback_root,
                database_existed=database_existed,
                database_changed=database_changed,
                changed_config=changed_config,
            )
        except Exception as rollback_error:
            raise RuntimeError(
                "Restore failed and rollback also failed; the safety archive, marker, and staging "
                "have been retained for recovery"
            ) from rollback_error
        finally:
            shutil.rmtree(rollback_root, ignore_errors=True)
        raise RuntimeError(
            "Restore failed; the live database and configuration were rolled back. "
            "The safety archive, marker, and staging have been retained for retry"
        ) from restore_error

    # The marker is the commit point.  It remains untouched if any live-file
    # replacement failed above, preventing an accidental partial retry.
    try:
        marker.unlink()
    except Exception as marker_error:
        try:
            _rollback_restore(
                config_dir=config_dir,
                current_db=current_db,
                rollback_root=rollback_root,
                database_existed=database_existed,
                database_changed=database_changed,
                changed_config=changed_config,
            )
        except Exception as rollback_error:
            raise RuntimeError(
                "Restore commit failed and rollback also failed; the safety archive, marker, and "
                "staging have been retained for recovery"
            ) from rollback_error
        finally:
            shutil.rmtree(rollback_root, ignore_errors=True)
        raise RuntimeError(
            "Restore commit failed; the live database and configuration were rolled back. "
            "The safety archive, marker, and staging have been retained for retry"
        ) from marker_error
    shutil.rmtree(rollback_root, ignore_errors=True)
    shutil.rmtree(staging)
    return True
