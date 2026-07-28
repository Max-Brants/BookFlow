"""Administrator backup and staged-restore centre API."""

from __future__ import annotations

import sqlite3
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Protocol

from flask import Blueprint, Response, jsonify, send_file

from bookflow.core.web_push_events import enqueue_admin_web_push

if TYPE_CHECKING:
    from collections.abc import Callable

    from bookflow.core.backup_service import BackupService


class ActorLike(Protocol):
    @property
    def user_id(self) -> int: ...

    @property
    def is_admin(self) -> bool: ...


def register_backup_routes(
    app: Any,
    *,
    resolve_actor: Callable[[], ActorLike | None],
    service: BackupService,
) -> None:
    blueprint = Blueprint("backups_v1", __name__, url_prefix="/api/v1/admin/backups")

    def admin() -> tuple[ActorLike | None, tuple[Response, int] | None]:
        current = resolve_actor()
        if current is None:
            return None, (jsonify({"error": {"code": "unauthorized"}}), 401)
        if not current.is_admin:
            return None, (jsonify({"error": {"code": "forbidden"}}), 403)
        return current, None

    @blueprint.get("")
    def list_backups() -> tuple[Response, int] | Response:
        _, failure = admin()
        if failure:
            return failure
        items = service.list()
        return jsonify({"items": items, "total": len(items)})

    @blueprint.post("")
    def create_backup() -> tuple[Response, int] | Response:
        current, failure = admin()
        if failure:
            return failure
        try:
            return jsonify(asdict(service.create(created_by=current.user_id))), 201  # type: ignore[union-attr]
        except (OSError, sqlite3.Error, RuntimeError) as exc:
            enqueue_admin_web_push(
                str(service.database_path),
                event_type="backup.error",
                payload={
                    "title": "Backup failed",
                    "body": "BookFlow could not create a backup.",
                    "url": "/admin/operations",
                },
                event_key=f"create:{type(exc).__name__}",
            )
            return jsonify({"error": {"code": "backup_failed", "message": str(exc)}}), 500

    @blueprint.post("/<backup_id>/verify")
    def verify(backup_id: str) -> tuple[Response, int] | Response:
        _, failure = admin()
        if failure:
            return failure
        try:
            return jsonify(service.verify(backup_id))
        except LookupError:
            return jsonify({"error": {"code": "backup_not_found"}}), 404
        except (OSError, ValueError, RuntimeError) as exc:
            enqueue_admin_web_push(
                str(service.database_path),
                event_type="backup.error",
                payload={
                    "title": "Backup verification failed",
                    "body": "A backup could not be verified.",
                    "url": "/admin/operations",
                },
                event_key=f"verify:{backup_id}:{type(exc).__name__}",
            )
            return jsonify({"error": {"code": "backup_invalid", "message": str(exc)}}), 422

    @blueprint.post("/<backup_id>/stage-restore")
    def stage_restore(backup_id: str) -> tuple[Response, int] | Response:
        _, failure = admin()
        if failure:
            return failure
        try:
            return jsonify(service.stage_restore(backup_id)), 202
        except LookupError:
            return jsonify({"error": {"code": "backup_not_found"}}), 404
        except (OSError, ValueError, RuntimeError) as exc:
            enqueue_admin_web_push(
                str(service.database_path),
                event_type="backup.error",
                payload={
                    "title": "Restore staging failed",
                    "body": "A backup could not be prepared for restore.",
                    "url": "/admin/operations",
                },
                event_key=f"restore:{backup_id}:{type(exc).__name__}",
            )
            return jsonify({"error": {"code": "restore_stage_failed", "message": str(exc)}}), 422

    @blueprint.get("/<backup_id>/download")
    def download(backup_id: str) -> tuple[Response, int] | Response:
        _, failure = admin()
        if failure:
            return failure
        try:
            path = service.download_path(backup_id)
        except LookupError:
            return jsonify({"error": {"code": "backup_not_found"}}), 404
        return send_file(path, as_attachment=True, download_name=path.name, conditional=True)

    @blueprint.delete("/<backup_id>")
    def delete(backup_id: str) -> tuple[Response, int] | Response:
        _, failure = admin()
        if failure:
            return failure
        try:
            return jsonify({"deleted": service.delete(backup_id)})
        except LookupError:
            return jsonify({"error": {"code": "backup_not_found"}}), 404

    app.register_blueprint(blueprint)
