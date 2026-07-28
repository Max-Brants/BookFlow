import json
import os
import sqlite3
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from flask import Flask

from bookflow.core.backup_service import BackupService, apply_staged_restore
from bookflow.core.catalog_monitor_service import CatalogMonitorService
from bookflow.core.kobo_pairing import KoboPairingService, PairingError, PairingRateLimitError
from bookflow.core.kobo_pairing_routes import register_kobo_pairing_routes
from bookflow.core.kobo_services import TokenService
from bookflow.core.metadata_governance import (
    MetadataGovernanceService,
    record_provider_observation,
)
from bookflow.core.monitor_runtime import MonitorRuntime
from bookflow.core.user_db import UserDB
from bookflow.core.web_push import WebPushService
from bookflow.core.web_push_events import enqueue_admin_web_push, enqueue_web_push
from bookflow.core.web_push_routes import register_web_push_routes
from bookflow.metadata_providers import BookMetadata


@pytest.fixture
def platform_db(tmp_path: Path) -> tuple[Path, int, int]:
    db_path = tmp_path / "users.db"
    users = UserDB(str(db_path))
    users.initialize()
    user = users.create_user("reader")
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO books (metadata_provider, provider_book_id, title, author)
            VALUES ('test', 'book-1', 'Old title', 'Writer')
            """
        )
        book_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.close()
    return db_path, int(user["id"]), book_id


def test_pairing_code_is_one_time_and_can_revoke_completed_token(platform_db):
    db_path, user_id, _ = platform_db
    tokens = TokenService(str(db_path), pepper=b"t" * 32)
    service = KoboPairingService(str(db_path), secret=b"s" * 32, token_service=tokens)

    generated = service.create_code(user_id=user_id, origin="https://books.example")
    prefix, encoded, _signature = generated["code"].split(".")
    payload = json.loads(
        __import__("base64").urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
    )
    assert prefix == "SM1"
    assert payload["protocol_version"] == 1
    assert payload["origin"] == "https://books.example"

    claimed = service.claim(code=generated["code"], source_ip="127.0.0.1")
    with pytest.raises(PairingError):
        service.claim(code=generated["code"], source_ip="127.0.0.1")
    completed = service.complete(session=claimed.session, device_label="Clara HD")
    assert completed["api_endpoint"].startswith("https://books.example/api/kobo/")
    assert completed["protocol_version"] == service.PROTOCOL_VERSION
    assert service.revoke_session(session=claimed.session)
    with sqlite3.connect(db_path) as conn:
        token = conn.execute(
            "SELECT device_label, revoked_at FROM kobo_tokens WHERE id = ?",
            (completed["token_id"],),
        ).fetchone()
    assert token[0] == "Clara HD"
    assert token[1] is not None


def test_pairing_claim_rate_limits_invalid_guesses(platform_db):
    db_path, _user_id, _ = platform_db
    service = KoboPairingService(
        str(db_path),
        secret=b"s" * 32,
        token_service=TokenService(str(db_path), pepper=b"t" * 32),
        max_claims_per_window=1,
    )
    with pytest.raises(PairingError):
        service.claim(code="SM1.invalid.invalid", source_ip="198.51.100.1")
    # A changed code still hits the aggregate source-IP limiter; this closes
    # the trivial evasion of changing one byte per anonymous guess.
    with pytest.raises(PairingRateLimitError):
        service.claim(code="SM1.different.invalid", source_ip="198.51.100.1")


def test_pairing_and_push_mutations_require_tls_outside_loopback(platform_db, tmp_path):
    db_path, user_id, _ = platform_db
    app = Flask(__name__)
    app.config["TESTING"] = True
    pairing = KoboPairingService(
        str(db_path), secret=b"s" * 32, token_service=TokenService(str(db_path), pepper=b"t" * 32)
    )

    class Actor:
        is_admin = False

        def __init__(self, identifier: int) -> None:
            self.user_id = identifier

    register_kobo_pairing_routes(
        app,
        resolve_actor=lambda: Actor(user_id),
        service=pairing,
        patcher_cache=tmp_path / "patcher-cache",
    )
    register_web_push_routes(
        app,
        resolve_actor=lambda: Actor(user_id),
        service=WebPushService(str(db_path)),
        vapid_public_key="public-key",
    )
    client = app.test_client()
    public_http = {"REMOTE_ADDR": "8.8.8.8"}

    assert (
        client.post("/api/v1/users/me/kobo-pairing-code", environ_overrides=public_http).status_code
        == 400
    )
    assert (
        client.post(
            "/api/kobo/pair/claim",
            json={"code": "SM1.invalid.invalid"},
            environ_overrides=public_http,
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/v1/users/me/push/subscriptions",
            json={"endpoint": "https://push.example/sub", "keys": {"p256dh": "p", "auth": "a"}},
            environ_overrides=public_http,
        ).status_code
        == 400
    )
    assert (
        client.get("/api/v1/users/me/push/subscriptions", environ_overrides=public_http).status_code
        == 400
    )


def test_metadata_report_apply_and_revert_preserve_history(platform_db):
    db_path, user_id, book_id = platform_db
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            UPDATE books
            SET metadata_json = ?
            WHERE id = ?
            """,
            (
                json.dumps(
                    {
                        "provider": "test",
                        "provider_id": "book-1",
                        "title": "Provider title",
                        "authors": ["Writer", "Co-writer"],
                    }
                ),
                book_id,
            ),
        )
    service = MetadataGovernanceService(str(db_path))
    report = service.report(
        user_id=user_id,
        book_id=book_id,
        fields=["title"],
        explanation="The title is incorrect",
    )
    other_user = UserDB(str(db_path)).create_user("other-reader")
    service.report(
        user_id=int(other_user["id"]),
        book_id=book_id,
        fields=["author"],
        explanation="The author is incorrect",
    )
    assert [item["id"] for item in service.reports(user_id=user_id)] == [report["id"]]
    context = service.preview(book_id=book_id, changes={"title": "Correct title"})
    assert context["current_values"]["title"] == "Old title"
    assert context["provider_values"][0]["values"]["author"] == "Writer, Co-writer"
    applied = service.apply(
        actor_user_id=user_id,
        book_id=book_id,
        changes={"title": "Correct title"},
        reason="Verified against publisher",
        report_id=report["id"],
    )
    assert applied["changes"][0]["after"] == "Correct title"
    assert service.reports(user_id=user_id) == []
    service.revert(
        actor_user_id=user_id,
        book_id=book_id,
        revision_id=applied["revision_id"],
        reason="Undo",
    )
    with sqlite3.connect(db_path) as conn:
        assert (
            conn.execute("SELECT title FROM books WHERE id = ?", (book_id,)).fetchone()[0]
            == "Old title"
        )
        event_types = {
            row[0]
            for row in conn.execute(
                "SELECT event_type FROM book_metadata_field_events WHERE book_id = ?",
                (book_id,),
            )
        }
    assert event_types == {"observed", "applied", "reverted"}
    assert len(service.history(book_id=book_id)) == 2


