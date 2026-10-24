"""Tests for the Hardcover settings "Test Connection" action."""

from typing import Any

import pytest

from bookflow.metadata_providers import hardcover
from bookflow.metadata_providers.hardcover import HardcoverProvider, _test_hardcover_connection

# Hardcover's scoped personal access tokens (since August 2026) are ~50 chars;
# legacy keys were long JWTs. Neither value is a real credential.
PAT_STYLE_KEY = "x" * 51
LEGACY_JWT_STYLE_KEY = "eyJ" + "a" * 400


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the API call and config writes; record what the test action did."""
    state: dict[str, Any] = {"queries": [], "saved": []}

    def fake_execute_query(self: HardcoverProvider, query: str, variables: dict) -> dict:
        state["queries"].append((self.api_key, query))
        return {"me": [{"id": 42, "username": "reader"}]}

    monkeypatch.setattr(HardcoverProvider, "_execute_query", fake_execute_query)
    monkeypatch.setattr(
        hardcover,
        "_save_connected_user",
        lambda user_id, username: state["saved"].append((user_id, username)),
    )
    return state


@pytest.mark.parametrize("key", [PAT_STYLE_KEY, LEGACY_JWT_STYLE_KEY])
def test_accepts_personal_access_tokens_and_legacy_keys(captured, key):
    result = _test_hardcover_connection({"HARDCOVER_API_KEY": key})

    assert result == {"success": True, "message": "Connected as: reader"}
    assert captured["queries"][0][0] == key
    assert captured["saved"] == [("42", "reader")]


def test_strips_copied_bearer_prefix(captured):
    result = _test_hardcover_connection({"HARDCOVER_API_KEY": f"Bearer {PAT_STYLE_KEY}"})

    assert result["success"] is True
    assert captured["queries"][0][0] == PAT_STYLE_KEY


def test_rejects_obviously_truncated_key_without_calling_api(captured):
    result = _test_hardcover_connection({"HARDCOVER_API_KEY": "x" * 10})

    assert result["success"] is False
    assert "too short (10 chars)" in result["message"]
    assert captured["queries"] == []
