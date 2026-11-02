from unittest.mock import patch

from bookflow.metadata_providers.hardcover import _test_hardcover_connection


def test_short_token_is_validated_by_hardcover():
    with (
        patch("bookflow.metadata_providers.hardcover.HardcoverProvider") as provider,
        patch("bookflow.metadata_providers.hardcover._save_connected_user") as save_user,
    ):
        provider.return_value._execute_query.return_value = {
            "me": [{"id": 42, "username": "reader"}]
        }

        result = _test_hardcover_connection({"HARDCOVER_API_KEY": "Bearer hc_pat_short"})

    provider.assert_called_once_with(api_key="hc_pat_short")
    provider.return_value._execute_query.assert_called_once_with(
        "query { me { id, username } }", {}
    )
    save_user.assert_called_once_with("42", "reader")
    assert result == {"success": True, "message": "Connected as: reader"}


def test_rejected_short_token_reports_failure():
    with (
        patch("bookflow.metadata_providers.hardcover.HardcoverProvider") as provider,
        patch("bookflow.metadata_providers.hardcover._save_connected_user") as save_user,
    ):
        provider.return_value._execute_query.return_value = None

        result = _test_hardcover_connection({"HARDCOVER_API_KEY": "invalid"})

    provider.return_value._execute_query.assert_called_once()
    save_user.assert_called_once_with(None, None)
    assert result == {"success": False, "message": "API request failed - check your API key"}
