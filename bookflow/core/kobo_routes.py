"""Unregistered Flask Blueprint factory for the isolated Kobo MVP API."""

from __future__ import annotations

import time
from copy import deepcopy
from ipaddress import ip_address
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from flask import Blueprint, Response, jsonify, request, send_file

from bookflow.core.kobo_services import (
    KoboAuthenticationError,
    KoboCursorError,
    KoboEntitlementError,
    KoboRateLimitError,
)
from bookflow.core.path_security import PathInput, PathSecurityError, resolve_library_file

if TYPE_CHECKING:
    from collections.abc import Callable

    from bookflow.core.kobo_services import KoboSyncService, TokenService

KOB0_CONTRACT_FIXTURES: dict[str, dict[str, Any]] = {
    "initialization": {
        "Version": "1.0",
        "Capabilities": {"sync": True, "metadata": True, "download": True, "delete": True},
    },
    "sync": {"Changes": [], "Cursor": None},
    "compatibility_empty": {},
}

type TLSGuard = Callable[[], bool]
type CoverFetcher = Callable[[str, str], tuple[bytes, str] | None]
type SyncAuditRecorder = Callable[..., None]
type KoboRouteFailure = tuple[Response, int]
type KoboAuthenticationResult = tuple[int, None] | tuple[None, KoboRouteFailure]


def default_external_tls_guard() -> bool:
    """Allow loopback development; require a secure transport for external peers."""
    remote = request.remote_addr or ""
    try:
        if ip_address(remote).is_loopback:
            return True
    except ValueError:
        return False
    return bool(request.is_secure)