def test_push_event_producers_are_durable_and_idempotent(platform_db):
    db_path, user_id, book_id = platform_db
    service = MetadataGovernanceService(str(db_path))
    report = service.report(
        user_id=user_id, book_id=book_id, fields=["title"], explanation="Wrong title"
    )
    service.reject_report(actor_user_id=user_id, report_id=report["id"], note="Kept provider value")
    enqueue_web_push(
        str(db_path),
        user_id=user_id,
        event_type="request.status",
        payload={"book_id": book_id, "status": "approved"},
        event_key="request:1:approved",
    )
    enqueue_web_push(
        str(db_path),
        user_id=user_id,
        event_type="request.status",
        payload={"book_id": book_id, "status": "approved"},
        event_key="request:1:approved",
    )
    with sqlite3.connect(db_path) as conn:
        jobs = conn.execute(
            "SELECT payload_json FROM background_jobs WHERE job_type = 'send_web_push'"
        ).fetchall()
    event_types = [json.loads(row[0])["event_type"] for row in jobs]
    assert event_types.count("metadata_report.status") == 2
    assert event_types.count("request.status") == 1


def test_backup_error_producer_targets_all_active_admins(platform_db):
    db_path, _user_id, _book_id = platform_db
    users = UserDB(str(db_path))
    users.create_user("admin", role="admin")
    assert (
        enqueue_admin_web_push(
            str(db_path),
            event_type="backup.error",
            payload={"title": "Failed"},
            event_key="backup:1",
        )
        == 1
    )
    with sqlite3.connect(db_path) as conn:
        payload = json.loads(
            conn.execute(
                "SELECT payload_json FROM background_jobs WHERE job_type = 'send_web_push'"
            ).fetchone()[0]
        )
    assert payload["event_type"] == "backup.error"


