"""Authenticated API route for in-app GitHub problem reports."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlparse

from flask import Blueprint, Response, jsonify, request

from bookflow.core.github_issue_service import (
    GitHubIssueService,
    ImageValidationError,
    IssueReportingError,
    build_issue_body,
    normalize_image,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)
ROUTE = "/api/v1/issue-reports"
MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 10_000
MAX_REQUEST_BYTES = 6 * 1024 * 1024


class ActorLike(Protocol):
    @property
    def user_id(self) -> int: ...


def register_github_issue_routes(
    app: Any,
    *,
    database_path: str,
    resolve_actor: Callable[[], ActorLike | None],
    service: GitHubIssueService,
    build_version: str,
    release_version: str,
) -> None:
    blueprint = Blueprint("github_issue_reports_v1", __name__, url_prefix=ROUTE)

    def failure(code: str, message: str, status: int) -> tuple[Response, int]:
        return jsonify({"error": {"code": code, "message": message}}), status

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(database_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    @blueprint.post("")
    def submit() -> tuple[Response, int] | Response:
        actor = resolve_actor()
        if actor is None:
            return failure("unauthorized", "Authentication required", 401)
        if request.content_length is not None and request.content_length > MAX_REQUEST_BYTES:
            return failure("image_too_large", "Afbeelding is groter dan 5 MiB", 413)

        idempotency_key = (request.headers.get("Idempotency-Key") or "").strip()
        if not idempotency_key or len(idempotency_key) > 128:
            return failure(
                "invalid_idempotency_key", "Een geldige Idempotency-Key is verplicht", 400
            )
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        page_url = (request.form.get("page_url") or "").strip()
        ui_language = (request.form.get("ui_language") or "").strip()[:20]
        if not title or len(title) > MAX_TITLE_LENGTH:
            return failure("invalid_title", "Onderwerp is verplicht en maximaal 200 tekens", 400)
        if not description or len(description) > MAX_DESCRIPTION_LENGTH:
            return failure(
                "invalid_description",
                "Omschrijving is verplicht en maximaal 10.000 tekens",
                400,
            )
        parsed_url = urlparse(page_url)
        if (
            len(page_url) > 2048
            or parsed_url.scheme not in {"http", "https"}
            or not parsed_url.netloc
        ):
            return failure("invalid_page_url", "Voer een geldige http(s)-URL in", 400)

        image = None
        image_hash = ""
        upload = request.files.get("image")
        if upload is not None and upload.filename:
            raw_image = upload.read(MAX_DESCRIPTION_LENGTH * 1024)
            try:
                image = normalize_image(raw_image)
            except ImageValidationError as exc:
                return failure(
                    "image_too_large" if exc.too_large else "invalid_image",
                    str(exc),
                    413 if exc.too_large else 400,
                )
            if upload.mimetype.lower() != image.source_media_type:
                return failure(
                    "invalid_image",
                    "Het opgegeven afbeeldingstype komt niet overeen met de bestandsinhoud",
                    400,
                )
            image_hash = hashlib.sha256(image.content).hexdigest()

        request_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "title": title,
                    "description": description,
                    "page_url": page_url,
                    "ui_language": ui_language,
                    "image_hash": image_hash,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        with connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            replay = conn.execute(
                """
                SELECT request_hash, response_status, response_json
                FROM api_idempotency_keys
                WHERE actor_user_id = ? AND method = 'POST'
                  AND route = ? AND idempotency_key = ?
                """,
                (actor.user_id, ROUTE, idempotency_key),
            ).fetchone()
            if replay is not None:
                if replay["request_hash"] != request_fingerprint:
                    return failure(
                        "idempotency_conflict",
                        "Deze verzendsleutel is al voor een andere melding gebruikt",
                        409,
                    )
                if int(replay["response_status"]) == 102:
                    return failure(
                        "submission_in_progress",
                        "Deze probleemmelding wordt al verwerkt",
                        409,
                    )
                return jsonify(json.loads(str(replay["response_json"]))), int(
                    replay["response_status"]
                )
            recent_count = conn.execute(
                """
                SELECT COUNT(*) FROM api_idempotency_keys
                WHERE actor_user_id = ? AND method = 'POST' AND route = ?
                  AND created_at >= datetime('now', '-15 minutes')
                """,
                (actor.user_id, ROUTE),
            ).fetchone()[0]
            if int(recent_count) >= 5:
                return failure(
                    "issue_report_rate_limited",
                    "Je kunt maximaal vijf problemen per vijftien minuten indienen",
                    429,
                )
            conn.execute(
                """
                INSERT INTO api_idempotency_keys (
                    actor_user_id, method, route, idempotency_key, request_hash,
                    response_status, response_json
                ) VALUES (?, 'POST', ?, ?, ?, 102, '{"status":"processing"}')
                """,
                (actor.user_id, ROUTE, idempotency_key, request_fingerprint),
            )

        with connect() as conn:
            user = conn.execute(
                "SELECT username FROM users WHERE id = ?", (actor.user_id,)
            ).fetchone()
        username = str(user["username"]) if user is not None else f"user-{actor.user_id}"
        body = build_issue_body(
            description=description,
            page_url=page_url,
            username=username,
            build_version=build_version,
            release_version=release_version,
            submitted_at=datetime.now(UTC).isoformat(),
            user_agent=request.headers.get("User-Agent", ""),
            ui_language=ui_language or "onbekend",
        )
        try:
            issue = service.create_issue(title=title, body=body)
        except IssueReportingError as exc:
            logger.warning("GitHub issue creation failed: code=%s", exc.code)
            with connect() as conn:
                conn.execute(
                    """
                    DELETE FROM api_idempotency_keys
                    WHERE actor_user_id = ? AND method = 'POST' AND route = ?
                      AND idempotency_key = ? AND response_status = 102
                    """,
                    (actor.user_id, ROUTE, idempotency_key),
                )
            return failure(exc.code, str(exc), exc.status_code)

        response_body: dict[str, Any] = {
            "issue_number": issue.number,
            "attachment_status": "none",
        }
        if image is not None:
            try:
                service.attach_image(issue=issue, image=image)
                response_body["attachment_status"] = "attached"
            except IssueReportingError as exc:
                logger.warning(
                    "GitHub issue attachment failed after issue creation: issue=%s code=%s",
                    issue.number,
                    exc.code,
                )
                response_body["attachment_status"] = "failed"
                response_body["warning"] = "De bijlage kon niet worden toegevoegd"

        with connect() as conn:
            conn.execute(
                """
                UPDATE api_idempotency_keys
                SET response_status = 201, response_json = ?
                WHERE actor_user_id = ? AND method = 'POST' AND route = ?
                  AND idempotency_key = ? AND request_hash = ?
                """,
                (
                    json.dumps(response_body, sort_keys=True),
                    actor.user_id,
                    ROUTE,
                    idempotency_key,
                    request_fingerprint,
                ),
            )
        return jsonify(response_body), 201

    app.register_blueprint(blueprint)