def register_kobo_routes(
    app: Any,
    *,
    token_service: TokenService,
    sync_service: KoboSyncService,
    allowed_file_roots: tuple[PathInput, ...],
    tls_guard: TLSGuard = default_external_tls_guard,
    cover_fetcher: CoverFetcher | None = None,
    sync_audit_recorder: SyncAuditRecorder | None = None,
) -> Blueprint:
    """Create and register Kobo token routes without touching application bootstrap.

    Registration is explicit so callers can place it behind feature/config gates
    during the broader integration.  Tokens are intentionally never logged or
    returned in error messages.
    """
    blueprint = Blueprint("kobo_mvp", __name__, url_prefix="/api/kobo")

    def authenticate(token: str) -> KoboAuthenticationResult:
        if not tls_guard():
            return None, (jsonify({"code": "tls_required", "message": "TLS is required"}), 400)
        try:
            authenticated = token_service.authenticate(
                token=token,
                source_ip=request.remote_addr or "unknown",
            )
        except KoboRateLimitError:
            return None, (jsonify({"code": "rate_limited", "message": "Too many requests"}), 429)
        except KoboAuthenticationError:
            return None, (jsonify({"code": "unauthorized", "message": "Unauthorized"}), 401)
        request.environ["bookflow.kobo_token_id"] = authenticated.token_id
        return authenticated.user_id, None

    def record_sync_audit(
        *,
        user_id: int,
        status: str,
        started: float,
        changes_sent: int = 0,
        high_water_revision: int | None = None,
        has_more: bool = False,
        error_code: str | None = None,
    ) -> None:
        if sync_audit_recorder is None:
            return
        try:
            sync_audit_recorder(
                user_id=user_id,
                token_id=request.environ.get("bookflow.kobo_token_id"),
                source_ip=request.remote_addr or "unknown",
                user_agent=request.headers.get("User-Agent"),
                status=status,
                changes_sent=changes_sent,
                high_water_revision=high_water_revision,
                has_more=has_more,
                duration_ms=round((time.monotonic() - started) * 1000),
                error_code=error_code,
            )
        except OSError, RuntimeError, TypeError, ValueError:
            app.logger.exception("Unable to persist Kobo sync audit event")

    @blueprint.get("/<token>/v1/initialization")
    def initialization(token: str) -> tuple[Response, int] | Response:
        user_id, failure = authenticate(token)
        if failure is not None:
            return failure
        user_id = cast(int, user_id)
        payload = deepcopy(KOB0_CONTRACT_FIXTURES["initialization"])
        payload["UserId"] = user_id
        payload["SyncUrl"] = f"/api/kobo/{token}/v1/library/sync"
        return jsonify(payload)

    @blueprint.get("/<token>/v1/library/sync")
    def library_sync(token: str) -> tuple[Response, int] | Response:
        user_id, failure = authenticate(token)
        if failure is not None:
            return failure
        user_id = cast(int, user_id)
        started = time.monotonic()
        try:
            batch = sync_service.sync(user_id=user_id, cursor=request.args.get("cursor"))
        except KoboCursorError:
            record_sync_audit(
                user_id=user_id,
                status="failed",
                started=started,
                error_code="invalid_cursor",
            )
            return jsonify({"code": "invalid_cursor", "message": "Invalid sync cursor"}), 409
        except KoboEntitlementError:
            record_sync_audit(
                user_id=user_id,
                status="failed",
                started=started,
                error_code="forbidden",
            )
            return jsonify({"code": "forbidden", "message": "Kobo is unavailable"}), 403
        payload = deepcopy(KOB0_CONTRACT_FIXTURES["sync"])
        payload.update(
            {
                "Changes": batch.changes,
                "Cursor": batch.cursor,
                "HighWater": batch.high_water,
            }
        )
        response = jsonify(payload)
        if batch.has_more:
            response.headers["X-Kobo-Sync"] = "continue"
        record_sync_audit(
            user_id=user_id,
            status="completed",
            started=started,
            changes_sent=len(batch.changes),
            high_water_revision=batch.high_water,
            has_more=batch.has_more,
        )
        return response

    @blueprint.get("/<token>/v1/books/<int:book_id>")
    def book_metadata(token: str, book_id: int) -> tuple[Response, int] | Response:
        user_id, failure = authenticate(token)
        if failure is not None:
            return failure
        user_id = cast(int, user_id)
        try:
            book = sync_service.get_book_metadata(user_id=user_id, book_id=book_id)
        except KoboEntitlementError:
            return jsonify({"code": "not_found", "message": "Book not found"}), 404
        return jsonify(
            {
                "BookId": book["id"],
                "Title": book["title"],
                "Author": book["author"],
                "Language": book["language"],
                "PublicationYear": book["publish_year"],
                "File": {
                    "Id": book["file_id"],
                    "Format": book["file_format"],
                    "Size": book["size_bytes"],
                    "Checksum": book["sha256"],
                },
                "CoverUrl": f"/api/kobo/{token}/v1/books/{book_id}/cover",
            }
        )

    @blueprint.get("/<token>/v1/library/<int:book_id>/state")
    def reading_state(token: str, book_id: int) -> tuple[Response, int] | Response:
        user_id, failure = authenticate(token)
        if failure is not None:
            return failure
        try:
            state = sync_service.get_reading_state(user_id=cast(int, user_id), book_id=book_id)
        except KoboEntitlementError:
            return jsonify({"code": "not_found", "message": "Book not found"}), 404
        if state is None:
            return jsonify({"BookId": book_id, "Progress": 0, "Active": False, "Revision": 0})
        return jsonify(
            {
                "BookId": book_id,
                "Progress": state["progress"],
                "Active": bool(state["active"]),
                "Revision": state["revision"],
                "UpdatedAt": state["updated_at"],
            }
        )

    @blueprint.put("/<token>/v1/library/<int:book_id>/state")
    def put_reading_state(token: str, book_id: int) -> tuple[Response, int] | Response:
        user_id, failure = authenticate(token)
        if failure is not None:
            return failure
        payload = request.get_json(silent=True)
        raw_progress = (
            payload.get("Progress", payload.get("progress")) if isinstance(payload, dict) else None
        )
        if isinstance(raw_progress, bool) or not isinstance(raw_progress, (int, float)):
            return jsonify(
                {"code": "invalid_progress", "message": "Progress must be a number"}
            ), 400
        try:
            # A device must never be able to lower progress by supplying an
            # undocumented Reset flag.  Resetting is an explicit BookFlow
            # action (the authenticated web API), keeping device sync monotone.
            state = sync_service.set_reading_state(
                user_id=cast(int, user_id), book_id=book_id, progress=float(raw_progress)
            )
        except KoboEntitlementError:
            return jsonify({"code": "not_found", "message": "Book not found"}), 404
        except ValueError as exc:
            return jsonify({"code": "invalid_progress", "message": str(exc)}), 409
        return jsonify(
            {
                "BookId": book_id,
                "Progress": state["progress"],
                "Active": bool(state["active"]),
                "Revision": state["revision"],
                "UpdatedAt": state["updated_at"],
            }
        )

    @blueprint.get("/<token>/v1/files/<int:file_id>/download")
    def file_download(token: str, file_id: int) -> tuple[Response, int] | Response:
        user_id, failure = authenticate(token)
        if failure is not None:
            return failure
        user_id = cast(int, user_id)
        try:
            file_row = sync_service.get_entitled_file(user_id=user_id, file_id=file_id)
            path = resolve_library_file(file_row["storage_path"], allowed_roots=allowed_file_roots)
        except KoboEntitlementError:
            return jsonify({"code": "not_found", "message": "File not found"}), 404
        except PathSecurityError:
            return jsonify({"code": "file_unavailable", "message": "File is unavailable"}), 404
        return send_file(path, as_attachment=True, download_name=Path(path).name)

    @blueprint.get("/<token>/v1/books/<int:book_id>/cover")
    def book_cover(token: str, book_id: int) -> tuple[Response, int] | Response:
        user_id, failure = authenticate(token)
        if failure is not None:
            return failure
        user_id = cast(int, user_id)
        try:
            book = sync_service.get_book_metadata(user_id=user_id, book_id=book_id)
        except KoboEntitlementError:
            return jsonify({"code": "not_found", "message": "Cover not found"}), 404
        cover_url = book.get("cover_url")
        if not isinstance(cover_url, str) or not cover_url.strip():
            return jsonify({"code": "not_found", "message": "Cover not found"}), 404
        if cover_fetcher is None:
            return jsonify({"CoverUrl": cover_url})
        cover = cover_fetcher(f"kobo-book-{book_id}", cover_url)
        if cover is None:
            return jsonify({"code": "not_found", "message": "Cover not found"}), 404
        image_bytes, content_type = cover
        response = app.response_class(image_bytes, content_type=content_type)
        response.headers["Cache-Control"] = "private, max-age=86400"
        return response

    @blueprint.delete("/<token>/v1/books/<int:book_id>")
    def delete_book(token: str, book_id: int) -> tuple[Response, int] | Response:
        user_id, failure = authenticate(token)
        if failure is not None:
            return failure
        user_id = cast(int, user_id)
        try:
            revision = sync_service.delete_book(user_id=user_id, book_id=book_id)
        except KoboEntitlementError:
            return jsonify({"code": "not_found", "message": "Book not found"}), 404
        return jsonify({"revision": revision})

    @blueprint.get("/<token>/v1/<compatibility_route>")
    def empty_compatibility(
        token: str, compatibility_route: str
    ) -> tuple[Response, int] | Response:
        if compatibility_route not in {"analytics", "recommendations", "store"}:
            return jsonify({"code": "not_found", "message": "Not found"}), 404
        _user_id, failure = authenticate(token)
        if failure is not None:
            return failure
        return jsonify(deepcopy(KOB0_CONTRACT_FIXTURES["compatibility_empty"]))

    app.register_blueprint(blueprint)
    return blueprint