class _PushTransport:
    def __init__(self, statuses):
        self.statuses = iter(statuses)

    def send(self, subscription, payload):
        assert subscription["auth"]
        assert payload["event"] == "book.available"
        return next(self.statuses)


def test_web_push_rules_and_expired_subscription_cleanup(platform_db):
    db_path, user_id, _ = platform_db
    service = WebPushService(str(db_path), transport=_PushTransport([201, 410]))
    first = service.subscribe(
        user_id=user_id,
        endpoint="https://push.example/1",
        p256dh="key",
        auth="secret",
        device_label="Laptop",
    )
    service.subscribe(
        user_id=user_id,
        endpoint="https://push.example/2",
        p256dh="key",
        auth="secret",
        device_label="Phone",
    )
    assert service.deliver(user_id=user_id, event_type="book.available", payload={}) == 1
    remaining = service.list_subscriptions(user_id=user_id)
    assert [item.id for item in remaining] == [first.id]
    service.set_rule(user_id=user_id, event_type="book.available", enabled=False, filters={})
    assert service.deliver(user_id=user_id, event_type="book.available", payload={}) == 0


def test_push_subscription_endpoint_must_be_https_or_loopback(platform_db):
    db_path, user_id, _ = platform_db
    service = WebPushService(str(db_path), transport=_PushTransport([201]))
    with pytest.raises(ValueError):
        service.subscribe(
            user_id=user_id,
            endpoint="https:///missing-host",
            p256dh="key",
            auth="secret",
            device_label=None,
        )
    with pytest.raises(ValueError):
        service.subscribe(
            user_id=user_id,
            endpoint="http://push.example/subscription",
            p256dh="key",
            auth="secret",
            device_label=None,
        )
    created = service.subscribe(
        user_id=user_id,
        endpoint="http://127.0.0.1:8787/subscription",
        p256dh="key",
        auth="secret",
        device_label=None,
    )
    assert created.id > 0


def test_web_push_rule_filters_are_enforced(platform_db):
    db_path, user_id, _ = platform_db
    service = WebPushService(str(db_path), transport=_PushTransport([201]))
    service.subscribe(
        user_id=user_id,
        endpoint="https://push.example/filter",
        p256dh="key",
        auth="secret",
        device_label=None,
    )
    service.set_rule(
        user_id=user_id, event_type="book.available", enabled=True, filters={"book_id": 7}
    )
    assert (
        service.deliver(user_id=user_id, event_type="book.available", payload={"book_id": 8}) == 0
    )
    assert (
        service.deliver(user_id=user_id, event_type="book.available", payload={"book_id": 7}) == 1
    )
    assert service.delete_rule(user_id=user_id, event_type="book.available")
    assert next(
        rule
        for rule in service.list_rules(user_id=user_id)
        if rule["event_type"] == "book.available"
    ) == {"event_type": "book.available", "enabled": True, "filters": {}}


def test_web_push_retries_transient_delivery_and_validates_device_label(platform_db):
    db_path, user_id, _ = platform_db
    service = WebPushService(str(db_path), transport=_PushTransport([503]))
    subscription = service.subscribe(
        user_id=user_id,
        endpoint="https://push.example/retry",
        p256dh="key",
        auth="secret",
        device_label="Phone",
    )

    with pytest.raises(RuntimeError, match="HTTP 503"):
        service.deliver(user_id=user_id, event_type="book.available", payload={})

    assert [item.id for item in service.list_subscriptions(user_id=user_id)] == [subscription.id]
    with pytest.raises(ValueError, match="device_label"):
        service.subscribe(
            user_id=user_id,
            endpoint="https://push.example/invalid-label",
            p256dh="key",
            auth="secret",
            device_label={"not": "a string"},  # type: ignore[arg-type]
        )


