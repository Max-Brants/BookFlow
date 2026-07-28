"""One-time, audited removal of retired audiobook data and physical artifacts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from bookflow.core.logger import setup_logger

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

logger = setup_logger(__name__)

AUDIO_FILE_EXTENSIONS = frozenset(
    {".aac", ".flac", ".m4a", ".m4b", ".mp3", ".ogg", ".opus", ".wav", ".wma"}
)
_RETIRED_CONFIG_KEYS = frozenset(
    {
        "AUDIOBOOK_LIBRARY_URL",
        "SUPPORTED_AUDIOBOOK_FORMATS",
        "METADATA_PROVIDER_AUDIOBOOK",
        "DEFAULT_RELEASE_SOURCE_AUDIOBOOK",
        "DESTINATION_AUDIOBOOK",
        "FILE_ORGANIZATION_AUDIOBOOK",
        "TEMPLATE_AUDIOBOOK_RENAME",
        "TEMPLATE_AUDIOBOOK_ORGANIZE",
        "HARDLINK_TORRENTS_AUDIOBOOK",
        "QBITTORRENT_CATEGORY_AUDIOBOOK",
        "TRANSMISSION_CATEGORY_AUDIOBOOK",
        "DELUGE_CATEGORY_AUDIOBOOK",
        "RTORRENT_AUDIOBOOK_LABEL",
        "NZBGET_CATEGORY_AUDIOBOOK",
        "SABNZBD_CATEGORY_AUDIOBOOK",
        "REQUEST_POLICY_DEFAULT_AUDIOBOOK",
    }
)
_ALLOWED_ROOT_KEYS = frozenset(
    {
        "DESTINATION",
        "DESTINATION_AUDIOBOOK",
        "QBITTORRENT_DOWNLOAD_DIR",
        "TRANSMISSION_DOWNLOAD_DIR",
        "DELUGE_DOWNLOAD_DIR",
        "RTORRENT_DOWNLOAD_DIR",
    }
)


def is_retired_audiobook_value(*, content_type: object = None, file_format: object = None) -> bool:
    """Return whether explicit type or a known audio extension identifies retired content."""
    if str(content_type or "").strip().casefold() == "audiobook":
        return True
    normalized_format = str(file_format or "").strip().casefold().lstrip(".")
    return f".{normalized_format}" in AUDIO_FILE_EXTENSIONS if normalized_format else False


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    with suppress(OSError):
        temporary.chmod(0o600)
    temporary.replace(path)


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        logger.warning("Could not inspect retired audiobook settings in %s", path)
        return {}
    return value if isinstance(value, dict) else {}


def _scrub_retired_values(value: Any) -> tuple[Any, list[str]]:
    removed: list[str] = []
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for key, child in value.items():
            normalized_key = str(key).upper()
            if normalized_key in _RETIRED_CONFIG_KEYS or "AUDIOBOOK" in normalized_key:
                removed.append(str(key))
                continue
            cleaned_child, child_removed = _scrub_retired_values(child)
            removed.extend(f"{key}.{item}" for item in child_removed)
            cleaned[str(key)] = cleaned_child
        return cleaned, removed
    if isinstance(value, list):
        cleaned_list = [
            child
            for child in value
            if str(child).strip().casefold() not in {"audiobook", "audiobookbay"}
        ]
        if len(cleaned_list) != len(value):
            removed.append("[]")
        return cleaned_list, removed
    return value, removed


def inspect_and_scrub_retired_config(config_dir: Path) -> tuple[list[Path], dict[str, list[str]]]:
    """Remove retired keys while returning media roots that existed before the scrub."""
    roots: list[Path] = []
    removals: dict[str, list[str]] = {}
    candidates = [config_dir / "settings.json"]
    plugins = config_dir / "plugins"
    if plugins.is_dir():
        candidates.extend(sorted(plugins.glob("*.json")))

    for path in candidates:
        raw = _load_json_object(path)
        for key in _ALLOWED_ROOT_KEYS:
            candidate = raw.get(key)
            if isinstance(candidate, str) and candidate.strip():
                roots.append(Path(candidate.strip()))

        if path.stem.casefold() == "audiobookbay_config":
            removals[str(path)] = ["<entire retired source config>"]
            with suppress(OSError):
                path.unlink()
            continue

        cleaned, removed = _scrub_retired_values(raw)
        if not removed or cleaned == raw:
            continue
        _atomic_json(path, cleaned)
        removals[str(path)] = sorted(set(removed))
    return roots, removals


def _inspect_config_roots(config_dir: Path) -> list[Path]:
    roots: list[Path] = []
    candidates = [config_dir / "settings.json"]
    plugins = config_dir / "plugins"
    if plugins.is_dir():
        candidates.extend(sorted(plugins.glob("*.json")))
    for path in candidates:
        raw = _load_json_object(path)
        for key in _ALLOWED_ROOT_KEYS:
            candidate = raw.get(key)
            if isinstance(candidate, str) and candidate.strip():
                roots.append(Path(candidate.strip()))
    return roots


def _backup_database(conn: sqlite3.Connection, database_path: Path, audit_root: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_path = audit_root / f"{timestamp}.pre-audiobook-retirement.sqlite3"
    audit_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_conn = sqlite3.connect(backup_path)
    try:
        conn.backup(backup_conn)
    finally:
        backup_conn.close()
    with suppress(OSError):
        backup_path.chmod(0o600)
    if not backup_path.is_file() or backup_path.stat().st_size == 0:
        raise OSError(f"Database backup was not created for {database_path}")
    return backup_path


def _rows(conn: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(query).fetchall()]


def _collect_plan(conn: sqlite3.Connection) -> dict[str, Any]:
    file_rows = _rows(
        conn,
        """
        SELECT id, book_id, storage_path, file_format, content_type, import_status
        FROM book_files
        WHERE lower(trim(content_type)) = 'audiobook'
           OR lower(trim(file_format)) IN ('aac','flac','m4a','m4b','mp3','ogg','opus','wav','wma')
        ORDER BY id
        """,
    )
    history_rows = _rows(
        conn,
        """
        SELECT id, task_id, book_id, download_path, format, content_type, final_status
        FROM download_history
        WHERE lower(trim(COALESCE(content_type, ''))) = 'audiobook'
           OR lower(trim(COALESCE(format, ''))) IN
              ('aac','flac','m4a','m4b','mp3','ogg','opus','wav','wma')
        ORDER BY id
        """,
    )
    request_process_rows = _rows(
        conn,
        """
        SELECT id, book_id, status, active_request_attempt_id
        FROM request_processes WHERE lower(trim(content_type)) = 'audiobook' ORDER BY id
        """,
    )
    request_rows = _rows(
        conn,
        """
        SELECT id, book_id, user_id, request_process_id, status
        FROM requests WHERE lower(trim(content_type)) = 'audiobook' ORDER BY id
        """,
    )
    request_process_ids = [int(row["id"]) for row in request_process_rows]
    attempts: list[dict[str, Any]] = []
    if request_process_ids:
        attempts = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, request_process_id, client_type, external_job_id, status, completed_path
                FROM request_attempts ORDER BY id
                """
            ).fetchall()
            if int(row["request_process_id"]) in request_process_ids
        ]

    book_ids = sorted(
        {
            int(row["book_id"])
            for rows in (file_rows, history_rows, request_process_rows, request_rows)
            for row in rows
            if row.get("book_id") is not None
        }
    )
    paths: list[dict[str, Any]] = []
    for table, rows, column in (
        ("book_files", file_rows, "storage_path"),
        ("download_history", history_rows, "download_path"),
        ("request_attempts", attempts, "completed_path"),
    ):
        for row in rows:
            raw_path = row.get(column)
            if isinstance(raw_path, str) and raw_path.strip():
                paths.append(
                    {
                        "table": table,
                        "row_id": int(row["id"]),
                        "path": raw_path.strip(),
                    }
                )
    return {
        "book_files": file_rows,
        "download_history": history_rows,
        "request_processes": request_process_rows,
        "requests": request_rows,
        "request_attempts": attempts,
        "candidate_book_ids": book_ids,
        "paths": paths,
    }


