"""Regression coverage for settings retired by the catalog request process."""

from bookflow.config.settings import download_settings, general_settings
from scripts.generate_env_docs import generate_env_docs


def test_library_url_and_downloads_sidebar_settings_are_not_registered() -> None:
    keys = {
        field.key
        for settings_factory in (general_settings, download_settings)
        for field in settings_factory()
    }

    assert "CALIBRE_WEB_URL" not in keys
    assert "AUTO_OPEN_DOWNLOADS_SIDEBAR" not in keys


def test_retired_settings_are_not_emitted_as_environment_variables() -> None:
    docs = generate_env_docs()

    assert "CALIBRE_WEB_URL" not in docs
    assert "AUTO_OPEN_DOWNLOADS_SIDEBAR" not in docs
