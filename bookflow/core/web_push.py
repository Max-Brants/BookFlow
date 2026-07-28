"""Personal web-push subscriptions and event filtering.

Delivery is transport-injected so the durable job worker can use a VAPID
implementation without ever serialising subscription secrets into job logs.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

SUPPORTED_PUSH_EVENTS = frozenset(
    {
        "monitor.discovery",
        "request.status",
        "book.available",
        "request.error",
        "metadata_report.status",
        "backup.error",
    }
)


class PushTransport(Protocol):
    def send(self, subscription: dict[str, str], payload: dict[str, Any]) -> int: ...


class VapidWebPushTransport:
    """Standards-compliant RFC 8292 transport backed by ``pywebpush``."""

    def __init__(self, *, private_key: str, subject: str) -> None:
        if not private_key.strip() or not subject.startswith(("mailto:", "https://")):
            raise ValueError("A VAPID private key and mailto:/https: subject are required")
        self._private_key = private_key
        self._claims: dict[str, str | int] = {"sub": subject}

    def send(self, subscription: dict[str, str], payload: dict[str, Any]) -> int:
        try:
            from pywebpush import WebPushException, webpush
        except ImportError as exc:
            raise RuntimeError("Web-push support is not installed") from exc
        try:
            response = webpush(
                subscription_info={
                    "endpoint": subscription["endpoint"],
                    "keys": {
                        "p256dh": subscription["p256dh"],
                        "auth": subscription["auth"],
                    },
                },
                data=json.dumps(payload, separators=(",", ":")),
                vapid_private_key=self._private_key,
                vapid_claims=self._claims.copy(),
                ttl=300,
            )
        except WebPushException as exc:
            response = getattr(exc, "response", None)
            status_code = getattr(response, "status_code", None)
            if not isinstance(status_code, int):
                raise TypeError("Web-push delivery failed") from exc
            return status_code
        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int):
            raise TypeError("Web-push transport returned no HTTP status")
        return status_code


@dataclass(frozen=True, slots=True)
class PushSubscription:
    id: int
    device_label: str | None
    created_at: str
    last_success_at: str | None


class WebPushService:
    """Store sensitive subscription material and deliver filtered events."""

    def __init__(self, db_path: str, *, transport: PushTransport | None = None) -> None:
        self._db_path = db_path
        self._transport = transport

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def subscribe(
        self,
        *,
        user_id: int,
        endpoint: str,
        p256dh: str,
        auth: str,
        device_label: str | None,
    ) -> PushSubscription:
        if device_label is not None and not isinstance(device_label, str):
            raise ValueError("device_label must be a string")
        normalized_label = device_label.strip()[:100] if device_label else None
        parsed = urlsplit(endpoint)
        host = parsed.hostname
        # Production browser push services are HTTPS.  A loopback HTTP endpoint
        # is useful for local browser integration tests, but malformed URLs,
        # credentials, fragments and public HTTP are never persisted.
        loopback_host = host in {"localhost", "127.0.0.1", "::1"}
        allowed_scheme = parsed.scheme == "https" or (parsed.scheme == "http" and loopback_host)
        if (
            not allowed_scheme
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
            or not p256dh
            or not auth
        ):
            raise ValueError("A valid HTTPS (or loopback HTTP) web-push subscription is required")
        endpoint_hash = hashlib.sha256(endpoint.encode()).hexdigest()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO push_subscriptions
                    (user_id, endpoint_hash, endpoint, p256dh, auth_secret, device_label)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, endpoint_hash) DO UPDATE SET
                    endpoint = excluded.endpoint,
                    p256dh = excluded.p256dh,
                    auth_secret = excluded.auth_secret,
                    device_label = excluded.device_label,
                    revoked_at = NULL
                """,
                (user_id, endpoint_hash, endpoint, p256dh, auth, normalized_label),
            )
            row = conn.execute(
                """
                SELECT id, device_label, created_at, last_success_at
                FROM push_subscriptions
                WHERE user_id = ? AND endpoint_hash = ?
                """,
                (user_id, endpoint_hash),
            ).fetchone()
        if row is None:
            raise RuntimeError("Subscription could not be stored")
        return PushSubscription(**dict(row))

    def list_subscriptions(self, *, user_id: int) -> list[PushSubscription]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, device_label, created_at, last_success_at
                FROM push_subscriptions
                WHERE user_id = ? AND revoked_at IS NULL ORDER BY id DESC
                """,
                (user_id,),
            ).fetchall()
        return [PushSubscription(**dict(row)) for row in rows]

    def unsubscribe(self, *, user_id: int, subscription_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE push_subscriptions SET revoked_at = CURRENT_TIMESTAMP
                WHERE id = ? AND user_id = ? AND revoked_at IS NULL
                """,
                (subscription_id, user_id),
            )
        return cursor.rowcount == 1

    def set_rule(
        self, *, user_id: int, event_type: str, enabled: bool, filters: dict[str, Any]
    ) -> dict[str, Any]:
        if event_type not in SUPPORTED_PUSH_EVENTS:
            raise ValueError("Unsupported notification event")
        filters_json = json.dumps(filters, sort_keys=True, separators=(",", ":"))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO notification_rules (user_id, event_type, enabled, filters_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, event_type) DO UPDATE SET
                    enabled = excluded.enabled,
                    filters_json = excluded.filters_json,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, event_type, int(enabled), filters_json),
            )
        return {"event_type": event_type, "enabled": enabled, "filters": filters}

    def list_rules(self, *, user_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_type, enabled, filters_json
                FROM notification_rules WHERE user_id = ? ORDER BY event_type
                """,
                (user_id,),
            ).fetchall()
        configured = {
            str(row["event_type"]): {
                "event_type": str(row["event_type"]),
                "enabled": bool(row["enabled"]),
                "filters": json.loads(str(row["filters_json"])),
            }
            for row in rows
        }
        return [
            configured.get(event, {"event_type": event, "enabled": True, "filters": {}})
            for event in sorted(SUPPORTED_PUSH_EVENTS)
        ]

    def delete_rule(self, *, user_id: int, event_type: str) -> bool:
        """Remove a customization so the event returns to its enabled default."""
        if event_type not in SUPPORTED_PUSH_EVENTS:
            raise ValueError("Unsupported notification event")
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM notification_rules WHERE user_id = ? AND event_type = ?",
                (user_id, event_type),
            )
        return cursor.rowcount == 1

    def deliver(self, *, user_id: int, event_type: str, payload: dict[str, Any]) -> int:
        """Send an event and retire endpoints returning 404/410."""
        if self._transport is None:
            raise RuntimeError("Web-push transport is not configured")
        with self._connect() as conn:
            rule = conn.execute(
                "SELECT enabled, filters_json FROM notification_rules WHERE user_id = ? AND event_type = ?",
                (user_id, event_type),
            ).fetchone()
            if rule is not None and not bool(rule["enabled"]):
                return 0
            if rule is not None:
                try:
                    filters = json.loads(str(rule["filters_json"]))
                except json.JSONDecodeError:
                    filters = {}
                if not isinstance(filters, dict) or not _matches_filters(payload, filters):
                    return 0
            subscriptions = conn.execute(
                """
                SELECT id, endpoint, p256dh, auth_secret FROM push_subscriptions
                WHERE user_id = ? AND revoked_at IS NULL
                """,
                (user_id,),
            ).fetchall()
            sent = 0
            for subscription in subscriptions:
                status = self._transport.send(
                    {
                        "endpoint": str(subscription["endpoint"]),
                        "p256dh": str(subscription["p256dh"]),
                        "auth": str(subscription["auth_secret"]),
                    },
                    {"event": event_type, **payload},
                )
                if status in {404, 410}:
                    conn.execute(
                        "UPDATE push_subscriptions SET revoked_at = ? WHERE id = ?",
                        (datetime.now(UTC).isoformat(timespec="seconds"), int(subscription["id"])),
                    )
                elif 200 <= status < 300:
                    sent += 1
                    conn.execute(
                        "UPDATE push_subscriptions SET last_success_at = ? WHERE id = ?",
                        (datetime.now(UTC).isoformat(timespec="seconds"), int(subscription["id"])),
                    )
                else:
                    # Let the durable worker retry transport/server failures.
                    # Only explicit gone endpoints are terminal and retired.
                    raise RuntimeError(f"Web-push delivery returned HTTP {status}")
        return sent


def _matches_filters(payload: dict[str, Any], filters: dict[str, Any]) -> bool:
    """Match only explicit, scalar/list rule filters; unknown payloads never pass."""
    for key, expected in filters.items():
        actual = payload.get(key)
        if isinstance(expected, list):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True
