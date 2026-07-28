"""API tests for the frontend config endpoint."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(scope="module")
def main_module():
    """Import `bookflow.main` with background startup disabled."""
    with patch("bookflow.download.orchestrator.start"):
        import bookflow.main as main

        importlib.reload(main)
        return main


@pytest.fixture
def client(main_module):
    test_client = main_module.app.test_client()
    test_client.environ_base["HTTP_ORIGIN"] = "http://localhost"
    return test_client


def _set_session(client, *, user_id: str, db_user_id: int, is_admin: bool) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = user_id
        sess["db_user_id"] = db_user_id
        sess["is_admin"] = is_admin


def test_config_endpoint_uses_user_scope_and_runtime_flags(main_module, client):
    _set_session(client, user_id="reader-1", db_user_id=42, is_admin=False)

    calls: list[tuple[str, int | None]] = []

    def fake_get(key, default=None, user_id=None):
        calls.append((key, user_id))
        values = {
            "SHOW_RELEASE_SOURCE_LINKS": False,
            "METADATA_PROVIDER": "openlibrary",
            "DEFAULT_RELEASE_SOURCE": "prowlarr",
            "HARDCOVER_AUTO_REMOVE_ON_DOWNLOAD": True,
        }
        return values.get(key, default)

    with (
        patch.object(main_module, "get_auth_mode", return_value="builtin"),
        patch.object(main_module.app_config, "get", side_effect=fake_get),
        patch("bookflow.config.env._is_config_dir_writable", return_value=True),
        patch("bookflow.core.onboarding.is_onboarding_complete", return_value=True),
        patch("bookflow.metadata_providers.get_provider_sort_options", return_value=["sort-a"]),
        patch("bookflow.metadata_providers.get_provider_search_fields", return_value=["field-a"]),
        patch("bookflow.metadata_providers.get_provider_default_sort", return_value="relevance"),
    ):
        resp = client.get("/api/config")

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["show_release_source_links"] is False
    assert data["metadata_sort_options"] == ["sort-a"]
    assert data["metadata_search_fields"] == ["field-a"]
    assert data["default_release_source"] == "prowlarr"
    assert "default_release_source_audiobook" not in data
    assert "calibre_web_url" not in data
    assert "auto_open_downloads_sidebar" not in data
    assert data["settings_enabled"] is True
    assert data["metadata_default_sort"] == "relevance"

    assert ("SHOW_RELEASE_SOURCE_LINKS", None) in calls


def test_frontend_dist_resolves_from_repo_root(main_module):
    expected_project_root = Path(main_module.__file__).resolve().parent.parent

    assert main_module.PROJECT_ROOT == expected_project_root
    assert main_module.FRONTEND_DIST == expected_project_root / "frontend-dist"
