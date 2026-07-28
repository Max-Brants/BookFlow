"""Tests for auth mode and admin policy helpers used by OIDC integration."""

import sqlite3

import pytest

from bookflow.core.auth_modes import (
    AUTH_MODE_UNAVAILABLE,
    determine_auth_mode,
    get_auth_check_admin_status,
    get_settings_tab_from_path,
    is_settings_or_onboarding_path,
    load_active_auth_mode,
    requires_admin_for_settings_access,
    should_restrict_settings_to_admin,
)


class TestDetermineAuthMode:
    def test_returns_none_only_when_explicitly_configured(self):
        assert determine_auth_mode({"AUTH_METHOD": "none"}, cwa_db_path=None) == "none"

    def test_returns_oidc_when_fully_configured(self):
        config = {
            "AUTH_METHOD": "oidc",
            "OIDC_DISCOVERY_URL": "https://auth.example.com/.well-known/openid-configuration",
            "OIDC_CLIENT_ID": "bookflow",
        }
        assert determine_auth_mode(config, cwa_db_path=None) == "oidc"

    def test_returns_unavailable_when_oidc_missing_client_id(self):
        config = {
            "AUTH_METHOD": "oidc",
            "OIDC_DISCOVERY_URL": "https://auth.example.com/.well-known/openid-configuration",
        }
        assert determine_auth_mode(config, cwa_db_path=None) == AUTH_MODE_UNAVAILABLE

    def test_returns_unavailable_when_oidc_missing_discovery_url(self):
        config = {
            "AUTH_METHOD": "oidc",
            "OIDC_CLIENT_ID": "bookflow",
        }
        assert determine_auth_mode(config, cwa_db_path=None) == AUTH_MODE_UNAVAILABLE

    def test_builtin_still_works(self):
        config = {
            "AUTH_METHOD": "builtin",
        }
        assert determine_auth_mode(config, cwa_db_path=None) == "builtin"

    def test_builtin_without_local_admin_is_unavailable(self):
        config = {
            "AUTH_METHOD": "builtin",
        }
        assert (
            determine_auth_mode(config, cwa_db_path=None, has_local_admin=False)
            == AUTH_MODE_UNAVAILABLE
        )

    def test_proxy_still_works(self):
        config = {
            "AUTH_METHOD": "proxy",
            "PROXY_AUTH_USER_HEADER": "X-Auth-User",
        }
        assert determine_auth_mode(config, cwa_db_path=None) == "proxy"

    def test_oidc_without_local_admin_is_unavailable(self):
        config = {
            "AUTH_METHOD": "oidc",
            "OIDC_DISCOVERY_URL": "https://auth.example.com/.well-known/openid-configuration",
            "OIDC_CLIENT_ID": "bookflow",
        }
        assert (
            determine_auth_mode(config, cwa_db_path=None, has_local_admin=False)
            == AUTH_MODE_UNAVAILABLE
        )

    @pytest.mark.parametrize(
        "config",
        [
            {"AUTH_METHOD": "cwa"},
            {"AUTH_METHOD": "proxy"},
            {"AUTH_METHOD": "unknown"},
            {},
        ],
    )
    def test_missing_or_unknown_auth_prerequisite_is_unavailable(self, config):
        assert determine_auth_mode(config, cwa_db_path=None) == AUTH_MODE_UNAVAILABLE

    @pytest.mark.parametrize(
        ("auth_mode", "config"),
        [
            ("builtin", {"AUTH_METHOD": "builtin"}),
            (
                "oidc",
                {
                    "AUTH_METHOD": "oidc",
                    "OIDC_DISCOVERY_URL": "https://auth.example.com/.well-known/openid-configuration",
                    "OIDC_CLIENT_ID": "bookflow",
                },
            ),
        ],
    )
    def test_disable_local_auth_keeps_configured_mode_without_admin(self, auth_mode, config):
        assert (
            determine_auth_mode(
                config,
                cwa_db_path=None,
                has_local_admin=False,
                disable_local_auth=True,
            )
            == auth_mode
        )

    def test_load_active_auth_mode_reads_env_backed_cwa_setting(self, monkeypatch, tmp_path):
        from bookflow.core.config import config as app_config

        monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("AUTH_METHOD", "cwa")
        app_config.refresh(force=True)

        cwa_db_path = tmp_path / "app.db"
        conn = sqlite3.connect(cwa_db_path)
        conn.execute("create table user (name text)")
        conn.commit()
        conn.close()

        try:
            assert load_active_auth_mode(cwa_db_path) == "cwa"
        finally:
            monkeypatch.delenv("AUTH_METHOD", raising=False)
            app_config.refresh(force=True)

    def test_load_active_auth_mode_reads_env_backed_proxy_setting(self, monkeypatch, tmp_path):
        from bookflow.core.config import config as app_config

        monkeypatch.setenv("CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("AUTH_METHOD", "proxy")
        monkeypatch.setenv("PROXY_AUTH_USER_HEADER", "X-Forwarded-User")
        app_config.refresh(force=True)

        try:
            assert load_active_auth_mode(cwa_db_path=None) == "proxy"
        finally:
            monkeypatch.delenv("AUTH_METHOD", raising=False)
            monkeypatch.delenv("PROXY_AUTH_USER_HEADER", raising=False)
            app_config.refresh(force=True)

    def test_load_active_auth_mode_is_unavailable_when_config_read_fails(self, monkeypatch):
        from bookflow.core.config import config as app_config

        def raise_read_error(*_args, **_kwargs):
            raise OSError

        monkeypatch.setattr(app_config, "get", raise_read_error)

        assert load_active_auth_mode(cwa_db_path=None) == AUTH_MODE_UNAVAILABLE

    def test_load_active_auth_mode_is_unavailable_when_admin_check_fails(self, monkeypatch):
        from bookflow.core.config import config as app_config

        def get_builtin_mode(key, default=None):
            return "builtin" if key == "AUTH_METHOD" else default

        def raise_admin_check_error(_user_db):
            raise sqlite3.OperationalError

        monkeypatch.setattr(app_config, "get", get_builtin_mode)
        monkeypatch.setattr(
            "bookflow.core.auth_modes.has_local_password_admin",
            raise_admin_check_error,
        )

        assert load_active_auth_mode(cwa_db_path=None) == AUTH_MODE_UNAVAILABLE


class TestSettingsRestrictionPolicy:
    def test_settings_path_detection(self):
        assert is_settings_or_onboarding_path("/api/settings/downloads")
        assert is_settings_or_onboarding_path("/api/onboarding")
        assert not is_settings_or_onboarding_path("/api/releases")

    def test_default_is_admin_restricted(self):
        assert should_restrict_settings_to_admin({}) is True

    def test_restriction_is_always_enabled(self):
        assert should_restrict_settings_to_admin({"RESTRICT_SETTINGS_TO_ADMIN": True}) is True
        assert should_restrict_settings_to_admin({"RESTRICT_SETTINGS_TO_ADMIN": False}) is True

    def test_extracts_settings_tab_from_path(self):
        assert get_settings_tab_from_path("/api/settings/security") == "security"
        assert get_settings_tab_from_path("/api/settings/users/action/open_users_tab") == "users"
        assert get_settings_tab_from_path("/api/settings") is None

    def test_security_and_users_tabs_always_require_admin(self):
        users_config = {"RESTRICT_SETTINGS_TO_ADMIN": False}
        assert requires_admin_for_settings_access("/api/settings/security", users_config) is True
        assert requires_admin_for_settings_access("/api/settings/users", users_config) is True

    def test_other_tabs_also_require_admin(self):
        assert (
            requires_admin_for_settings_access(
                "/api/settings/general",
                {"RESTRICT_SETTINGS_TO_ADMIN": False},
            )
            is True
        )
        assert (
            requires_admin_for_settings_access(
                "/api/settings/general",
                {"RESTRICT_SETTINGS_TO_ADMIN": True},
            )
            is True
        )


class TestAuthCheckAdminStatus:
    def test_authenticated_admin_when_restricted(self):
        result = get_auth_check_admin_status(
            "oidc",
            {"RESTRICT_SETTINGS_TO_ADMIN": True},
            {"user_id": "admin", "is_admin": True},
        )
        assert result is True

    def test_authenticated_non_admin_when_restricted(self):
        result = get_auth_check_admin_status(
            "oidc",
            {"RESTRICT_SETTINGS_TO_ADMIN": True},
            {"user_id": "user", "is_admin": False},
        )
        assert result is False

    def test_authenticated_non_admin_user_is_not_admin(self):
        result = get_auth_check_admin_status(
            "proxy",
            {"RESTRICT_SETTINGS_TO_ADMIN": False},
            {"user_id": "user", "is_admin": False},
        )
        assert result is False

    def test_unauthenticated_is_never_admin(self):
        result = get_auth_check_admin_status(
            "builtin",
            {"RESTRICT_SETTINGS_TO_ADMIN": False},
            {"is_admin": True},
        )
        assert result is False
