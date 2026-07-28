"""Authenticated web-push device and notification-rule API."""

from __future__ import annotations

from dataclasses import asdict
from ipaddress import ip_address
from typing import TYPE_CHECKING, Any, Protocol

from flask import Blueprint, Response, jsonify, request

if TYPE_CHECKING:
    from collections.abc import Callable

    from bookflow.core.web_push import WebPushService


class ActorLike(Protocol):
    @property
    def user_id(self) -> int: ...


def register_web_push_routes(
    app: Any,
    *,
    resolve_actor: Callable[[], ActorLike | None],
    service: WebPushService,
    vapid_public_key: str | None,
) -> None:
    blueprint = Blueprint("web_push_v1", __name__, url_prefix="/api/v1/users/me/push")

    def actor() -> tuple[ActorLike | None, tuple[Response, int] | None]:
        current = resolve_actor()
        if current is None:
            return None, (jsonify({"error": {"code": "unauthorized"}}), 401)
        return current, None

    def tls_required() -> tuple[Response, int] | None:
        if request.is_secure:
            return None
        try:
            peer = ip_address(request.remote_addr or "")
        except ValueError:
            return jsonify({"error": {"code": "tls_required"}}), 400
        if peer.is_loopback:
            return None
        return jsonify({"error": {"code": "tls_required"}}), 400

    @blueprint.get("/vapid-key")
    def vapid_key() -> tuple[Response, int] | Response:
        tls_failure = tls_required()
        if tls_failure is not None:
            return tls_failure
        if actor()[1] is not None:
            return actor()[1]  # type: ignore[return-value]
        if not vapid_public_key:
            return jsonify({"configured": False, "public_key": None}), 503
        return jsonify({"configured": True, "public_key": vapid_public_key})

    @blueprint.get("/subscriptions")
    def subscriptions() -> tuple[Response, int] | Response:
        tls_failure = tls_required()
        if tls_failure is not None:
            return tls_failure
        current, failure = actor()
        if failure:
            return failure
        if current is None:
            return jsonify({"error": {"code": "unauthorized"}}), 401
        items = [asdict(item) for item in service.list_subscriptions(user_id=current.user_id)]
        return jsonify({"items": items, "total": len(items)})

    @blueprint.post("/subscriptions")
    def subscribe() -> tuple[Response, int] | Response:
        tls_failure = tls_required()
        if tls_failure is not None:
            return tls_failure
        current, failure = actor()
        if failure:
            return failure
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), dict):
            return jsonify({"error": {"code": "invalid_request"}}), 400
        keys = payload["keys"]
        try:
            item = service.subscribe(
                user_id=current.user_id,  # type: ignore[union-attr]
                endpoint=str(payload.get("endpoint", "")),
                p256dh=str(keys.get("p256dh", "")),
                auth=str(keys.get("auth", "")),
                device_label=payload.get("device_label"),
            )
        except ValueError as exc:
            return jsonify({"error": {"code": "invalid_subscription", "message": str(exc)}}), 400
        return jsonify(asdict(item)), 201

    @blueprint.delete("/subscriptions/<int:subscription_id>")
    def unsubscribe(subscription_id: int) -> tuple[Response, int] | Response:
        tls_failure = tls_required()
        if tls_failure is not None:
            return tls_failure
        current, failure = actor()
        if failure:
            return failure
        if current is None:
            return jsonify({"error": {"code": "unauthorized"}}), 401
        if not service.unsubscribe(user_id=current.user_id, subscription_id=subscription_id):
            return jsonify({"error": {"code": "not_found"}}), 404
        return jsonify({"deleted": True})

    @blueprint.get("/rules")
    def rules() -> tuple[Response, int] | Response:
        tls_failure = tls_required()
        if tls_failure is not None:
            return tls_failure
        current, failure = actor()
        if failure:
            return failure
        if current is None:
            return jsonify({"error": {"code": "unauthorized"}}), 401
        items = service.list_rules(user_id=current.user_id)
        return jsonify({"items": items, "total": len(items)})

    @blueprint.put("/rules/<event_type>")
    def put_rule(event_type: str) -> tuple[Response, int] | Response:
        tls_failure = tls_required()
        if tls_failure is not None:
            return tls_failure
        current, failure = actor()
        if failure:
            return failure
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict) or not isinstance(payload.get("enabled"), bool):
            return jsonify({"error": {"code": "invalid_request"}}), 400
        filters = payload.get("filters", {})
        if not isinstance(filters, dict):
            return jsonify({"error": {"code": "invalid_request"}}), 400
        try:
            result = service.set_rule(
                user_id=current.user_id,  # type: ignore[union-attr]
                event_type=event_type,
                enabled=payload["enabled"],
                filters=filters,
            )
        except ValueError as exc:
            return jsonify({"error": {"code": "unsupported_event", "message": str(exc)}}), 400
        return jsonify(result)

    @blueprint.delete("/rules/<event_type>")
    def delete_rule(event_type: str) -> tuple[Response, int] | Response:
        tls_failure = tls_required()
        if tls_failure is not None:
            return tls_failure
        current, failure = actor()
        if failure:
            return failure
        try:
            deleted = service.delete_rule(
                user_id=current.user_id,  # type: ignore[union-attr]
                event_type=event_type,
            )
        except ValueError as exc:
            return jsonify({"error": {"code": "unsupported_event", "message": str(exc)}}), 400
        return jsonify({"deleted": deleted, "event_type": event_type})

    @blueprint.post("/test")
    def test_notification() -> tuple[Response, int] | Response:
        tls_failure = tls_required()
        if tls_failure is not None:
            return tls_failure
        current, failure = actor()
        if failure:
            return failure
        try:
            sent = service.deliver(
                user_id=current.user_id,  # type: ignore[union-attr]
                event_type="book.available",
                payload={"title": "BookFlow testmelding", "url": "/"},
            )
        except RuntimeError:
            return jsonify({"error": {"code": "push_not_configured"}}), 503
        return jsonify({"sent": sent})

    app.register_blueprint(blueprint)
