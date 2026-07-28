from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from bookflow.core.audiobook_retirement import retire_audiobooks
from bookflow.core.request_workflow_service import (
    RequestWorkflowError,
    RequestWorkflowService,
)
from bookflow.core.user_db import UserDB
from bookflow.download.orchestrator import queue_release

_WRITE_GUARDS = (
    "reject_audiobook_request_insert",
    "reject_audiobook_request_update",
    "reject_audiobook_request_process_insert",
    "reject_audiobook_request_process_update",
    "reject_audiobook_file_insert",
    "reject_audiobook_file_update",
    "reject_audiobook_history_insert",
    "reject_audiobook_history_update",
)


def _seed_legacy_audiobook(database_path: Path, audio_path: Path) -> None:
    with sqlite3.connect(database_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for trigger in _WRITE_GUARDS:
            conn.execute(f"DROP TRIGGER {trigger}")
        user_id = conn.execute(
            """
            INSERT INTO users (username, auth_source, role, is_active)
            VALUES ('reader', 'builtin', 'user', 1)
            """
        ).lastrowid
        book_id = conn.execute(
            """
            INSERT INTO books (metadata_provider, provider_book_id, title, metadata_json)
            VALUES ('legacy', 'audio-only', 'Retired audio', '{}')
            """
        ).lastrowid
        file_id = conn.execute(
            """
            INSERT INTO book_files (
                book_id, storage_path, file_format, size_bytes, sha256,
                import_status, content_type
            ) VALUES (?, ?, 'm4b', ?, ?, 'imported', 'audiobook')
            """,
            (book_id, str(audio_path), audio_path.stat().st_size, "a" * 64),
        ).lastrowid
        request_process_id = conn.execute(
            """
            INSERT INTO request_processes (
                book_id, content_type, profile_hash, profile_snapshot_json, status
            ) VALUES (?, 'audiobook', ?, '{}', 'completed')
            """,
            (book_id, "b" * 64),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO requests (
                user_id, book_id, request_process_id, content_type, profile_hash,
                profile_snapshot_json, status, fulfilled_file_id
            ) VALUES (?, ?, ?, 'audiobook', ?, '{}', 'fulfilled', ?)
            """,
            (user_id, book_id, request_process_id, "b" * 64, file_id),
        )
        conn.execute(
            """
            INSERT INTO download_history (
                task_id, user_id, source, title, format, content_type,
                final_status, download_path, book_id
            ) VALUES ('legacy-audio', ?, 'legacy', 'Retired audio', 'm4b',
                      'audiobook', 'complete', ?, ?)
            """,
            (user_id, str(audio_path), book_id),
        )


def test_retirement_backs_up_audits_purges_and_is_idempotent(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    library_root = tmp_path / "library"
    library_root.mkdir()
    staging_root = tmp_path / "staging"
    staging_root.mkdir()
    audio_path = library_root / "retired.m4b"
    audio_path.write_bytes(b"retired audio")
    orphan_audio_path = library_root / "unregistered.mp3"
    orphan_audio_path.write_bytes(b"unregistered retired audio")
    ebook_path = library_root / "keep.epub"
    ebook_path.write_bytes(b"ebook")
    database_path = config_dir / "users.db"
    UserDB(str(database_path)).initialize()
    _seed_legacy_audiobook(database_path, audio_path)
    (config_dir / "settings.json").write_text(
        json.dumps(
            {
                "DESTINATION": str(library_root),
                "DESTINATION_AUDIOBOOK": str(library_root),
                "SUPPORTED_AUDIOBOOK_FORMATS": ["m4b", "mp3"],
                "SUPPORTED_FORMATS": ["epub"],
            }
        ),
        encoding="utf-8",
    )

    summary = retire_audiobooks(
        database_path=database_path,
        config_dir=config_dir,
        staging_root=staging_root,
        library_root=library_root,
    )

    assert summary["database"]["book_files"] == 1
    assert summary["database"]["requests"] == 1
    assert summary["database"]["request_processes"] == 1
    assert summary["database"]["books"] == 1
    assert not audio_path.exists()
    assert not orphan_audio_path.exists()
    assert ebook_path.is_file()
    persisted_config = json.loads((config_dir / "settings.json").read_text(encoding="utf-8"))
    assert persisted_config == {
        "DESTINATION": str(library_root),
        "SUPPORTED_FORMATS": ["epub"],
    }

    with sqlite3.connect(database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0
        run = conn.execute(
            "SELECT status, backup_path, manifest_path FROM audiobook_retirement_runs WHERE id = 1"
        ).fetchone()
    assert run is not None
    assert run[0] == "completed"
    assert Path(run[1]).is_file()
    manifest = json.loads(Path(run[2]).read_text(encoding="utf-8"))
    assert manifest["status"] == "completed"
    assert manifest["records"]["book_files"][0]["storage_path"] == str(audio_path)

    repeated = retire_audiobooks(
        database_path=database_path,
        config_dir=config_dir,
        staging_root=staging_root,
        library_root=library_root,
    )
    assert repeated["database"] == summary["database"]

    late_orphan = library_root / "late-orphan.flac"
    late_orphan.write_bytes(b"late retired audio")
    repeated = retire_audiobooks(
        database_path=database_path,
        config_dir=config_dir,
        staging_root=staging_root,
        library_root=library_root,
    )
    assert repeated["deleted_physical_files_after_completion"] == 1
    assert not late_orphan.exists()


def test_new_audiobook_requests_and_downloads_are_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "users.db"
    user_db = UserDB(str(database_path))
    user_db.initialize()
    user = user_db.create_user(username="reader", password_hash="hash")
    with sqlite3.connect(database_path) as conn:
        book_id = conn.execute(
            """
            INSERT INTO books (metadata_provider, provider_book_id, title, metadata_json)
            VALUES ('test', 'book-1', 'Book', '{}')
            """
        ).lastrowid

    try:
        RequestWorkflowService(database_path).create_request(
            user_id=int(user["id"]),
            book_id=int(book_id),
            profile={},
            content_type="audiobook",
        )
    except RequestWorkflowError as exc:
        assert exc.code == "invalid_content_type"
    else:
        raise AssertionError("Audiobook request unexpectedly succeeded")

    success, message = queue_release(
        {
            "source": "direct_download",
            "source_id": "retired-audio",
            "title": "Retired audio",
            "format": "m4b",
        }
    )
    assert success is False
    assert message == "Audiobooks are no longer supported"