def _normalized_roots(roots: Iterable[Path]) -> tuple[Path, ...]:
    normalized: list[Path] = []
    for root in roots:
        try:
            candidate = root.expanduser().resolve(strict=False)
        except OSError, RuntimeError:
            continue
        if candidate not in normalized:
            normalized.append(candidate)
    return tuple(normalized)


def _allowed_path(raw_path: str, roots: tuple[Path, ...]) -> tuple[Path | None, str | None]:
    try:
        candidate = Path(raw_path).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return None, f"unresolvable path: {exc}"
    matching_roots = [root for root in roots if candidate.is_relative_to(root)]
    if not matching_roots:
        return None, "outside configured library, staging, and download roots"
    if candidate in matching_roots:
        return None, "refused to delete an allowed root itself"
    return candidate, None


def _delete_exact_artifact(path: Path, roots: tuple[Path, ...]) -> list[str]:
    deleted: list[str] = []
    if not path.exists() and not path.is_symlink():
        return deleted
    if path.is_file() or path.is_symlink():
        path.unlink()
        return [str(path)]
    if not path.is_dir():
        return deleted

    # A recorded audiobook directory is exact task output. Resolve each child
    # independently so a symlink can never escape the validated roots.
    children = sorted(path.rglob("*"), key=lambda item: len(item.parts), reverse=True)
    for child in children:
        resolved, error = _allowed_path(str(child), roots)
        if error is not None or resolved is None:
            continue
        if resolved.is_file() or resolved.is_symlink():
            resolved.unlink()
            deleted.append(str(resolved))
        elif resolved.is_dir():
            with suppress(OSError):
                resolved.rmdir()
    with suppress(OSError):
        path.rmdir()
    return deleted


