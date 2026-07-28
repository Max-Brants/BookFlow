"""Route-contract tests for in-app GitHub issue reports."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import pytest
from flask import Flask
from PIL import Image

from bookflow.core.github_issue_routes import ROUTE, register_github_issue_routes
from bookflow.core.github_issue_service import (
    CreatedIssue,
    IssueReportingError,
    NormalizedImage,
)
from bookflow.core.user_db import UserDB
from bookflow.core.v1_api import V1Actor


def _png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (3, 2), color="blue").save(output, format="PNG")
    return output.getvalue()


@dataclass
class _FakeIssueService:
    issue_number: int = 123
    fail_attachment: bool = False
    create_calls: list[tuple[str, str]] | None = None
    attachment_calls: list[tuple[CreatedIssue, NormalizedImage]] | None = None

    def __post_init__(self) -> None:
        self.create_calls = []
        self.attachment_calls = []

    def create_issue(self, *, title: str, body: str) -> CreatedIssue:
        assert self.create_calls is not None
        self.create_calls.append((title, body))
        return CreatedIssue(self.issue_number, body)

    def attach_image(self, *, issue: CreatedIssue, image: NormalizedImage) -> str:
        assert self.attachment_calls is not None
        self.attachment_calls.append((issue, image))
        if self.fail_attachment:
            raise IssueReportingError("github_request_failed", "failed", 502)
        return "https://github.test/attachment"


@pytest.fixture
def configured(tmp_path: Path):
    db_path = tmp_path / "users.db"
    db = UserDB(str(db_path))
    db.initialize()
    user = db.create_user(username="reader")
    actor = V1Actor(int(user["id"]))
    service = _FakeIssueService()
    app = Flask(__name__)
    app.config["TESTING"] = True
    register_github_issue_routes(
        app,
        database_path=str(db_path),
        resolve_actor=lambda: actor,
        service=service,  # type: ignore[arg-type]
        build_version="build-test",
        release_version="release-test",
    )
    return app.test_client(), service, db_path, actor


def _form(*, title: str = "Broken search", description: str = "Search stays blank") -> dict[str, object]:
    return {
        "title": title,
        "description": description,
        "page_url": "https://bookflow.test/search?q=one",
        "ui_language": "nl",
    }


def _post(client, *, key: str = "request-1", data: dict[str, object] | None = None):
    return client.post(ROUTE, data=data or _form(), headers={"Idempotency-Key": key})


def test_route_requires_an_authenticated_actor(tmp_path: Path) -> None:
    path = tmp_path / "users.db"
    db = UserDB(str(path))
    db.initialize()
    app = Flask(__name__)
    register_github_issue_routes(
        app,
        database_path=str(path),
        resolve_actor=lambda: None,
        service=_FakeIssueService(),  # type: ignore[arg-type]
        build_version="build",
        release_version="release",
    )

    response = _post(app.test_client())

    assert response.status_code == 401
    assert response.json["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        ({"description": "x", "page_url": "https://bookflow.test"}, "invalid_title"),
        ({"title": "x", "page_url": "https://bookflow.test"}, "invalid_description"),
        ({"title": "x", "description": "x", "page_url": "javascript:alert(1)"}, "invalid_page_url"),
    ],
)
def test_route_validates_required_fields_and_page_url(configured, data: dict[str, object], code: str) -> None:
    client, service, _path, _actor = configured

    response = _post(client, data=data)

    assert response.status_code == 400
    assert response.json["error"]["code"] == code
    assert service.create_calls == []


def test_route_creates_issue_from_multipart_and_passes_image(configured) -> None:
    client, service, _path, _actor = configured
    data = _form()
    data["image"] = (io.BytesIO(_png_bytes()), "screenshot.png", "image/png")

    response = _post(client, data=data)

    assert response.status_code == 201
    assert response.json == {"issue_number": 123, "attachment_status": "attached"}
    assert service.create_calls is not None and service.create_calls[0][0] == "Broken search"
    assert "BookFlow-gebruiker: `reader`" in service.create_calls[0][1]
    assert service.attachment_calls is not None and len(service.attachment_calls) == 1


def test_route_rejects_mime_type_that_does_not_match_image_content(configured) -> None:
    client, service, _path, _actor = configured
    data = _form()
    data["image"] = (io.BytesIO(_png_bytes()), "screenshot.jpg", "image/jpeg")

    response = _post(client, data=data)

    assert response.status_code == 400
    assert response.json["error"]["code"] == "invalid_image"
    assert service.create_calls == []


def test_route_replays_same_idempotency_key_without_creating_duplicate_issue(configured) -> None:
    client, service, _path, _actor = configured

    first = _post(client, key="same-key")
    replay = _post(client, key="same-key")

    assert first.status_code == replay.status_code == 201
    assert replay.json == first.json
    assert service.create_calls is not None and len(service.create_calls) == 1


def test_route_rejects_idempotency_key_reused_for_other_payload(configured) -> None:
    client, service, _path, _actor = configured
    _post(client, key="same-key")

    conflict = _post(client, key="same-key", data=_form(title="Different"))

    assert conflict.status_code == 409
    assert conflict.json["error"]["code"] == "idempotency_conflict"
    assert service.create_calls is not None and len(service.create_calls) == 1


def test_route_limits_user_to_five_new_reports_per_fifteen_minutes(configured) -> None:
    client, service, _path, _actor = configured
    for number in range(5):
        response = _post(client, key=f"key-{number}", data=_form(title=f"Broken {number}"))
        assert response.status_code == 201

    limited = _post(client, key="key-six", data=_form(title="Broken six"))

    assert limited.status_code == 429
    assert limited.json["error"]["code"] == "issue_report_rate_limited"
    assert service.create_calls is not None and len(service.create_calls) == 5


def test_route_returns_success_with_warning_when_attachment_fails(configured) -> None:
    client, service, _path, _actor = configured
    service.fail_attachment = True
    data = _form()
    data["image"] = (io.BytesIO(_png_bytes()), "screenshot.png")

    response = _post(client, data=data)

    assert response.status_code == 201
    assert response.json == {
        "issue_number": 123,
        "attachment_status": "failed",
        "warning": "De bijlage kon niet worden toegevoegd",
    }
    assert service.create_calls is not None and len(service.create_calls) == 1


def test_route_rejects_image_larger_than_five_mib(configured) -> None:
    client, service, _path, _actor = configured
    data = _form()
    data["image"] = (io.BytesIO(b"x" * (5 * 1024 * 1024 + 1)), "too-large.png")

    response = _post(client, data=data)

    assert response.status_code == 413
    assert response.json["error"]["code"] == "image_too_large"
    assert service.create_calls == []


def test_route_rate_limit_uses_persisted_idempotency_records(configured) -> None:
    client, service, path, actor = configured
    with sqlite3.connect(path) as conn:
        for number in range(5):
            conn.execute(
                """
                INSERT INTO api_idempotency_keys
                    (actor_user_id, method, route, idempotency_key, request_hash, response_status, response_json)
                VALUES (?, 'POST', ?, ?, ?, 201, '{}')
                """,
                (actor.user_id, ROUTE, f"old-{number}", "a" * 64),
            )

    response = _post(client, key="new-key")

    assert response.status_code == 429
    assert service.create_calls == []


def test_route_rejects_duplicate_while_submission_is_reserved(configured) -> None:
    client, service, path, actor = configured
    payload = _form()

    request_hash = hashlib.sha256(
        json.dumps(
            {
                "title": payload["title"],
                "description": payload["description"],
                "page_url": payload["page_url"],
                "ui_language": payload["ui_language"],
                "image_hash": "",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            INSERT INTO api_idempotency_keys
                (actor_user_id, method, route, idempotency_key, request_hash,
                 response_status, response_json)
            VALUES (?, 'POST', ?, 'busy-key', ?, 102, '{"status":"processing"}')
            """,
            (actor.user_id, ROUTE, request_hash),
        )

    response = _post(client, key="busy-key", data=payload)

    assert response.status_code == 409
    assert response.json["error"]["code"] == "submission_in_progress"
    assert service.create_calls == []
