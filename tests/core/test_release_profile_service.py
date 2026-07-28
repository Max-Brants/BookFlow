from __future__ import annotations

import pytest

from bookflow.core.release_profile_service import (
    ReleaseProfileError,
    ReleaseProfileService,
    release_profile_from_snapshot,
)
from bookflow.core.user_db import UserDB


def test_named_profiles_keep_one_active_default_and_round_trip_config(tmp_path):
    db_path = tmp_path / "users.db"
    UserDB(str(db_path)).initialize()
    service = ReleaseProfileService(db_path)

    original_default = service.list(active_only=True)[0]
    preferred = service.create(
        name="Dutch EPUB",
        is_default=True,
        config={
            "allowed_formats": ["epub"],
            "allowed_indexers": ["prowlarr"],
            "allowed_languages": ["nl"],
            "minimum_automatic_score": 75,
            "term_scores": {"retail": 20, "ocr": -100},
        },
    )

    profiles = service.list()
    assert sum(profile["is_default"] for profile in profiles) == 1
    assert preferred["is_default"] is True
    assert preferred["config"]["allowed_indexers"] == ["prowlarr"]
    assert preferred["config"]["minimum_automatic_score"] == 75
    assert (
        next(profile for profile in profiles if profile["id"] == original_default["id"])[
            "is_default"
        ]
        is False
    )


def test_profile_snapshot_builds_all_automatic_search_filters():
    profile = release_profile_from_snapshot(
        {
            "allowed_formats": ["epub"],
            "allowed_protocols": ["torrent"],
            "allowed_indexers": ["indexer-a"],
            "allowed_languages": ["nl"],
            "minimum_automatic_score": 125,
        },
        title="Book",
        author="Author",
        language="nl",
        publish_year=2026,
    )

    assert profile.allowed_indexers == ("indexer-a",)
    assert profile.allowed_languages == ("nl",)
    assert profile.minimum_automatic_score == 125


def test_default_profile_cannot_be_created_inactive(tmp_path):
    db_path = tmp_path / "users.db"
    UserDB(str(db_path)).initialize()

    with pytest.raises(ReleaseProfileError, match="must stay active"):
        ReleaseProfileService(db_path).create(
            name="Inactive default",
            config={},
            is_default=True,
            is_active=False,
        )