def _delete_retired_audio_files(roots: tuple[Path, ...]) -> list[str]:
    """Delete unregistered retired audio files, bounded to configured roots."""
    deleted: list[str] = []
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in root.rglob("*"):
            if candidate.suffix.casefold() not in AUDIO_FILE_EXTENSIONS:
                continue
            path, error = _allowed_path(str(candidate), roots)
            if error is not None or path is None:
                logger.warning("Retained unsafe retired audio path %s: %s", candidate, error)
                continue
            if not path.is_file() and not path.is_symlink():
                continue
            try:
                path.unlink()
            except OSError as exc:
                logger.warning("Could not delete retired audio file %s: %s", path, exc)
            else:
                deleted.append(str(path))
    return deleted


def discard_late_audiobook_artifacts(task: Any, *, allowed_roots: Iterable[Path]) -> list[str]:
    """Delete exact output paths from a retired audiobook callback."""
    if not is_retired_audiobook_value(
        content_type=getattr(task, "content_type", None),
        file_format=getattr(task, "format", None),
    ):
        return []
    roots = _normalized_roots(allowed_roots)
    raw_paths = list(getattr(task, "library_paths", []) or [])
    for attribute in ("download_path", "staged_path", "original_download_path"):
        value = getattr(task, attribute, None)
        if isinstance(value, str) and value.strip():
            raw_paths.append(value.strip())
    deleted: list[str] = []
    for raw_path in dict.fromkeys(raw_paths):
        path, error = _allowed_path(raw_path, roots)
        if error is not None or path is None:
            logger.warning("Retained unsafe late audiobook path %s: %s", raw_path, error)
            continue
        with suppress(OSError):
            deleted.extend(_delete_exact_artifact(path, roots))
    return deleted


