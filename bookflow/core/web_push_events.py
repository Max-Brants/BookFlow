"""Safe, durable producers for personal web-push events.

Event producers never call a push transport in the request/download path.  They
only enqueue a small, non-secret payload; the runtime-owned ``send_web_push``
handler delivers it after the originating transaction has committed.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from bookflow.core.durable_jobs import DurableJobService
from bookflow.core.notifications import notify_personal_event
from bookflow.core.web_push import SUPPORTED_PUSH_EVENTS


def enqueue_web_push(
    database_path: str,
    *,
    user_id: int,
    event_type: str,
    payload: dict[str, Any],
    event_key: str,
) -> None:
    """Idempotently persist one eventual personal notification.

    ``event_key`` must name the committed domain transition (rather than use a
    timestamp), making duplicate callbacks safe across retry/restart paths.
    """
    if event_type not in SUPPORTED_PUSH_EVENTS or user_id < 1 or not event_key:
        raise ValueError("Invalid web-push event")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(f"{user_id}\0{event_type}\0{event_key}".encode()).hexdigest()[:32]
    try:
        DurableJobService(database_path).enqueue(
            job_key=f"web-push:{event_type}:{digest}",
            job_type="send_web_push",
            payload={"user_id": user_id, "event_type": event_type, "payload": json.loads(encoded)},
            max_attempts=3,
        )
        notify_personal_event(
            database_path,
            user_id=user_id,
            event_type=event_type,
            payload=json.loads(encoded),
        )
    except sqlite3.Error:
        # Notifications must not roll back an already committed user action;
        # this also keeps isolated older-schema test databases compatible.
        return


def enqueue_admin_web_push(
    database_path: str, *, event_type: str, payload: dict[str, Any], event_key: str
) -> int:
    """Queue the same operational event to every active administrator."""
    conn = sqlite3.connect(database_path)
    try:
        rows = conn.execute(
            "SELECT id FROM users WHERE role = 'admin' AND is_active = 1"
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        enqueue_web_push(
            database_path,
            user_id=int(row[0]),
            event_type=event_type,
            payload=payload,
            event_key=f"{event_key}:{int(row[0])}",
        )
    return len(rows)
