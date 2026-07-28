"""API tests for administrator notification targets."""

import importlib
import uuid
from unittest.mock import patch

import pytest


@pytest.fixture(scope="module")
def main_module():
    with patch("bookflow.download.orchestrator.start"):
        import bookflow.main as main

        importlib.reload(main)
        return main


def _session(client, user):
    with client.session_transaction() as session:
        session["user_id"] = user["username"]
        session["db_user_id"] = user["id"]
        session["is_admin"] = user["role"] == "admin"


def test_notification_targets_are_admin_only_and_round_trip(main_module):
    admin = main_module.user_db.create_user(username=f"admin-{uuid.uuid4().hex}", role="admin")
    member = main_module.user_db.create_user(username=f"member-{uuid.uuid4().hex}")
    client = main_module.app.test_client()
    client.environ_base["HTTP_ORIGIN"] = "http://localhost"
    with patch.object(main_module, "get_auth_mode", return_value="builtin"):
        _session(client, member)
        forbidden = client.put(
            "/api/settings/notifications", json={"ADMIN_NOTIFICATION_TARGETS": []}
        )
        _session(client, admin)
        saved = client.put(
            "/api/settings/notifications",
            json={
                "ADMIN_NOTIFICATION_TARGETS": [
                    {
                        "transport": "apprise",
                        "destination": "ntfys://ntfy.sh/ops",
                        "events": ["request_created"],
                    }
                ]
            },
        )
        settings = client.get("/api/settings/notifications")
    assert forbidden.status_code == 403
    assert saved.status_code == 200
    fields = {field["key"]: field for field in settings.json["fields"] if "key" in field}
    assert fields["ADMIN_NOTIFICATION_TARGETS"]["value"] == [
        {
            "transport": "apprise",
            "destination": "ntfys://ntfy.sh/ops",
            "events": ["request_created"],
        }
    ]