def _delete_background_jobs(conn: sqlite3.Connection, request_process_ids: set[int]) -> int:
    if not request_process_ids:
        return 0
    delete_ids: list[int] = []
    for row in conn.execute(
        "SELECT id, job_key, payload_json FROM background_jobs WHERE status IN ('queued','running')"
    ):
        try:
            payload = json.loads(row["payload_json"])
        except TypeError, json.JSONDecodeError:
            payload = {}
        payload_request_process = (
            payload.get("request_process_id") if isinstance(payload, dict) else None
        )
        key = str(row["job_key"])
        if payload_request_process in request_process_ids or any(
            f":{request_process_id}" in key for request_process_id in request_process_ids
        ):
            delete_ids.append(int(row["id"]))
    conn.executemany("DELETE FROM background_jobs WHERE id = ?", [(item,) for item in delete_ids])
    return len(delete_ids)


def _purge_database_rows(conn: sqlite3.Connection, plan: Mapping[str, Any]) -> dict[str, int]:
    file_ids = {int(row["id"]) for row in plan["book_files"]}
    history_ids = {int(row["id"]) for row in plan["download_history"]}
    request_process_ids = {int(row["id"]) for row in plan["request_processes"]}
    request_ids = {int(row["id"]) for row in plan["requests"]}
    candidate_book_ids = {int(value) for value in plan["candidate_book_ids"]}

    summary = {
        "background_jobs": _delete_background_jobs(conn, request_process_ids),
        "requests": len(request_ids),
        "request_processes": len(request_process_ids),
        "book_files": len(file_ids),
        "download_history": len(history_ids),
        "books": 0,
    }
    if file_ids:
        placeholders = ",".join("?" for _ in file_ids)
        conn.execute(
            f"UPDATE book_files SET derived_from_file_id = NULL "  # noqa: S608
            f"WHERE derived_from_file_id IN ({placeholders})",
            tuple(file_ids),
        )
    conn.executemany("DELETE FROM requests WHERE id = ?", [(item,) for item in request_ids])
    conn.executemany(
        "DELETE FROM request_processes WHERE id = ?", [(item,) for item in request_process_ids]
    )
    conn.executemany("DELETE FROM book_files WHERE id = ?", [(item,) for item in file_ids])
    conn.executemany("DELETE FROM download_history WHERE id = ?", [(item,) for item in history_ids])

    for book_id in candidate_book_ids:
        ebook_evidence = conn.execute(
            """
            SELECT
                EXISTS(SELECT 1 FROM book_files WHERE book_id = ?) OR
                EXISTS(SELECT 1 FROM requests WHERE book_id = ? AND content_type = 'ebook') OR
                EXISTS(SELECT 1 FROM request_processes WHERE book_id = ? AND content_type = 'ebook') OR
                EXISTS(SELECT 1 FROM download_history WHERE book_id = ?) OR
                EXISTS(SELECT 1 FROM bestseller_entries WHERE book_id = ?)
            """,
            (book_id, book_id, book_id, book_id, book_id),
        ).fetchone()[0]
        if not ebook_evidence:
            summary["books"] += conn.execute("DELETE FROM books WHERE id = ?", (book_id,)).rowcount
    return summary


