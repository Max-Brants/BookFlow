"""Authenticated normal-API routes for personal Kobo settings and shelf intent."""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING, Any, Protocol, cast

from flask import Blueprint, Response, jsonify, request

from bookflow.core.kobo_services import KoboEntitlementError, KoboError

if TYPE_CHECKING:
    from collections.abc import Callable

    from bookflow.core.kobo_services import KoboSyncService, TokenService


class ActorLike(Protocol):
    @property
    def user_id(self) -> int: ...


class KepubConversionCallback(Protocol):
    """Optional on-demand KEPUB integration owned by the application runtime."""

    def __call__(self, *, user_id: int, book_id: int, source_file_id: int) -> int: ...


def register_kobo_settings_routes(
    app: Any,
    *,
    db_path: str,
    resolve_actor: Callable[[], ActorLike | None],
    token_service: TokenService,
    sync_service: KoboSyncService,
    kepub_converter: KepubConversionCallback | None = None,
) -> None:
    """Register user-owned Kobo settings, token, and shelf mutations."""
    blueprint = Blueprint("kobo_settings_v1", __name__, url_prefix="/api/v1/users/me")

    def actor_or_error() -> tuple[ActorLike | None, tuple[Response, int] | None]:
        actor = resolve_actor()
        if actor is None:
            return None, (jsonify({"error": {"code": "unauthorized"}}), 401)
        return actor, None

    @blueprint.get("/kobo-settings")
    def get_settings() -> tuple[Response, int] | Response:
        actor, failure = actor_or_error()
        if failure is not None:
            return failure
        actor = cast("ActorLike", actor)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            settings = conn.execute(
                "SELECT * FROM user_kobo_settings WHERE user_id = ?",
                (actor.user_id,),
            ).fetchone()
            tokens = conn.execute(
                """
                SELECT id, token_prefix, device_label, created_at, last_used_at
                FROM kobo_tokens
                WHERE user_id = ? AND revoked_at IS NULL
                ORDER BY created_at DESC
                """,
                (actor.user_id,),
            ).fetchall()
        finally:
            conn.close()
        return jsonify(
            {
                "enabled": bool(settings["enabled"]) if settings else False,
                "current_revision": int(settings["current_revision"]) if settings else 0,
                "tokens": [dict(token) for token in tokens],
            }
        )

    @blueprint.put("/kobo-settings")
    def put_settings() -> tuple[Response, int] | Response:
        actor, failure = actor_or_error()
        if failure is not None:
            return failure
        actor = cast("ActorLike", actor)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
            return jsonify({"error": {"code": "invalid_request"}}), 400
        sync_service.enable_user(user_id=actor.user_id, enabled=payload["enabled"])
        return jsonify({"enabled": payload["enabled"]})

    @blueprint.post("/kobo-token")
    def issue_token() -> tuple[Response, int] | Response:
        actor, failure = actor_or_error()
        if failure is not None:
            return failure
        actor = cast("ActorLike", actor)
        payload = request.get_json(silent=True)
        label = payload.get("device_label") if isinstance(payload, dict) else None
        if label is not None and not isinstance(label, str):
            return jsonify({"error": {"code": "invalid_request"}}), 400
        sync_service.enable_user(user_id=actor.user_id)
        issued = token_service.issue_token(user_id=actor.user_id, device_label=label)
        return (
            jsonify(
                {
                    "token_id": issued.token_id,
                    "token": issued.token,
                    "prefix": issued.prefix,
                    "api_endpoint": f"/api/kobo/{issued.token}",
                    "sync_url": f"/api/kobo/{issued.token}/v1/library/sync",
                    "sync_url_deprecated": True,
                    "shown_once": True,
                }
            ),
            201,
        )

    @blueprint.post("/kobo-token/<int:token_id>/rotate")
    def rotate_token(token_id: int) -> tuple[Response, int] | Response:
        actor, failure = actor_or_error()
        if failure is not None:
            return failure
        actor = cast("ActorLike", actor)
        try:
            issued = token_service.rotate_token(user_id=actor.user_id, token_id=token_id)
        except KoboError:
            return jsonify({"error": {"code": "token_not_found"}}), 404
        return jsonify(
            {
                "token_id": issued.token_id,
                "token": issued.token,
                "prefix": issued.prefix,
                "api_endpoint": f"/api/kobo/{issued.token}",
                "sync_url": f"/api/kobo/{issued.token}/v1/library/sync",
                "sync_url_deprecated": True,
                "shown_once": True,
            }
        )

    @blueprint.delete("/kobo-token/<int:token_id>")
    def revoke_token(token_id: int) -> tuple[Response, int] | Response:
        actor, failure = actor_or_error()
        if failure is not None:
            return failure
        actor = cast("ActorLike", actor)
        if not token_service.revoke_token(user_id=actor.user_id, token_id=token_id):
            return jsonify({"error": {"code": "token_not_found"}}), 404
        return jsonify({"token_id": token_id, "revoked": True})

    @blueprint.put("/kobo-books/<int:book_id>")
    def add_book(book_id: int) -> tuple[Response, int] | Response:
        actor, failure = actor_or_error()
        if failure is not None:
            return failure
        actor = cast("ActorLike", actor)
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("file_id"), int):
            return jsonify({"error": {"code": "invalid_request"}}), 400
        file_id = payload["file_id"]
        if payload.get("preferred_format") == "kepub":
            if kepub_converter is None:
                return jsonify({"error": {"code": "kepub_unavailable"}}), 503
            try:
                file_id = kepub_converter(
                    user_id=actor.user_id,
                    book_id=book_id,
                    source_file_id=file_id,
                )
            except OSError, RuntimeError, ValueError:
                return jsonify({"error": {"code": "kepub_conversion_failed"}}), 503
            if not isinstance(file_id, int) or file_id <= 0:
                return jsonify({"error": {"code": "kepub_conversion_failed"}}), 503
        try:
            # An explicit add-to-Kobo action is also explicit opt-in for sync.
            sync_service.enable_user(user_id=actor.user_id)
            revision = sync_service.set_book(
                user_id=actor.user_id,
                book_id=book_id,
                file_id=file_id,
                preferred_format=payload.get("preferred_format"),
            )
        except KoboEntitlementError:
            return jsonify({"error": {"code": "book_or_file_not_found"}}), 404
        return jsonify({"book_id": book_id, "revision": revision}), 202

    @blueprint.delete("/kobo-books/<int:book_id>")
    def remove_book(book_id: int) -> tuple[Response, int] | Response:
        actor, failure = actor_or_error()
        if failure is not None:
            return failure
        actor = cast("ActorLike", actor)
        try:
            revision = sync_service.delete_book(user_id=actor.user_id, book_id=book_id)
        except KoboEntitlementError:
            return jsonify({"error": {"code": "book_not_found"}}), 404
        return jsonify({"book_id": book_id, "revision": revision}), 202

    app.register_blueprint(blueprint)
