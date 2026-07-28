"""User correction reports and administrator metadata revision API."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from flask import Blueprint, Response, jsonify, request

if TYPE_CHECKING:
    from collections.abc import Callable

    from bookflow.core.metadata_governance import MetadataGovernanceService


class ActorLike(Protocol):
    @property
    def user_id(self) -> int: ...

    @property
    def is_admin(self) -> bool: ...


def register_metadata_routes(
    app: Any,
    *,
    resolve_actor: Callable[[], ActorLike | None],
    service: MetadataGovernanceService,
) -> None:
    blueprint = Blueprint("metadata_governance_v1", __name__, url_prefix="/api/v1")

    def actor(*, admin: bool = False) -> tuple[ActorLike | None, tuple[Response, int] | None]:
        current = resolve_actor()
        if current is None:
            return None, (jsonify({"error": {"code": "unauthorized"}}), 401)
        if admin and not current.is_admin:
            return None, (jsonify({"error": {"code": "forbidden"}}), 403)
        return current, None

    @blueprint.post("/catalog/books/<int:book_id>/metadata-reports")
    def create_report(book_id: int) -> tuple[Response, int] | Response:
        current, failure = actor()
        if failure:
            return failure
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("fields"), list):
            return jsonify({"error": {"code": "invalid_request"}}), 400
        try:
            result = service.report(
                user_id=current.user_id,  # type: ignore[union-attr]
                book_id=book_id,
                fields=[str(field) for field in payload["fields"]],
                explanation=str(payload.get("explanation", "")),
            )
        except ValueError as exc:
            return jsonify({"error": {"code": "invalid_report", "message": str(exc)}}), 400
        except LookupError:
            return jsonify({"error": {"code": "book_not_found"}}), 404
        return jsonify(result), 201

    @blueprint.get("/metadata-reports")
    def own_reports() -> tuple[Response, int] | Response:
        current, failure = actor()
        if failure:
            return failure
        status = request.args.get("status", "open")
        items = service.reports(
            status=status,
            user_id=current.user_id,  # type: ignore[union-attr]
        )
        return jsonify(
            {
                "items": items,
                "total": len(items),
            }
        )

    @blueprint.get("/admin/metadata-reports")
    def reports() -> tuple[Response, int] | Response:
        _, failure = actor(admin=True)
        if failure:
            return failure
        items = service.reports(status=request.args.get("status", "open"))
        return jsonify({"items": items, "total": len(items)})

    @blueprint.post("/admin/books/<int:book_id>/metadata/preview")
    def preview(book_id: int) -> tuple[Response, int] | Response:
        _, failure = actor(admin=True)
        if failure:
            return failure
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("changes"), dict):
            return jsonify({"error": {"code": "invalid_request"}}), 400
        try:
            return jsonify(service.preview(book_id=book_id, changes=payload["changes"]))
        except ValueError as exc:
            return jsonify({"error": {"code": "invalid_changes", "message": str(exc)}}), 400
        except LookupError:
            return jsonify({"error": {"code": "book_not_found"}}), 404

    @blueprint.post("/admin/metadata-reports/<int:report_id>/reject")
    def reject_report(report_id: int) -> tuple[Response, int] | Response:
        current, failure = actor(admin=True)
        if failure:
            return failure
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(
                service.reject_report(
                    actor_user_id=current.user_id,  # type: ignore[union-attr]
                    report_id=report_id,
                    note=str(payload.get("note", "")),
                )
            )
        except ValueError as exc:
            return jsonify({"error": {"code": "invalid_review", "message": str(exc)}}), 400
        except LookupError:
            return jsonify({"error": {"code": "report_not_found"}}), 404

    @blueprint.post("/admin/books/<int:book_id>/metadata/apply")
    def apply(book_id: int) -> tuple[Response, int] | Response:
        current, failure = actor(admin=True)
        if failure:
            return failure
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("changes"), dict):
            return jsonify({"error": {"code": "invalid_request"}}), 400
        try:
            return jsonify(
                service.apply(
                    actor_user_id=current.user_id,  # type: ignore[union-attr]
                    book_id=book_id,
                    changes=payload["changes"],
                    reason=str(payload.get("reason", "")),
                    source=str(payload.get("source", "admin")),
                    report_id=payload.get("report_id"),
                )
            )
        except ValueError as exc:
            return jsonify({"error": {"code": "invalid_changes", "message": str(exc)}}), 400
        except LookupError:
            return jsonify({"error": {"code": "book_not_found"}}), 404

    @blueprint.get("/admin/books/<int:book_id>/metadata/history")
    def history(book_id: int) -> tuple[Response, int] | Response:
        _, failure = actor(admin=True)
        if failure:
            return failure
        return jsonify({"items": service.history(book_id=book_id)})

    @blueprint.post("/admin/books/<int:book_id>/metadata/revert/<int:revision_id>")
    def revert(book_id: int, revision_id: int) -> tuple[Response, int] | Response:
        current, failure = actor(admin=True)
        if failure:
            return failure
        payload = request.get_json(silent=True) or {}
        try:
            return jsonify(
                service.revert(
                    actor_user_id=current.user_id,  # type: ignore[union-attr]
                    book_id=book_id,
                    revision_id=revision_id,
                    reason=str(payload.get("reason", f"Reverted revision {revision_id}")),
                )
            )
        except LookupError:
            return jsonify({"error": {"code": "revision_not_found"}}), 404

    app.register_blueprint(blueprint)