def retire_audiobooks(
    *,
    database_path: Path,
    config_dir: Path,
    staging_root: Path,
    library_root: Path,
    cancel_download: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Run the safe retirement once and return its audit summary."""
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    audit_root = config_dir / "migration-audit" / "audiobook-retirement"
    try:
        state = conn.execute(
            "SELECT status, summary_json FROM audiobook_retirement_runs WHERE id = 1"
        ).fetchone()
        if state is not None and state["status"] == "completed":
            current_roots = _normalized_roots(
                [library_root, staging_root, *_inspect_config_roots(config_dir)]
            )
            deleted_after_completion = _delete_retired_audio_files(current_roots)
            _, removals = inspect_and_scrub_retired_config(config_dir)
            summary = json.loads(state["summary_json"] or "{}")
            summary["config_removals_after_completion"] = removals
            summary["deleted_physical_files_after_completion"] = len(deleted_after_completion)
            return summary

        plan = _collect_plan(conn)
        config_roots = _inspect_config_roots(config_dir)
        roots = _normalized_roots([library_root, staging_root, *config_roots])
        backup_path = _backup_database(conn, database_path, audit_root)
        _, config_removals = inspect_and_scrub_retired_config(config_dir)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
        manifest_path = audit_root / f"{timestamp}.manifest.json"
        manifest: dict[str, Any] = {
            "created_at": _utc_now(),
            "database_path": str(database_path.resolve(strict=False)),
            "backup_path": str(backup_path),
            "backup_sha256": hashlib.sha256(backup_path.read_bytes()).hexdigest(),
            "allowed_roots": [str(root) for root in roots],
            "config_removals": config_removals,
            "records": plan,
            "file_results": [],
            "status": "planned",
        }
        _atomic_json(manifest_path, manifest)
        conn.execute(
            """
            UPDATE audiobook_retirement_runs
            SET status = 'running', started_at = ?, completed_at = NULL,
                backup_path = ?, manifest_path = ?, summary_json = '{}', error_message = NULL
            WHERE id = 1
            """,
            (_utc_now(), str(backup_path), str(manifest_path)),
        )
        conn.commit()

        cancelled: list[str] = []
        if cancel_download is not None:
            task_ids = {
                str(row["task_id"])
                for row in plan["download_history"]
                if str(row.get("task_id") or "").strip()
            }
            task_ids.update(
                str(row["external_job_id"]).split(":", 1)[-1]
                for row in plan["request_attempts"]
                if row.get("client_type") == "legacy_queue" and row.get("external_job_id")
            )
            for task_id in sorted(task_ids):
                with suppress(OSError, RuntimeError, TypeError, ValueError):
                    if cancel_download(task_id):
                        cancelled.append(task_id)

        for item in plan["paths"]:
            result = dict(item)
            path, error = _allowed_path(str(item["path"]), roots)
            if error is not None or path is None:
                result.update({"status": "retained", "reason": error})
            else:
                try:
                    deleted = _delete_exact_artifact(path, roots)
                    result.update(
                        {
                            "status": "deleted" if deleted else "missing",
                            "deleted_paths": deleted,
                        }
                    )
                except OSError as exc:
                    result.update({"status": "retained", "reason": str(exc)})
            manifest["file_results"].append(result)

        orphan_files = _delete_retired_audio_files(roots)
        manifest["unregistered_audio_files_deleted"] = orphan_files

        conn.execute("BEGIN IMMEDIATE")
        database_summary = _purge_database_rows(conn, plan)
        summary = {
            "database": database_summary,
            "cancelled_tasks": cancelled,
            "deleted_physical_files": sum(
                len(item.get("deleted_paths", [])) for item in manifest["file_results"]
            )
            + len(orphan_files),
            "retained_unsafe_or_failed_paths": sum(
                item.get("status") == "retained" for item in manifest["file_results"]
            ),
            "config_files_changed": len(config_removals),
        }
        conn.execute(
            """
            UPDATE audiobook_retirement_runs
            SET status = 'completed', completed_at = ?, summary_json = ?, error_message = NULL
            WHERE id = 1
            """,
            (_utc_now(), json.dumps(summary, sort_keys=True)),
        )
        conn.commit()
        manifest.update({"status": "completed", "completed_at": _utc_now(), "summary": summary})
        _atomic_json(manifest_path, manifest)
        logger.info("Audiobook retirement completed: %s", summary)
        return summary  # noqa: TRY300 - keeps failure-state persistence in one handler
    except Exception as exc:
        conn.rollback()
        with suppress(sqlite3.Error):
            conn.execute(
                """
                UPDATE audiobook_retirement_runs
                SET status = 'failed', completed_at = ?, error_message = ?
                WHERE id = 1
                """,
                (_utc_now(), str(exc)[:2000]),
            )
            conn.commit()
        raise
    finally:
        conn.close()