def test_monitor_runtime_discovers_once_and_schedules_next_scan(platform_db, monkeypatch):
    db_path, user_id, _ = platform_db
    monitor = CatalogMonitorService(str(db_path)).create_monitor(
        user_id=user_id,
        payload={
            "type": "author",
            "provider": "openlibrary",
            "provider_id": "/authors/OL999A",
            "query": "New Writer",
            "action": "notify",
            "search_profile": {"language": "en", "limit": 17},
        },
        is_admin=False,
        library_capability="request-only",
    )
    notifications = []
    observed_options = []

    class Provider:
        def is_available(self):
            return True

        def search(self, options):
            observed_options.append(options)
            return [
                BookMetadata(
                    provider="openlibrary",
                    provider_id="OL-NEW",
                    title="New Book",
                    authors=["New Writer"],
                    publish_year=2026,
                )
            ]

    monkeypatch.setattr(
        "bookflow.core.monitor_runtime.get_provider", lambda *_args, **_kwargs: Provider()
    )
    runtime = MonitorRuntime(
        str(db_path),
        notify=lambda recipient, payload: notifications.append((recipient, payload)),
    )
    runtime.process({"monitor_id": monitor["id"]})
    runtime.process({"monitor_id": monitor["id"]})
    with sqlite3.connect(db_path) as conn:
        discoveries = conn.execute(
            "SELECT state FROM monitor_discoveries WHERE monitor_id = ?",
            (monitor["id"],),
        ).fetchall()
        next_scan = conn.execute(
            "SELECT next_scan_at FROM monitors WHERE id = ?", (monitor["id"],)
        ).fetchone()[0]
    assert discoveries == [("discovered",)]
    assert len(notifications) == 1
    assert next_scan
    assert observed_options[0].fields["author_key"] == "OL999A"
    assert observed_options[0].language == "en"
    assert observed_options[0].limit == 17


def test_metadata_review_collects_alternative_provider_observations(platform_db):
    db_path, _user_id, book_id = platform_db
    with sqlite3.connect(db_path) as conn:
        record_provider_observation(
            conn,
            book_id=book_id,
            source="openlibrary",
            source_identifier="OL1W",
            payload={"title": "Provider title", "authors": ["Provider Writer"]},
        )
        record_provider_observation(
            conn,
            book_id=book_id,
            source="hardcover",
            source_identifier="42",
            payload={"title": "Alternative title", "authors": ["Alternative Writer"]},
        )
    context = MetadataGovernanceService(str(db_path)).review_context(book_id=book_id)
    sources = {candidate["source"]: candidate["values"] for candidate in context["provider_values"]}
    assert sources["openlibrary"]["title"] == "Provider title"
    assert sources["hardcover"]["author"] == "Alternative Writer"


def test_backup_verify_stage_and_startup_restore(platform_db, tmp_path):
    db_path, user_id, _ = platform_db
    config_dir = tmp_path
    (config_dir / "settings.json").write_text('{"theme":"dark"}', encoding="utf-8")
    service = BackupService(
        database_path=db_path,
        config_dir=config_dir,
        backup_dir=config_dir / "backups",
    )
    backup = service.create(created_by=user_id)
    assert service.verify(backup.id)["valid"]
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE books SET title = 'Changed'")
        conn.commit()
    finally:
        conn.close()
    (config_dir / "settings.json").write_text('{"theme":"light"}', encoding="utf-8")
    assert service.stage_restore(backup.id)["restart_required"]
    assert apply_staged_restore(config_dir)
    conn = sqlite3.connect(db_path)
    try:
        assert conn.execute("SELECT title FROM books").fetchone()[0] == "Old title"
    finally:
        conn.close()
    assert (config_dir / "settings.json").read_text(encoding="utf-8") == '{"theme":"dark"}'
    safety_archives = list((config_dir / "backups").glob("restore-safety-*.zip"))
    assert len(safety_archives) == 1
    with zipfile.ZipFile(safety_archives[0]) as archive:
        assert {"database/users.db", "config/settings.json", "manifest.json"} <= set(
            archive.namelist()
        )
        assert archive.read("config/settings.json") == b'{"theme":"light"}'
        restored_safety_db = config_dir / "safety.db"
        restored_safety_db.write_bytes(archive.read("database/users.db"))
    with sqlite3.connect(restored_safety_db) as safety_conn:
        assert safety_conn.execute("SELECT title FROM books").fetchone()[0] == "Changed"


