"""Synthetic contract tests for the isolated, non-reference Kobo MVP."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from flask import Flask

from bookflow.core.catalog_monitor_service import CatalogMonitorService
from bookflow.core.kobo_db import KOB0_DB_SQL
from bookflow.core.kobo_routes import KOB0_CONTRACT_FIXTURES, register_kobo_routes
from bookflow.core.kobo_services import (
    KoboAuthenticationError,
    KoboCursorError,
    KoboEntitlementError,
    KoboRateLimitError,
    KoboSyncService,
    TokenService,
    redact_kobo_token,
)
from bookflow.core.kobo_settings_routes import register_kobo_settings_routes
from bookflow.core.user_db import UserDB
from bookflow.core.v1_api import V1Actor


@pytest.fixture
def kobo_fixture(tmp_path: Path):
    db_path = tmp_path / "users.db"
    user_db = UserDB(str(db_path))
    user_db.initialize()
    user = user_db.create_user(username="kobo-reader")
    other_user = user_db.create_user(username="other-reader")
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    stored_file = storage_root / "book.epub"
    stored_file.write_bytes(b"synthetic kobo ebook")
    conn = user_db._connect()
    try:
        book_id = conn.execute(
            """
            INSERT INTO books (metadata_provider, provider_book_id, title, author, cover_url)
            VALUES ('test', 'kobo-book', 'Synthetic Kobo Book', 'BookFlow', 'https://covers.invalid/book')
            """
        ).lastrowid
        assert book_id is not None
        file_id = conn.execute(
            """
            INSERT INTO book_files (
                book_id, storage_path, file_format, size_bytes, sha256, import_status
            ) VALUES (?, ?, 'epub', ?, ?, 'imported')
            """,
            (book_id, str(stored_file), stored_file.stat().st_size, "a" * 64),
        ).lastrowid
        assert file_id is not None
        conn.execute(
            "INSERT INTO user_file_entitlements (user_id, file_id) VALUES (?, ?)",
            (user["id"], file_id),
        )
        conn.commit()
    finally:
        conn.close()
    tokens = TokenService(str(db_path), pepper="test-token-pepper")
    sync = KoboSyncService(str(db_path), cursor_secret="test-cursor-secret")
    tokens.initialize()
    sync.enable_user(user_id=user["id"])
    sync.enable_user(user_id=other_user["id"])
    return {
        "db_path": db_path,
        "user": user,
        "other_user": other_user,
        "book_id": int(book_id),
        "file_id": int(file_id),
        "storage_root": storage_root,
        "tokens": tokens,
        "sync": sync,
    }


def test_kobo_schema_is_additive_and_changes_are_append_only(kobo_fixture) -> None:
    assert "user_kobo_settings" in KOB0_DB_SQL
    sync: KoboSyncService = kobo_fixture["sync"]
    revision = sync.set_book(
        user_id=kobo_fixture["user"]["id"],
        book_id=kobo_fixture["book_id"],
        file_id=kobo_fixture["file_id"],
    )
    conn = UserDB(str(kobo_fixture["db_path"]))._connect()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(
                "UPDATE user_kobo_changes SET payload_json = '{}' WHERE revision = ?", (revision,)
            )
    finally:
        conn.close()


def test_tokens_store_only_hmac_and_rotation_revokes_old_token(kobo_fixture) -> None:
    tokens: TokenService = kobo_fixture["tokens"]
    issued = tokens.issue_token(user_id=kobo_fixture["user"]["id"], device_label="Libra 2")
    authenticated = tokens.authenticate(token=issued.token, source_ip="203.0.113.10")
    rotated = tokens.rotate_token(user_id=kobo_fixture["user"]["id"], token_id=issued.token_id)

    assert authenticated.user_id == kobo_fixture["user"]["id"]
    assert len(issued.token) >= 43
    conn = UserDB(str(kobo_fixture["db_path"]))._connect()
    try:
        persisted_hash = conn.execute(
            "SELECT token_hash, device_label FROM kobo_tokens WHERE id = ?", (issued.token_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert persisted_hash != issued.token
    assert issued.token not in redact_kobo_token(issued.token)
    assert (
        tokens.authenticate(token=rotated.token, source_ip="203.0.113.10").user_id
        == authenticated.user_id
    )
    with pytest.raises(KoboAuthenticationError):
        tokens.authenticate(token=issued.token, source_ip="203.0.113.10")
    conn = UserDB(str(kobo_fixture["db_path"]))._connect()
    try:
        replacement_label = conn.execute(
            "SELECT device_label FROM kobo_tokens WHERE id = ?", (rotated.token_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert replacement_label == "Libra 2"


def test_issuing_replacement_keeps_only_one_active_kobo_token(kobo_fixture) -> None:
    tokens: TokenService = kobo_fixture["tokens"]
    first = tokens.issue_token(user_id=kobo_fixture["user"]["id"])
    second = tokens.issue_token(user_id=kobo_fixture["user"]["id"])

    with pytest.raises(KoboAuthenticationError):
        tokens.authenticate(token=first.token, source_ip="203.0.113.20")
    assert (
        tokens.authenticate(token=second.token, source_ip="203.0.113.20").token_id
        == second.token_id
    )
    conn = UserDB(str(kobo_fixture["db_path"]))._connect()
    try:
        active = conn.execute(
            "SELECT COUNT(*) FROM kobo_tokens WHERE user_id = ? AND revoked_at IS NULL",
            (kobo_fixture["user"]["id"],),
        ).fetchone()[0]
    finally:
        conn.close()
    assert active == 1


def test_kobo_sync_audit_flags_three_consecutive_ip_switches(kobo_fixture) -> None:
    user_db = UserDB(str(kobo_fixture["db_path"]))
    for source_ip in ("203.0.113.10", "198.51.100.20", "203.0.113.10", "198.51.100.20"):
        user_db.record_kobo_sync(
            user_id=kobo_fixture["user"]["id"],
            token_id=None,
            source_ip=source_ip,
            user_agent="Kobo",
            status="completed",
        )

    kobo = user_db.get_admin_user_audit(kobo_fixture["user"]["id"])["kobo"]
    assert kobo["ip_switch_streak"] == 3
    assert kobo["suspicious"] is True


def test_token_and_ip_rate_limit_is_persisted(kobo_fixture) -> None:
    limited = TokenService(
        str(kobo_fixture["db_path"]),
        pepper="test-token-pepper",
        max_requests_per_window=1,
    )
    issued = limited.issue_token(user_id=kobo_fixture["user"]["id"])
    limited.authenticate(token=issued.token, source_ip="203.0.113.11")
    with pytest.raises(KoboRateLimitError):
        limited.authenticate(token=issued.token, source_ip="203.0.113.11")
    conn = UserDB(str(kobo_fixture["db_path"]))._connect()
    try:
        row = conn.execute(
            """
            SELECT request_count, blocked_until FROM kobo_auth_rate_limits
            WHERE source_ip = ?
            """,
            ("203.0.113.11",),
        ).fetchone()
    finally:
        conn.close()
    assert tuple(row)[0] == 2
    assert row["blocked_until"] is not None


def test_unknown_token_prefix_is_persistently_rate_limited(kobo_fixture) -> None:
    limited = TokenService(
        str(kobo_fixture["db_path"]),
        pepper="test-token-pepper",
        max_requests_per_window=1,
    )
    with pytest.raises(KoboAuthenticationError):
        limited.authenticate(token="unknown-token-prefix-value", source_ip="203.0.113.12")
    with pytest.raises(KoboRateLimitError):
        limited.authenticate(token="unknown-token-prefix-value", source_ip="203.0.113.12")


def test_authenticated_settings_token_and_personal_shelf_routes(kobo_fixture) -> None:
    app = Flask(__name__)
    app.config["TESTING"] = True
    actor = {"value": V1Actor(kobo_fixture["user"]["id"])}
    register_kobo_settings_routes(
        app,
        db_path=str(kobo_fixture["db_path"]),
        resolve_actor=lambda: actor["value"],
        token_service=kobo_fixture["tokens"],
        sync_service=kobo_fixture["sync"],
    )
    client = app.test_client()

    issued = client.post("/api/v1/users/me/kobo-token", json={"device_label": "Bedroom Kobo"})
    added = client.put(
        f"/api/v1/users/me/kobo-books/{kobo_fixture['book_id']}",
        json={"file_id": kobo_fixture["file_id"], "preferred_format": "epub"},
    )
    settings = client.get("/api/v1/users/me/kobo-settings")
    revoked = client.delete(f"/api/v1/users/me/kobo-token/{issued.json['token_id']}")
    after_revoke = client.get("/api/v1/users/me/kobo-settings")
    actor["value"] = V1Actor(kobo_fixture["other_user"]["id"])
    denied = client.put(
        f"/api/v1/users/me/kobo-books/{kobo_fixture['book_id']}",
        json={"file_id": kobo_fixture["file_id"]},
    )

    assert issued.status_code == 201
    assert issued.json["shown_once"] is True
    assert issued.json["token"] in issued.json["sync_url"]
    assert added.status_code == 202
    assert settings.json["enabled"] is True
    assert settings.json["tokens"][0]["token_prefix"] == issued.json["prefix"]
    assert settings.json["tokens"][0]["device_label"] == "Bedroom Kobo"
    assert revoked.status_code == 200
    assert revoked.json["revoked"] is True
    assert after_revoke.json["tokens"] == []
    assert denied.status_code == 404


def test_sync_cursor_is_user_bound_and_high_water_is_deterministic(kobo_fixture) -> None:
    sync: KoboSyncService = kobo_fixture["sync"]
    user_id = kobo_fixture["user"]["id"]
    for _ in range(101):
        sync.set_book(
            user_id=user_id,
            book_id=kobo_fixture["book_id"],
            file_id=kobo_fixture["file_id"],
        )

    first = sync.sync(user_id=user_id)
    sync.delete_book(user_id=user_id, book_id=kobo_fixture["book_id"])
    assert len(first.changes) == 100
    assert first.has_more is True
    assert first.cursor is not None
    resumed = sync.sync(user_id=user_id, cursor=first.cursor)
    assert [change["revision"] for change in resumed.changes] == [101]
    assert resumed.has_more is False
    with pytest.raises(KoboCursorError):
        sync.sync(user_id=kobo_fixture["other_user"]["id"], cursor=first.cursor)


def test_reading_state_is_entitlement_scoped_and_part_of_kobo_changelog(kobo_fixture) -> None:
    sync: KoboSyncService = kobo_fixture["sync"]
    user_id = kobo_fixture["user"]["id"]
    sync.set_book(user_id=user_id, book_id=kobo_fixture["book_id"], file_id=kobo_fixture["file_id"])
    updated = sync.set_reading_state(user_id=user_id, book_id=kobo_fixture["book_id"], progress=45)

    assert updated["progress"] == 45
    assert sync.get_reading_state(user_id=user_id, book_id=kobo_fixture["book_id"])["active"] == 1
    assert sync.sync(user_id=user_id).changes[-1]["type"] == "progress"
    with pytest.raises(KoboEntitlementError):
        sync.set_reading_state(
            user_id=kobo_fixture["other_user"]["id"], book_id=kobo_fixture["book_id"], progress=45
        )


def test_kobo_state_route_rejects_device_requested_progress_reset(kobo_fixture) -> None:
    sync: KoboSyncService = kobo_fixture["sync"]
    user_id = kobo_fixture["user"]["id"]
    book_id = kobo_fixture["book_id"]
    sync.set_book(user_id=user_id, book_id=book_id, file_id=kobo_fixture["file_id"])
    sync.set_reading_state(user_id=user_id, book_id=book_id, progress=60)
    token = kobo_fixture["tokens"].issue_token(user_id=user_id)
    app = Flask(__name__)
    register_kobo_routes(
        app,
        token_service=kobo_fixture["tokens"],
        sync_service=sync,
        allowed_file_roots=(kobo_fixture["storage_root"],),
        tls_guard=lambda: True,
    )

    response = app.test_client().put(
        f"/api/kobo/{token.token}/v1/library/{book_id}/state",
        json={"Progress": 10, "Reset": True},
    )

    assert response.status_code == 409
    assert sync.get_reading_state(user_id=user_id, book_id=book_id)["progress"] == 60


def test_library_sync_route_records_audit_event(kobo_fixture) -> None:
    user_id = kobo_fixture["user"]["id"]
    token = kobo_fixture["tokens"].issue_token(user_id=user_id)
    user_db = UserDB(str(kobo_fixture["db_path"]))
    app = Flask(__name__)
    register_kobo_routes(
        app,
        token_service=kobo_fixture["tokens"],
        sync_service=kobo_fixture["sync"],
        allowed_file_roots=(kobo_fixture["storage_root"],),
        tls_guard=lambda: True,
        sync_audit_recorder=user_db.record_kobo_sync,
    )

    response = app.test_client().get(
        f"/api/kobo/{token.token}/v1/library/sync",
        headers={"User-Agent": "Kobo-test"},
        environ_base={"REMOTE_ADDR": "203.0.113.90"},
    )

    assert response.status_code == 200
    syncs = user_db.get_admin_user_audit(user_id)["kobo"]["recent_syncs"]
    assert syncs[0]["token_id"] == token.token_id
    assert syncs[0]["source_ip"] == "203.0.113.90"
    assert syncs[0]["status"] == "completed"


def test_web_progress_is_emitted_to_an_active_entitled_kobo(kobo_fixture) -> None:
    sync: KoboSyncService = kobo_fixture["sync"]
    user_id = kobo_fixture["user"]["id"]
    sync.set_book(user_id=user_id, book_id=kobo_fixture["book_id"], file_id=kobo_fixture["file_id"])
    conn = UserDB(str(kobo_fixture["db_path"]))._connect()
    try:
        conn.execute(
            "INSERT INTO user_library(user_id, book_id) VALUES (?, ?)",
            (user_id, kobo_fixture["book_id"]),
        )
        conn.commit()
    finally:
        conn.close()

    CatalogMonitorService(str(kobo_fixture["db_path"])).set_progress(
        user_id=user_id, book_id=kobo_fixture["book_id"], progress=63, source="web"
    )

    assert sync.sync(user_id=user_id).changes[-1]["type"] == "progress"


def test_clearing_web_progress_emits_an_append_only_kobo_reset(kobo_fixture) -> None:
    sync: KoboSyncService = kobo_fixture["sync"]
    user_id = kobo_fixture["user"]["id"]
    sync.set_book(user_id=user_id, book_id=kobo_fixture["book_id"], file_id=kobo_fixture["file_id"])
    conn = UserDB(str(kobo_fixture["db_path"]))._connect()
    try:
        conn.execute(
            "INSERT INTO user_library(user_id, book_id) VALUES (?, ?)",
            (user_id, kobo_fixture["book_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    progress = CatalogMonitorService(str(kobo_fixture["db_path"]))
    progress.set_progress(
        user_id=user_id, book_id=kobo_fixture["book_id"], progress=63, source="web"
    )

    assert progress.clear_progress(user_id=user_id, book_id=kobo_fixture["book_id"])
    reset = sync.sync(user_id=user_id).changes[-1]
    assert reset["type"] == "progress"
    assert reset["payload"] == {"progress": 0.0, "active": 0, "source": "web"}


def test_entitlement_required_for_kobo_desired_state_and_routes(kobo_fixture) -> None:
    sync: KoboSyncService = kobo_fixture["sync"]
    with pytest.raises(KoboEntitlementError):
        sync.set_book(
            user_id=kobo_fixture["other_user"]["id"],
            book_id=kobo_fixture["book_id"],
            file_id=kobo_fixture["file_id"],
        )

    sync.set_book(
        user_id=kobo_fixture["user"]["id"],
        book_id=kobo_fixture["book_id"],
        file_id=kobo_fixture["file_id"],
    )
    issued = kobo_fixture["tokens"].issue_token(user_id=kobo_fixture["user"]["id"])
    app = Flask(__name__)
    register_kobo_routes(
        app,
        token_service=kobo_fixture["tokens"],
        sync_service=sync,
        allowed_file_roots=(kobo_fixture["storage_root"],),
        tls_guard=lambda: True,
        cover_fetcher=lambda _cache_id, _url: (b"sanitized-cover", "image/jpeg"),
    )
    client = app.test_client()
    metadata = client.get(f"/api/kobo/{issued.token}/v1/books/{kobo_fixture['book_id']}")
    download = client.get(f"/api/kobo/{issued.token}/v1/files/{kobo_fixture['file_id']}/download")
    compatibility = client.get(f"/api/kobo/{issued.token}/v1/recommendations")
    cover = client.get(f"/api/kobo/{issued.token}/v1/books/{kobo_fixture['book_id']}/cover")

    assert metadata.status_code == 200
    assert metadata.json["File"]["Id"] == kobo_fixture["file_id"]
    assert download.status_code == 200
    assert download.data == b"synthetic kobo ebook"
    assert cover.status_code == 200
    assert cover.data == b"sanitized-cover"
    assert cover.content_type == "image/jpeg"
    assert compatibility.json == KOB0_CONTRACT_FIXTURES["compatibility_empty"]


def test_routes_require_tls_for_external_requests(kobo_fixture) -> None:
    issued = kobo_fixture["tokens"].issue_token(user_id=kobo_fixture["user"]["id"])
    app = Flask(__name__)
    register_kobo_routes(
        app,
        token_service=kobo_fixture["tokens"],
        sync_service=kobo_fixture["sync"],
        allowed_file_roots=(kobo_fixture["storage_root"],),
        tls_guard=lambda: False,
    )
    response = app.test_client().get(f"/api/kobo/{issued.token}/v1/initialization")

    assert response.status_code == 400
    assert response.json["code"] == "tls_required"