def test_startup_restore_rolls_back_db_and_config_and_keeps_retry_state(
    platform_db, tmp_path, monkeypatch
):
    db_path, user_id, _ = platform_db
    config_dir = tmp_path
    first_settings = config_dir / "a-first.json"
    first_settings.write_text('{"first":"dark"}', encoding="utf-8")
    settings = config_dir / "z-settings.json"
    settings.write_text('{"theme":"dark"}', encoding="utf-8")
    service = BackupService(
        database_path=db_path,
        config_dir=config_dir,
        backup_dir=config_dir / "backups",
    )
    backup = service.create(created_by=user_id)

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE books SET title = 'Changed'")
        conn.commit()
    first_settings.write_text('{"first":"light"}', encoding="utf-8")
    settings.write_text('{"theme":"light"}', encoding="utf-8")
    service.stage_restore(backup.id)

    from bookflow.core import backup_service as backup_module

    original_atomic_copy = backup_module._atomic_copy
    failed_once = False

    def fail_live_settings_copy(source: Path, destination: Path) -> None:
        nonlocal failed_once
        if destination == settings and not failed_once:
            failed_once = True
            raise OSError("simulated full volume")
        original_atomic_copy(source, destination)

    monkeypatch.setattr(backup_module, "_atomic_copy", fail_live_settings_copy)
    with pytest.raises(RuntimeError, match="rolled back"):
        apply_staged_restore(config_dir)

    assert failed_once
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT title FROM books").fetchone()[0] == "Changed"
    assert first_settings.read_text(encoding="utf-8") == '{"first":"light"}'
    assert settings.read_text(encoding="utf-8") == '{"theme":"light"}'
    assert (config_dir / ".restore-pending.json").is_file()
    assert (config_dir / ".restore-staging").is_dir()

    safety_archives = list((config_dir / "backups").glob("restore-safety-*.zip"))
    assert len(safety_archives) == 1
    with zipfile.ZipFile(safety_archives[0]) as archive:
        assert archive.read("config/a-first.json") == b'{"first":"light"}'
        assert archive.read("config/z-settings.json") == b'{"theme":"light"}'
        safety_db = config_dir / "failed-safety.db"
        safety_db.write_bytes(archive.read("database/users.db"))
    with sqlite3.connect(safety_db) as safety_conn:
        assert safety_conn.execute("SELECT title FROM books").fetchone()[0] == "Changed"


def test_daily_backup_due_uses_one_jittered_job_per_day(platform_db, tmp_path):
    db_path, _user_id, _book_id = platform_db
    service = BackupService(
        database_path=db_path, config_dir=tmp_path, backup_dir=tmp_path / "backups"
    )
    now = datetime(2026, 1, 1, 23, 0, tzinfo=UTC)
    assert service.daily_backup_due(now)
    service.create()
    assert not service.daily_backup_due(now)


def test_backup_retention_keeps_daily_points_then_weekly_representatives(platform_db, tmp_path):
    db_path, _user_id, _book_id = platform_db
    backup_dir = tmp_path / "backups"
    service = BackupService(database_path=db_path, config_dir=tmp_path, backup_dir=backup_dir)
    now = datetime.now(UTC).replace(hour=12, minute=0, second=0, microsecond=0)
    for day_offset in range(14):
        for copy in range(2):
            path = backup_dir / f"bookflow-{day_offset:02d}-{copy}.zip"
            path.write_bytes(b"backup")
            stamp = (now - timedelta(days=day_offset, minutes=copy)).timestamp()
            os.utime(path, (stamp, stamp))

    service.apply_retention()

    remaining = list(backup_dir.glob("bookflow-*.zip"))
    remaining_dates = {
        datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%d") for path in remaining
    }
    assert (
        len(
            remaining_dates
            & {(now - timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(7)}
        )
        == 7
    )
    assert len(remaining) <= 11
